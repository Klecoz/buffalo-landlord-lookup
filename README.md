# Buffalo Landlord Lookup

Browser tool: enter a Buffalo, NY address → see who owns it, code-violation history, recent 311 complaints, and the owner's full property portfolio across LLCs.

A personal civic-data toy. No backend, no DB, no auth. A Python pipeline scrapes public data, joins it to parcels, and emits static JSON the frontend reads directly.

## Quickstart

```bash
# 1. Install pipeline deps
cd pipeline && pip install -r requirements.txt

# 2. Run the pipeline (fetches everything; takes a few minutes)
python run.py

# 3. Serve the frontend
cd ../web && python -m http.server 8000
# open http://localhost:8000
```

If `web/config.js` exists it sets `DATA_BASE` to the deployed R2 bucket, so a
local server reads **production** data with your local HTML and JS. Move it
aside to exercise the freshly built `web/data/`. Browsers cache it aggressively;
serve on a new port after moving it.

## Data sources

All public:

- **data.buffalony.gov** (Socrata API): code violations, 311 service requests, demolition permits
- **NYS GIS Clearinghouse** (ArcGIS REST FeatureServer): tax parcels w/ owner-of-record, filtered to `MUNI_NAME='Buffalo'`
- Map tiles: OpenStreetMap via MapLibre GL JS

The pipeline writes a `meta.json` with row counts and refresh date. The footer of every page shows it.

## Limitations (read these)

- **Owner aggregation is string-matching only** for the per-owner view. "ACME PROPERTIES LLC" and "Acme Properties, L.L.C." merge; "John Smith" and "John A Smith" don't. The **Operators** leaderboard groups owners sharing a mailing address, surfacing many cross-LLC portfolios — but shared service-address pools (registered agents, CPA firms) are suppressed heuristically and may miss some connections. Bulk LLC unmasking via NYS DOS isn't available (the 2026 LLC Transparency Act exempts domestic LLCs).
- **The 311 dataset (`whkc-e5vr`) stopped updating in May 2024.** The 12-month complaint window is anchored to the dataset's max date, not today. Code violations and parcels are current.
- **The tool never says "X is a slumlord."** It shows facts; readers form a view.
- **Not legal advice.** Research tool only.

## Run tests

```bash
# Pipeline (Python)
cd pipeline && pytest

# Frontend (Vitest / jsdom)
cd web && npm install && npm test
```

## Deploy

Hosted on Cloudflare Pages (site) + Cloudflare R2 (data). See [DEPLOY.md](DEPLOY.md) for one-time setup and the manual refresh workflow.
