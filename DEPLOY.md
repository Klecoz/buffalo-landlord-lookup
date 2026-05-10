# Deploy

Production hosting: **Cloudflare Pages** (site) + **Cloudflare R2** (data files).

Why split: the `web/data/` directory is ~384 MB across ~67k JSON files. Pages caps at 25 MiB/file and 20k files/deploy, so the data goes to R2 and the site fetches it from a public R2 URL.

## One-time setup

### 1. Install tools

```bash
brew install node rclone
```

### 2. Log into Cloudflare

```bash
npx wrangler login
```

### 3. Create the R2 bucket

```bash
npx wrangler r2 bucket create buffalo-landlord-data
```

### 4. Enable public access (browser)

1. https://dash.cloudflare.com → **R2** → `buffalo-landlord-data` → **Settings**
2. Under **Public access**, enable the **r2.dev subdomain**
3. Copy the URL — looks like `https://pub-abc123XXXXXX.r2.dev`

### 5. Create an R2 API token (browser)

1. R2 → **Manage R2 API Tokens** → **Create API Token**
2. Permission: **Object Read & Write**, scoped to bucket `buffalo-landlord-data`
3. Save:
   - Access Key ID
   - Secret Access Key
   - The account-ID endpoint URL (`https://<account-id>.r2.cloudflarestorage.com`)

### 6. Configure rclone

```bash
rclone config
```

Walk through:

| Prompt | Answer |
|---|---|
| `n/s/q` | `n` (new remote) |
| `name` | `r2` |
| `Storage` | `s3` |
| `provider` | `Cloudflare` |
| `env_auth` | `false` |
| `access_key_id` | (from step 5) |
| `secret_access_key` | (from step 5) |
| `region` | `auto` (or just press enter) |
| `endpoint` | `https://<account-id>.r2.cloudflarestorage.com` |

Accept defaults for everything else. Save.

### 7. Set the production data URL

```bash
cp web/config.js.example web/config.js
# edit web/config.js — paste the pub-*.r2.dev URL from step 4
```

`web/config.js` is gitignored. Local dev (`python -m http.server`) doesn't need it; it falls back to relative `data/` paths.

## Deploy

```bash
./deploy.sh              # data + site (full deploy)
./deploy.sh --data-only  # push fresh JSON to R2 after running the pipeline
./deploy.sh --site-only  # push HTML/JS/CSS changes only
```

First data sync takes 10–20 min for all 67k files. Subsequent `--data-only` runs are incremental (rclone only uploads changed files). Site deploys are ~30 sec.

## Manual refresh workflow

When data goes stale and you want to publish fresh:

```bash
cd pipeline && python run.py        # regenerate web/data/
cd .. && ./deploy.sh --data-only    # sync to R2
```

The site URL doesn't change; users just see fresher numbers and a newer "generated at" date in the footer.

## Files involved

- `deploy.sh` — the deploy script
- `web/config.js` — local-only, holds `window.DATA_BASE = "https://pub-*.r2.dev"`
- `web/config.js.example` — checked-in template
- `web/app.js:11` — reads `window.DATA_BASE`, falls back to `"data"`
- `.gitignore` — excludes `web/data/` and `web/config.js`

## Overrides

The deploy script reads these env vars if you ever rename things:

```bash
R2_BUCKET=buffalo-landlord-data
RCLONE_REMOTE=r2
PAGES_PROJECT=buffalo-landlord-lookup
```

## Troubleshooting

- **`rclone: command not found`** → `brew install rclone`
- **`web/config.js missing`** → did step 7
- **Browser console: CORS error fetching from R2** → r2.dev subdomain has permissive GET CORS by default; if you switched to a custom domain, add a CORS policy on the bucket allowing your Pages origin
- **Pages deploy: "too many files"** → `web/data/` leaked into the deploy stage; the script uses `rsync --exclude 'data'`, so check that line
- **Stale data after deploy** → R2 + r2.dev caches aggressively. Either wait a few minutes, hard-refresh, or invalidate via dashboard
