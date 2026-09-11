"""Validation helpers for the Event warehouse SQL semantics catalog.

The catalog is intentionally optional at runtime.  It documents the SQLite
schema for external query clients, while this module keeps that documentation
synchronized with the physical warehouse schema during development and deploys.
"""

from __future__ import annotations

import json
import re
import sqlite3
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


CATALOG_VERSION = 1

APPROVED_ANALYST_TABLES = frozenset(
    {
        "config_app_mapping",
        "raw_fb_posts",
        "raw_st_app_update",
        "raw_st_version",
        "st_app_update_events",
        "st_version_events",
        "post_event_detection",
        "post_event_objects",
        "unified_events",
        "unified_event_sources",
    }
)

_FORBIDDEN_SQL = re.compile(
    r"\b(?:insert|update|delete|drop|alter|create|attach|pragma|vacuum|replace)\b",
    flags=re.IGNORECASE,
)


class CatalogColumn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    description: str = Field(min_length=1)
    semantic_type: Literal[
        "identifier",
        "name",
        "category",
        "text",
        "boolean",
        "integer",
        "number",
        "ratio",
        "currency",
        "date",
        "timestamp",
        "month",
        "url",
        "json",
    ]
    unit: str = Field(min_length=1)
    additivity: Literal["additive", "semi_additive", "non_additive"]
    default_aggregation: str = Field(min_length=1)
    null_policy: Literal["preserve", "exclude", "zero", "unknown"]
    analyst_visible: bool = True


class CatalogJoinColumn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    from_column: str = Field(min_length=1)
    to_column: str = Field(min_length=1)


class CatalogCondition(BaseModel):
    model_config = ConfigDict(extra="forbid")

    table: str = Field(min_length=1)
    column: str = Field(min_length=1)
    operator: Literal["eq"]
    value: str = Field(min_length=1)


class CatalogRelationship(BaseModel):
    model_config = ConfigDict(extra="forbid")

    from_table: str = Field(alias="from", min_length=1)
    to_table: str = Field(alias="to", min_length=1)
    on: list[CatalogJoinColumn] = Field(min_length=1)
    conditions: list[CatalogCondition] = Field(default_factory=list)
    cardinality: Literal[
        "one_to_one",
        "one_to_zero_or_one",
        "one_to_many",
        "many_to_one",
        "many_to_many",
    ]
    description: str = Field(min_length=1)


class CatalogExample(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question: str = Field(min_length=1)
    sql: str = Field(min_length=1)


class CatalogObject(BaseModel):
    model_config = ConfigDict(extra="forbid")

    description: str = Field(min_length=1)
    grain: str = Field(min_length=1)
    grain_columns: list[str] = Field(min_length=1)
    analyst_visible: bool = True
    columns: dict[str, CatalogColumn]
    relationships: list[CatalogRelationship] = Field(default_factory=list)
    examples: list[CatalogExample] = Field(min_length=2)


class SqlCatalog(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: Literal[CATALOG_VERSION]
    objects: dict[str, CatalogObject]


def default_catalog_path() -> Path:
    return Path(__file__).with_name("sql_catalog.json")


def load_sql_catalog(path: Path | None = None) -> SqlCatalog:
    """Load and structurally validate a catalog without touching a database."""

    catalog_path = path or default_catalog_path()
    payload = json.loads(catalog_path.read_text(encoding="utf-8"))
    return SqlCatalog.model_validate(payload)


def _live_columns(connection: sqlite3.Connection, table: str) -> list[str]:
    return [str(row[1]) for row in connection.execute(f'PRAGMA table_info("{table}")')]


def _primary_key_columns(connection: sqlite3.Connection, table: str) -> list[str]:
    rows = connection.execute(f'PRAGMA table_info("{table}")').fetchall()
    return [str(row[1]) for row in sorted(rows, key=lambda row: int(row[5])) if int(row[5])]


def _is_read_only_sql(sql: str) -> bool:
    cleaned = sql.strip().rstrip(";")
    if not cleaned.lower().startswith(("select", "with")):
        return False
    return ";" not in cleaned and _FORBIDDEN_SQL.search(cleaned) is None


def validate_sql_catalog(catalog: SqlCatalog, connection: sqlite3.Connection) -> list[str]:
    """Return deterministic validation errors for catalog/schema drift."""

    errors: list[str] = []
    catalog_tables = set(catalog.objects)
    if catalog_tables != APPROVED_ANALYST_TABLES:
        missing = sorted(APPROVED_ANALYST_TABLES - catalog_tables)
        unexpected = sorted(catalog_tables - APPROVED_ANALYST_TABLES)
        if missing:
            errors.append(f"Catalog is missing approved tables: {', '.join(missing)}")
        if unexpected:
            errors.append(f"Catalog contains unapproved tables: {', '.join(unexpected)}")

    live_columns_by_table = {
        table: _live_columns(connection, table) for table in sorted(catalog_tables)
    }
    for table, entry in catalog.objects.items():
        live_columns = live_columns_by_table.get(table, [])
        if not live_columns:
            errors.append(f"Catalog table does not exist in SQLite: {table}")
            continue

        documented_columns = set(entry.columns)
        actual_columns = set(live_columns)
        missing_columns = sorted(actual_columns - documented_columns)
        unknown_columns = sorted(documented_columns - actual_columns)
        if missing_columns:
            errors.append(f"{table} is missing column metadata: {', '.join(missing_columns)}")
        if unknown_columns:
            errors.append(f"{table} advertises nonexistent columns: {', '.join(unknown_columns)}")

        primary_key = _primary_key_columns(connection, table)
        if entry.grain_columns != primary_key:
            errors.append(
                f"{table} grain_columns {entry.grain_columns!r} do not match primary key {primary_key!r}"
            )

        for relationship in entry.relationships:
            for related_table in (relationship.from_table, relationship.to_table):
                if related_table not in catalog.objects:
                    errors.append(
                        f"{table} relationship references non-catalog table: {related_table}"
                    )
                    continue
                if not live_columns_by_table.get(related_table):
                    errors.append(
                        f"{table} relationship references nonexistent SQLite table: {related_table}"
                    )
            from_columns = set(live_columns_by_table.get(relationship.from_table, []))
            to_columns = set(live_columns_by_table.get(relationship.to_table, []))
            for join in relationship.on:
                if join.from_column not in from_columns:
                    errors.append(
                        f"{table} relationship column does not exist: {relationship.from_table}.{join.from_column}"
                    )
                if join.to_column not in to_columns:
                    errors.append(
                        f"{table} relationship column does not exist: {relationship.to_table}.{join.to_column}"
                    )
            for condition in relationship.conditions:
                condition_columns = set(live_columns_by_table.get(condition.table, []))
                if condition.table not in {relationship.from_table, relationship.to_table}:
                    errors.append(
                        f"{table} relationship condition table is not part of the relationship: {condition.table}"
                    )
                elif condition.column not in condition_columns:
                    errors.append(
                        f"{table} relationship condition column does not exist: {condition.table}.{condition.column}"
                    )

        for index, example in enumerate(entry.examples, start=1):
            if not _is_read_only_sql(example.sql):
                errors.append(f"{table} example {index} is not one read-only SELECT/CTE statement")
                continue
            try:
                connection.execute(f"EXPLAIN QUERY PLAN {example.sql}").fetchall()
                connection.execute(f"SELECT * FROM ({example.sql}) AS catalog_example LIMIT 0").fetchall()
            except sqlite3.Error as exc:
                errors.append(f"{table} example {index} does not execute: {exc}")
    return errors
