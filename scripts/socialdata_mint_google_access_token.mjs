import fs from "node:fs/promises";
import path from "node:path";
import process from "node:process";
import {GoogleAuth} from "google-auth-library";

const DEFAULT_SCOPE = "https://www.googleapis.com/auth/userinfo.email";
const DEFAULT_SCOPES = [DEFAULT_SCOPE];

function usage() {
  console.error(
    [
      "Usage:",
      "  node scripts/socialdata_mint_google_access_token.mjs --key-file <path> [--scope <scope>] [--token-only]",
      "  npm run socialdata:mint-node-token -- --key-file <path> [--scope <scope>] [--token-only]",
    ].join("\n"),
  );
}

function parseArgs(argv) {
  let keyFile = "";
  const scopes = [];
  let tokenOnly = false;

  for (let index = 0; index < argv.length; index += 1) {
    const value = argv[index];
    if (value === "--key-file") {
      keyFile = argv[index + 1] || "";
      index += 1;
      continue;
    }
    if (value === "--scope") {
      scopes.push(argv[index + 1] || "");
      index += 1;
      continue;
    }
    if (value === "--token-only") {
      tokenOnly = true;
      continue;
    }
    if (value === "--help" || value === "-h") {
      usage();
      process.exit(0);
    }
    throw new Error(`Unknown argument: ${value}`);
  }

  if (!keyFile) {
    throw new Error("--key-file is required.");
  }

  return {
    keyFile,
    scopes: normalizeScopes(scopes.length > 0 ? scopes : process.env.SOCIALDATA_GOOGLE_SCOPES),
    tokenOnly,
  };
}

function normalizeScopes(rawScopes) {
  const candidates = Array.isArray(rawScopes)
    ? rawScopes.flatMap((scope) => scope.replaceAll(",", " ").split(/\s+/))
    : String(rawScopes || "").replaceAll(",", " ").split(/\s+/);
  const scopes = [...new Set(candidates.map((scope) => scope.trim()).filter(Boolean))];
  return scopes.length > 0 ? scopes : DEFAULT_SCOPES;
}

function normalizeAccessToken(tokenValue) {
  if (!tokenValue) {
    return "";
  }
  if (typeof tokenValue === "string") {
    return tokenValue;
  }
  if (typeof tokenValue === "object" && typeof tokenValue.token === "string") {
    return tokenValue.token;
  }
  return "";
}

const args = parseArgs(process.argv.slice(2));
const resolvedKeyFile = path.resolve(args.keyFile);
const rawJson = await fs.readFile(resolvedKeyFile, "utf8");
const credential = JSON.parse(rawJson);

const auth = new GoogleAuth({
  keyFile: resolvedKeyFile,
  scopes: args.scopes,
});

const client = await auth.getClient();
const tokenValue = await client.getAccessToken();
const accessToken = normalizeAccessToken(tokenValue);

if (!accessToken) {
  throw new Error("GoogleAuth did not return an access token.");
}

const expiryDate =
  typeof client.credentials?.expiry_date === "number"
    ? new Date(client.credentials.expiry_date).toISOString()
    : null;

if (args.tokenOnly) {
  console.log(accessToken);
  process.exit(0);
}

console.log(
  JSON.stringify(
    {
      service_account_email: credential.client_email || null,
      access_token: accessToken,
      expiry_iso: expiryDate,
      scopes: args.scopes,
      library: "google-auth-library",
      key_file: resolvedKeyFile,
    },
    null,
    2,
  ),
);
