"""NYS DOS Active Corporations enrichment.

Detects 'service-address pools' — operator clusters whose shared mailing
address is actually a registered-agent or filing-service address that
forwards thousands of unrelated NY entities. The address-count is
counter-evidence to the 'real shared owner' hypothesis used elsewhere
in the cluster construction.

Source: data.ny.gov dataset n9v6-gdp6 ('Active Corporations: Beginning
1800'). Free Socrata API, monthly refresh, ~4.2M active entities. We
fetch the dos_process_address_* fields (the address NYS DOS forwards
lawsuits to — the field that registered-agent services share) and
build an index of normalized-address -> distinct-entity-count.

The cached derived index lives in pipeline/derived/ and is refreshed
when older than REFRESH_DAYS, since DOS publishes monthly.
"""

from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Optional

import requests

from normalize import normalize_mail_address


HERE = Path(__file__).resolve().parent
DERIVED = HERE / "derived"
DERIVED.mkdir(exist_ok=True)

INDEX_PATH = DERIVED / "nys_dos_address_index.json"

NYS_DOS_HOST = "https://data.ny.gov"
DATASET_ID = "n9v6-gdp6"
PAGE_SIZE = 50_000
REFRESH_DAYS = 30


def _atomic_write_json(path: Path, data) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w") as f:
        json.dump(data, f, separators=(",", ":"))
    tmp.replace(path)


def _normalize_dos_record(rec: dict) -> str:
    """Map a DOS row to the same '|'-joined normalized address key the rest
    of the pipeline uses for cluster mailing addresses.

    Uses dos_process_address_* (NYS service-of-process address). Empty or
    unparseable rows return ''.
    """
    return normalize_mail_address(
        rec.get("dos_process_address_1"),
        rec.get("dos_process_city"),
        rec.get("dos_process_state"),
        rec.get("dos_process_zip"),
    )


def build_index_from_records(records: Iterable[dict]) -> dict[str, int]:
    """Stream over DOS records, count distinct dos_id per normalized
    process-address key. Pure function for testability."""
    seen_per_addr: dict[str, set[str]] = {}
    for rec in records:
        key = _normalize_dos_record(rec)
        if not key:
            continue
        dos_id = rec.get("dos_id")
        if not dos_id:
            continue
        seen_per_addr.setdefault(key, set()).add(str(dos_id))
    return {key: len(ids) for key, ids in seen_per_addr.items()}


def _fetch_dataset_max_date(app_token: Optional[str]) -> Optional[str]:
    """Latest filing date across the dataset — used as source_max_date in
    meta.json. Best-effort; returns None on any error so a transient
    Socrata blip doesn't fail the pipeline."""
    url = f"{NYS_DOS_HOST}/resource/{DATASET_ID}.json"
    params = {
        "$select": "max(initial_dos_filing_date) as max_date",
        "$limit": 1,
    }
    headers = {"X-App-Token": app_token} if app_token else {}
    try:
        r = requests.get(url, params=params, headers=headers, timeout=30)
        r.raise_for_status()
        rows = r.json()
        if rows:
            raw = rows[0].get("max_date") or ""
            return raw[:10] or None
    except Exception as e:
        print(f"  warning: could not fetch DOS max date ({e})", file=sys.stderr)
    return None


def _paginate_dataset(app_token: Optional[str]) -> Iterable[dict]:
    """Yield each row from the active-corporations dataset.

    Streams page-by-page so callers can build derived state without
    holding all 4.2M rows in memory.
    """
    url = f"{NYS_DOS_HOST}/resource/{DATASET_ID}.json"
    headers = {"X-App-Token": app_token} if app_token else {}
    fields = (
        "dos_id,current_entity_name,"
        "dos_process_address_1,dos_process_address_2,"
        "dos_process_city,dos_process_state,dos_process_zip"
    )
    offset = 0
    total = 0
    while True:
        # `$order` is required for correct paging — see the note in
        # fetch.py::_socrata. Unordered, this pull drops entities and
        # undercounts the registered-agent pools the index exists to find.
        params = {
            "$limit": PAGE_SIZE,
            "$offset": offset,
            "$select": fields,
            "$order": ":id",
        }
        r = requests.get(url, params=params, headers=headers, timeout=300)
        r.raise_for_status()
        page = r.json()
        if not page:
            break
        yield from page
        total += len(page)
        print(f"  nys dos: {total:,} rows", file=sys.stderr)
        if len(page) < PAGE_SIZE:
            break
        offset += PAGE_SIZE


def _index_is_fresh(path: Path, max_age_days: int) -> bool:
    if not path.exists():
        return False
    age_days = (time.time() - path.stat().st_mtime) / 86400
    return age_days < max_age_days


def fetch_and_build_index(
    refresh_days: int = REFRESH_DAYS,
    force_refresh: bool = False,
) -> tuple[dict[str, int], Optional[str]]:
    """Return (address_count_index, source_max_date).

    Caches the derived index to disk. If the cached index is younger than
    refresh_days, returns it without hitting the network — DOS publishes
    monthly, so daily pipeline runs don't need to re-fetch.
    """
    if not force_refresh and _index_is_fresh(INDEX_PATH, refresh_days):
        # The cache is derived data. If it's unreadable — a write interrupted
        # by a full disk or a Ctrl-C, an older payload shape — rebuilding it
        # is cheap and correct; aborting the pipeline run is neither.
        try:
            with INDEX_PATH.open() as f:
                payload = json.load(f)
            index = payload["index"]
        except (OSError, ValueError, KeyError) as e:
            print(
                f"  warning: cached NYS DOS index at {INDEX_PATH} is unusable "
                f"({e}); re-fetching",
                file=sys.stderr,
            )
        else:
            print(
                f"Using cached NYS DOS address index "
                f"({payload.get('address_count', 0):,} addresses, "
                f"max_date={payload.get('source_max_date')})",
                file=sys.stderr,
            )
            return index, payload.get("source_max_date")

    print(f"Fetching NYS DOS active corporations ({DATASET_ID})...", file=sys.stderr)
    app_token = os.environ.get("NYS_OPEN_DATA_APP_TOKEN") or None
    max_date = _fetch_dataset_max_date(app_token)
    index = build_index_from_records(_paginate_dataset(app_token))

    payload = {
        "source": "nys_dos_active_corporations",
        "source_dataset_id": DATASET_ID,
        "source_max_date": max_date,
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "address_count": len(index),
        "index": index,
    }
    _atomic_write_json(INDEX_PATH, payload)
    print(
        f"  built address-count index: {len(index):,} distinct addresses",
        file=sys.stderr,
    )
    return index, max_date


def histogram(
    clusters: Iterable[dict],
    bands: tuple[int, ...] = (0, 1, 10, 50, 100, 500, 1000, 10000),
) -> list[tuple[str, int]]:
    """Bucket clusters' nys_dos_entity_count into human-readable bands.

    Used for stderr sanity-output during pipeline runs so we can eyeball
    the distribution before tuning REGISTERED_AGENT_THRESHOLD.
    """
    buckets = [0] * (len(bands) + 1)
    edges = list(bands) + [float("inf")]
    for c in clusters:
        count = (
            (c.get("audit") or {})
            .get("service_address", {})
            .get("nys_dos_entity_count", 0)
        )
        for i, edge in enumerate(edges):
            if count <= edge:
                buckets[i] += 1
                break
    labels: list[tuple[str, int]] = []
    prev = -1
    for i, edge in enumerate(edges):
        if edge == float("inf"):
            labels.append((f">{prev}", buckets[i]))
        else:
            labels.append((f"{prev + 1}–{int(edge)}" if prev + 1 != edge else f"={edge}", buckets[i]))
            prev = int(edge)
    return labels


if __name__ == "__main__":
    fetch_and_build_index(force_refresh="--force" in sys.argv)
