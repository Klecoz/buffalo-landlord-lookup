#!/usr/bin/env bash
# Deploy buffalo-landlord-lookup to Cloudflare Pages + R2.
#
# Site (HTML/CSS/JS) -> Cloudflare Pages
# Data (web/data/, ~384 MB, 67k files) -> Cloudflare R2 public bucket
#
# Prerequisites (one-time):
#   1. brew install node rclone
#   2. npx wrangler login
#   3. Create R2 bucket and enable public access:
#        npx wrangler r2 bucket create buffalo-landlord-data
#        # then in the Cloudflare dashboard: R2 -> bucket -> Settings ->
#        # "Public access" -> Allow Access via the r2.dev subdomain.
#        # Copy the pub-*.r2.dev URL.
#   4. Configure rclone for R2 (S3-compatible). Run `rclone config`:
#        n) new remote
#        name> r2
#        Storage> s3
#        provider> Cloudflare
#        access_key_id> <R2 API token Access Key>
#        secret_access_key> <R2 API token Secret>
#        endpoint> https://<account-id>.r2.cloudflarestorage.com
#        (R2 API tokens are created in dashboard: R2 -> Manage R2 API Tokens.)
#   5. Copy web/config.js.example to web/config.js and paste your pub-*.r2.dev URL.
#
# Usage: ./deploy.sh [--data-only|--site-only]

set -euo pipefail

cd "$(dirname "$0")"

R2_BUCKET="${R2_BUCKET:-buffalo-landlord-data}"
RCLONE_REMOTE="${RCLONE_REMOTE:-r2}"
PAGES_PROJECT="${PAGES_PROJECT:-buffalo-landlord-lookup}"

MODE="${1:-all}"

deploy_data() {
  echo "==> Syncing web/data/ to R2 bucket: $R2_BUCKET"
  if ! command -v rclone >/dev/null; then
    echo "rclone not installed. brew install rclone" >&2; exit 1
  fi
  # --transfers: parallel uploads. 67k small files benefit from high concurrency.
  # --checkers: parallel hash compares for incremental syncs.
  # --fast-list: fewer ListObjects calls on subsequent runs.
  rclone sync web/data "$RCLONE_REMOTE:$R2_BUCKET" \
    --transfers 32 \
    --checkers 32 \
    --fast-list \
    --progress
}

deploy_site() {
  echo "==> Deploying site to Cloudflare Pages: $PAGES_PROJECT"
  if [[ ! -f web/config.js ]]; then
    echo "web/config.js missing. Copy web/config.js.example -> web/config.js and set DATA_BASE." >&2
    exit 1
  fi
  # Stage site files without web/data/, node_modules/, or test scaffolding
  # so we stay under Pages' 20k file limit and don't ship dev-only assets.
  STAGE="$(mktemp -d)"
  trap 'rm -rf "$STAGE"' EXIT
  rsync -a \
    --exclude 'data' \
    --exclude 'node_modules' \
    --exclude 'tests' \
    --exclude 'coverage' \
    --exclude 'package.json' \
    --exclude 'package-lock.json' \
    --exclude 'vitest.config.js' \
    --exclude 'vitest.config.js.timestamp-*.mjs' \
    web/ "$STAGE/"
  npx wrangler pages deploy "$STAGE" --project-name "$PAGES_PROJECT" --commit-dirty=true
}

case "$MODE" in
  --data-only) deploy_data ;;
  --site-only) deploy_site ;;
  all|"")      deploy_data; deploy_site ;;
  *) echo "Usage: $0 [--data-only|--site-only]" >&2; exit 1 ;;
esac

echo "==> Done."
