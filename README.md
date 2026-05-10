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

## Data sources

All public:

- **data.buffalony.gov** (Socrata API): code violations, 311 service requests, demolition permits
- **NYS GIS Clearinghouse** (ArcGIS REST FeatureServer): tax parcels w/ owner-of-record, filtered to `COUNTY_NAME='Erie'`
- Map tiles: OpenStreetMap via MapLibre GL JS

The pipeline writes a `meta.json` with row counts and refresh date. The footer of every page shows it.

## Limitations (read these)

- **Owner aggregation is string-matching only.** "ACME PROPERTIES LLC" and "Acme Properties, L.L.C." merge. "John Smith" and "John A Smith" don't. Properties owned by the same person under shell LLCs with distinct names will appear separately. Bulk LLC unmasking via NYS DOS isn't available (the 2026 LLC Transparency Act exempts domestic LLCs).
- **The 311 dataset (`whkc-e5vr`) stopped updating in May 2024.** The 12-month complaint window is anchored to the dataset's max date, not today. Code violations and parcels are current.
- **The tool never says "X is a slumlord."** It shows facts; readers form a view. The page title is a question.
- **Not legal advice.** Research tool only.

## Run tests

```bash
cd pipeline && pytest
```

## Deploy

Hosted on Cloudflare Pages (site) + Cloudflare R2 (data). See [DEPLOY.md](DEPLOY.md) for one-time setup and the manual refresh workflow.
