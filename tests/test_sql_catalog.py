from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from vn_event_dw.api import create_app
from vn_event_dw.etl import init_db, open_connection
from vn_event_dw.sql_catalog import (
    APPROVED_ANALYST_TABLES,
    default_catalog_path,
    load_sql_catalog,
    validate_sql_catalog,
)


class SqlCatalogTests(unittest.TestCase):
    def test_packaged_catalog_matches_fresh_warehouse_schema(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            db_path = Path(temporary_directory) / "warehouse.db"
            conn = open_connection(db_path)
            try:
                init_db(conn)
                catalog = load_sql_catalog()
                self.assertEqual(set(catalog.objects), APPROVED_ANALYST_TABLES)
                self.assertEqual(validate_sql_catalog(catalog, conn), [])
            finally:
                conn.close()

    def test_catalog_rejects_nonexistent_column_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            catalog_path = Path(temporary_directory) / "catalog.json"
            payload = json.loads(default_catalog_path().read_text(encoding="utf-8"))
            payload["objects"]["raw_fb_posts"]["columns"]["not_a_real_column"] = {
                "description": "Invalid test column.",
                "semantic_type": "text",
                "unit": "text",
                "additivity": "non_additive",
                "default_aggregation": "none",
                "null_policy": "preserve",
                "analyst_visible": True,
            }
            catalog_path.write_text(json.dumps(payload), encoding="utf-8")

            conn = open_connection(Path(temporary_directory) / "warehouse.db")
            try:
                init_db(conn)
                errors = validate_sql_catalog(load_sql_catalog(catalog_path), conn)
            finally:
                conn.close()

        self.assertIn(
            "raw_fb_posts advertises nonexistent columns: not_a_real_column",
            errors,
        )

    def test_catalog_loader_rejects_invalid_json_without_touching_service_code(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            catalog_path = Path(temporary_directory) / "catalog.json"
            catalog_path.write_text("{ not valid JSON", encoding="utf-8")
            with self.assertRaises(json.JSONDecodeError):
                load_sql_catalog(catalog_path)

            # The public API never loads optional analyst metadata at startup.
            app = create_app(db_path=Path(temporary_directory) / "warehouse.db")
            self.assertEqual(app.title, "VN Event DW API")
