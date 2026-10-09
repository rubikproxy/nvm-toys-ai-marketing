# NVM Toys AI Marketing Workspace

A separate, local-first AI marketing workspace for NVM Toys. All production Python is in `app.py`; the existing Next.js site and Cloudflare D1 store are not modified. The workspace stores its own operational metadata in `data\operations.json`, an atomic-write JSON file. This local file is **not** a replacement for the store database.

## Current state and honest integration status

The local dashboard, authenticated drafts, campaign proposals, approvals, product imports, privacy-conscious event counts, exports, backups, audit history, and Gemini budget gate are implemented. The **Sell products** planner reviews every imported product, reports missing catalog facts and measured first-party interest events, and can create a safe local draft for each product not explicitly marked inactive. Unknown active status and unverified facts are flagged for review. Channel templates are provided for Instagram, Facebook, Reels, YouTube Shorts, email, and SEO. Batch runs are idempotent, make no Gemini calls, and never publish/send or edit store data. The AI content studio accepts a channel, tone, language, campaign angle, objective, and optional creative direction, then prompts for a channel-appropriate draft through the centrally metered Gemini client. Importing a product file does not make those facts verified: they remain labeled as manual/unverified. Product-specific Gemini generation is blocked until a product snapshot is marked verified by a future authorized source adapter.

The prior unauthenticated probe of `https://nvmtoys.com/api/mcp` returned HTTP 401. No MCP credential or confirmed protocol version is configured. The app therefore does not contact MCP during startup and does not claim store data is connected. The optional manual discovery action is disabled until both the authentication token and a protocol version have been verified. It performs initialization and `tools/list` only; it does not call business tools.

Cloudflare D1 is remote. This app does not open it as SQLite, issue D1 queries, change its schema, or write store data. Account/database IDs and a restricted API token are not available, and the existing schema/API permissions have not been verified. D1 remains `UNCONFIGURED`/`UNVERIFIED`.

Email, WhatsApp, social publishing, analytics/ad platforms, customer messaging, and ad spend are not connected. External publishing and ad spending are disabled. Approval records change local draft status only; they never publish, send, alter a price, or spend money.

## Windows setup

Use Python 3.12 or newer. From the workspace root in PowerShell:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
Copy-Item .env.example .env
```

Start with safe defaults:

```powershell
python .\app.py
```

Open <http://127.0.0.1:8000>. The application binds only to loopback and refuses non-loopback `APP_HOST` values. On first run, it creates `data\bootstrap.token`; use that one-time credential on the dashboard, then choose a password of at least 12 characters. The token is not printed or logged. Keep the `data` directory private and delete the bootstrap token after setup (the app removes it when the password is set). Alternatively, before the first launch set `APP_ADMIN_PASSWORD` in the ignored `.env` file; use a unique 12+ character value.

Stop with **Ctrl+C** in the PowerShell window. Run checks with:

```powershell
python -m pytest -q
ruff check app.py tests
```

If script activation is blocked, use the virtual environment interpreter directly:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe .\app.py
```

No Docker, external automation service, or public server is required.

## Gemini and ₹500 protection

Gemini calls are disabled by default (`AI_ENABLED=false`, `DEMO_MODE=true`). To enable a cloud call:

1. Obtain a Gemini API key from Google's official console and store it only in `.env` as `GEMINI_API_KEY`.
2. Set a currently supported `GEMINI_MODEL`.
3. Verify model pricing at <https://ai.google.dev/gemini-api/docs/pricing>; do not copy old sample prices.
4. Configure `GEMINI_INPUT_USD_PER_MILLION`, `GEMINI_OUTPUT_USD_PER_MILLION`, and `USD_TO_INR_RATE`, or use `GEMINI_PRICING_JSON` for per-model rates.
5. Set `AI_ENABLED=true` and `DEMO_MODE=false` only after reviewing those settings and Google's provider-side billing controls.

The application clamps `GEMINI_MAX_BUDGET_INR` to at most ₹500, defaults to a ₹10 daily limit, and withholds a 10% reserve by default. Before a request it estimates prompt tokens conservatively from UTF-8 bytes, reserves the maximum configured output tokens, and rejects unknown pricing, missing keys/models, demo mode, disabled AI, daily-limit overflow, or total-budget/reserve overflow. Requests are serialized in the local process. Failed/incomplete requests keep their conservative reservation. Repeated successful prompts can use the local response cache. The dashboard reports estimated spend separately from provider-reported token counts.

This is application-side protection, not a guarantee of Google's invoice or currency conversion. Also set any spending caps/alerts offered by Google. The emergency-stop button blocks later calls. No AI request runs on page load or on a background schedule.

## Store data, MCP, and D1

Product CSV/JSON import is available from the dashboard or `POST /api/products/import`. Imports are labeled `manual_import`, carry an import timestamp, and remain `verified=false`. Sales, revenue, and inventory are never shown as connected merely because a file was imported.

Before MCP discovery, independently confirm the endpoint's authentication scheme and supported MCP protocol version. Then set `NVM_TOYS_MCP_TOKEN` and `NVM_TOYS_MCP_PROTOCOL_VERSION` in `.env`, restart locally, sign in, and use **Integrations → Attempt verified MCP tool discovery**. The client sends requests only to the fixed HTTPS NVM Toys host and follows no redirects. Tool schemas are displayed; there is no unrestricted tool invocation. The current endpoint has not been successfully authenticated or tested.

Do not add a Cloudflare credential until you have verified account, database ID, API route, required permissions, and current D1 schema through official documentation/account configuration. This build intentionally does not issue SQL or call a guessed D1 route. Never place store tokens in browser JavaScript.

## Dashboard and local APIs

Dashboard areas include Overview, Products, **Sell products**, AI content studio, Campaigns, Approvals, privacy-conscious Segments, Analytics, Workflows, Integrations, Gemini budget, Settings, and Audit log. The catalog planner reports verified status and recorded product-interest events where available; those events are not orders or revenue, and no sales forecast is made. Its batch action creates deterministic, editable per-product drafts for products not explicitly marked inactive, flags unknown status and unverified product snapshots, and safely skips explicitly inactive items. Repeating the same batch does not create duplicates. Draft creation is not a sale: the app is not connected to checkout, order management, live store changes, publishing, or message delivery. Review product facts and platform rules before any manual use. The content studio guides channel, tone (playful, warm, energetic, educational, premium), language (English, Hindi, Hinglish), and creative angle. Drafts are saved locally with the generation brief and AI budget accounting; generated claims still require human review and approval. Use `/api/health` for a minimal local health check. The dashboard APIs require administrator sign-in; sign-in uses a salted PBKDF2 password hash and a short-lived HTTP-only SameSite cookie. Same-origin checks apply to cookie-authenticated writes. Login attempts are rate-limited in process. The API docs are available only in development at `/docs`.

Content and campaign records are drafts. Campaign discount arithmetic is calculated locally from the imported price snapshot and remains a recommendation, not an active coupon or store-price change. The approval center supports approval, rejection, cancellation, and seven-day expiration; approval is not execution authorization for a channel that is not implemented.

The local workflow list is disabled by default. It has manual-only local review tasks; there is no continuous polling or background Gemini generation. Analytics distinguish locally recorded event counts from unavailable sales, revenue, attribution, and ad metrics.

## Privacy and security

- The app binds to loopback, has no CORS allowlist, and rejects non-local Host headers. Do not reverse-proxy or expose it publicly.
- Keep `.env`, `data`, `bootstrap.token`, exports, and backups private. `.gitignore` excludes these paths.
- Never enter customer names, phone numbers, emails, payment details, or other sensitive data into Gemini notes. The app does not collect customer identifiers. Consent event records are aggregate/minimal and are not an audience export.
- Product imports are size-limited and product URLs must use the NVM Toys HTTPS domain. Treat imported descriptions as untrusted content.
- Use only first-party authorized data with appropriate privacy disclosures and consent. No customer messages, bulk sending, publishing, store updates, or advertising actions are implemented.
- There is no public inbound website event collector in this build. Do not add tracking to the Next.js site without separate review and explicit approval.
- `data\operations.json` uses atomic replace and stops on detected corruption instead of overwriting the damaged file. Backups include sensitive local operational data and must be protected.

## Backup and restore

While signed in, use **Audit log → Create local backup**, which writes a timestamped snapshot under `data\backups`. Or stop the app and copy the entire `data` folder to a protected location:

```powershell
Copy-Item .\data "$env:USERPROFILE\Documents\nvm-marketing-backup" -Recurse
```

To restore, stop the app, preserve the current `data` folder under a different name, then copy the chosen backup to `data\operations.json` or restore the protected folder. Never restore a data file from an untrusted source. Resetting this app means stopping it and renaming/removing only its local `data` directory; this does not touch the website or D1.

## Troubleshooting

- **Can't sign in on first run:** open `data\bootstrap.token` locally and paste its contents once. Do not share it. After password setup, use the password you selected.
- **Gemini disabled/unavailable:** confirm `AI_ENABLED`, `DEMO_MODE`, API key, model, verified pricing, and the `/api/budget` warning. Restart after `.env` changes.
- **Product AI generation blocked:** imported data is intentionally unverified. A verified authenticated read-only store adapter is not configured yet.
- **MCP returns 401:** the endpoint credentials/auth scheme are unverified; do not try guessed credentials or tools.
- **Corrupted local JSON:** stop the app and restore a known-good backup. The app will not silently reset it.
- **Port already in use:** set `APP_PORT` to an available local port in `.env`.

## Implemented limits

This rebuild is the local application foundation, not a verified live store integration. It does not yet implement a usable authenticated NVM Toys read adapter, D1 query adapter, customer CRM/profile storage, social/email/WhatsApp delivery, ad APIs, external notifications, campaign performance attribution, scheduled task runner, website event integration, or external execution/retry queue. Missing credentials, schemas, and account permissions prevent honest activation of those features. No live provider calls or external messages are part of automated tests.
