// Buffalo Landlord Lookup — vanilla-JS frontend
// Loads static JSON artifacts emitted by ../pipeline and renders three views:
//   - Landing: full Buffalo map, parcels colored by concern score
//   - Dossier: clicked parcel detail
//   - Portfolio: every parcel an owner has

const BUFFALO = { lng: -78.8784, lat: 42.8864, zoom: 13.5 };

// Where the JSON artifacts live. Local dev: "data". Prod: set window.DATA_BASE
// to your R2 public URL (e.g. "https://pub-xxx.r2.dev") in index.html before app.js loads.
const DATA_BASE = (typeof window !== "undefined" && window.DATA_BASE) || "data";

const state = {
  map: null,
  addressIndex: [],   // [{addr, id}, ...]
  dossiers: null,     // lazy-loaded { parcel_id: {violations, complaints} }
  meta: null,
  topOwners: null,
  topOperators: null,
  selectedId: null,
  activeBoard: "by_open_violations",
  activeBoardKind: "operators",  // "operators" | "owners" — sticky between renders
  mapFilter: null,               // { kind: "owner"|"operator", slug, label, count } | null
};

let _selectParcelToken = 0;

// ---------- helpers ----------
const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => [...document.querySelectorAll(sel)];

function fmtDate(s) {
  if (!s) return "";
  return s.slice(0, 10);
}
function escapeHtml(s) {
  return String(s ?? "").replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c])
  );
}
function cleanOwnerName(s) {
  return String(s ?? "").replace(/[;,\s]+$/u, "").trim();
}
function fmtMoney(n) {
  if (n == null || n === "") return "—";
  n = Number(n);
  if (isNaN(n)) return "—";
  if (n === 0) return "$0";
  if (n >= 1_000_000_000) return `$${(n / 1_000_000_000).toFixed(1)}B`;
  if (n >= 1_000_000)     return `$${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000)         return `$${Math.round(n / 1_000)}K`;
  return `$${n}`;
}
// Freshness pill: a small inline label rendered next to a panel header
// that tells the reader how current the underlying source is.
//
// kind: "violations" | "311" | "parcels"
// Returns an HTML string; pass through directly into a template literal.
function freshnessPill(kind) {
  const meta = state.meta || {};
  const generated = meta.generated_at || "";
  const maxDateByKind = {
    violations: meta.code_violations_max_date || "",
    "311": meta.complaints_311_max_date || "",
    parcels: meta.generated_at || "",
  };
  const labelByKind = {
    violations: "Code violations",
    "311": "311 complaints",
    parcels: "Parcels",
  };
  const max = maxDateByKind[kind] || "";
  const label = labelByKind[kind] || kind;
  if (!max && !generated) return "";

  const ageDays = (() => {
    if (!max) return Infinity;
    const ms = Date.now() - new Date(max).getTime();
    return Math.floor(ms / 86400000);
  })();

  // Special-case 311 freeze: the dataset stopped updating in 2024-05.
  // If the max date precedes the run by > 180 days, treat it as known-frozen.
  if (kind === "311" && ageDays > 180) {
    return `<span class="freshness-pill stale" title="Buffalo's 311 dataset (whkc-e5vr) stopped updating May 2024. The 12-month window ends at the dataset's max date, not today.">${label}: dataset frozen since ${max.slice(0, 7)}</span>`;
  }

  let cls = "fresh";
  if (ageDays > 180) cls = "stale";
  else if (ageDays > 30) cls = "aging";

  const dateLabel = max ? max.slice(0, 10) : generated.slice(0, 10);
  return `<span class="freshness-pill ${cls}">${label}: through ${dateLabel}</span>`;
}

function _copyLinkBtnHtml() {
  return `<button class="copy-link-btn" onclick="window.copyCurrentUrl(this)" title="Copy a shareable link to this view">Copy link</button>`;
}

function _downloadCsvBtnHtml(scope) {
  return `<button class="csv-btn" onclick="window.downloadPortfolioCsv('${escapeHtml(scope)}', this)" title="Download portfolio as CSV">Download CSV</button>`;
}

function _panelHeadActionsHtml(scope) {
  const copyBtn = _copyLinkBtnHtml();
  const csvBtn = scope ? _downloadCsvBtnHtml(scope) : "";
  return `<div class="panel-head-actions">${copyBtn}${csvBtn}</div>`;
}

function _violationTypesHtml(types) {
  if (!Array.isArray(types) || types.length === 0) return "";
  const max = types[0].count || 1;
  const rows = types.map(t => {
    const pct = Math.max(4, Math.round((t.count / max) * 100));
    return `
      <li>
        <span class="vt-label">${escapeHtml(t.code_section)}</span>
        <span class="vt-bar"><span class="vt-bar-fill" style="width:${pct}%"></span></span>
        <span class="vt-count">${t.count}</span>
      </li>`;
  }).join("");
  return `
    <h3>Top violation types</h3>
    <ul class="violation-types">${rows}</ul>`;
}

window.openAuditDisclosure = function () {
  const d = document.querySelector("#panel .audit-details");
  if (!d) return;
  d.open = true;
  d.scrollIntoView({ behavior: "smooth", block: "start" });
};

// CSV export: builds an RFC-4180-quoted blob from the cached portfolio
// (state.lastPortfolio) or operator (state.lastOperator) and triggers a
// download. No external dependencies.
function _csvEscape(value) {
  if (value === null || value === undefined) return "";
  const s = String(value);
  return /[",\r\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
}

function buildPortfolioCsv(scope) {
  const data = scope === "operator" ? state.lastOperator : state.lastPortfolio;
  if (!data) return null;
  const props = data.properties || [];
  const headers = [
    "address", "open_violations", "total_violations",
    "complaints_311_12mo", "value", "demolished",
    "lat", "lng", "parcel_id",
  ];
  const rows = props.map(p => [
    p.addr,
    p.violations_open ?? "",
    p.violations_total ?? "",
    p.complaints_311_12mo ?? "",
    p.value ?? "",
    p.demolished ? "true" : "false",
    p.lat ?? "",
    p.lng ?? "",
    p.id ?? "",
  ]);
  const lines = [headers, ...rows].map(r => r.map(_csvEscape).join(","));
  return lines.join("\r\n") + "\r\n";
}

function _csvFilename(scope) {
  const slug = scope === "operator"
    ? (state.lastOperator?.operator_slug || "operator")
    : (state.lastPortfolio?._slug || "owner");
  return `${slug}-${scope}.csv`;
}

window.downloadPortfolioCsv = function (scope, btn) {
  const csv = buildPortfolioCsv(scope);
  if (!csv) return;
  const blob = new Blob([csv], { type: "text/csv;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = _csvFilename(scope);
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  setTimeout(() => URL.revokeObjectURL(url), 0);
  if (btn) {
    const orig = btn.textContent;
    btn.textContent = "Downloaded";
    btn.classList.add("downloaded");
    setTimeout(() => {
      btn.textContent = orig;
      btn.classList.remove("downloaded");
    }, 1500);
  }
};

window.copyCurrentUrl = function (btn) {
  const url = location.href;
  const flash = (text, klass) => {
    const orig = btn.textContent;
    btn.textContent = text;
    btn.classList.add(klass);
    setTimeout(() => {
      btn.textContent = orig;
      btn.classList.remove(klass);
    }, 1500);
  };
  if (navigator.clipboard && navigator.clipboard.writeText) {
    navigator.clipboard.writeText(url)
      .then(() => flash("Copied!", "copied"))
      .catch(() => flash("Press ⌘C", "copied"));
  } else {
    flash("Press ⌘C", "copied");
  }
};

function showPanel(html) {
  $("#panel-content").innerHTML = html;
  const panel = $("#panel");
  panel.classList.remove("hidden");
  panel.scrollTop = 0;
  $("#reopen-panel").classList.add("hidden");
  // On phones, ensure the sheet has a snap state. Default to half when
  // navigating into a route; otherwise leave the user's chosen state alone.
  if (window.matchMedia("(max-width: 480px)").matches) {
    if (!panel.classList.contains("sheet-peek") &&
        !panel.classList.contains("sheet-half") &&
        !panel.classList.contains("sheet-full")) {
      panel.classList.add("sheet-half");
    }
    // First-time hint: bounce the sheet once so the drag affordance is obvious.
    try {
      if (!sessionStorage.getItem("sheetNudged")) {
        sessionStorage.setItem("sheetNudged", "1");
        panel.classList.add("nudge-once");
        panel.addEventListener("animationend", () => {
          panel.classList.remove("nudge-once");
        }, { once: true });
      }
    } catch {}
  }
  // Re-wire any "Highlight on map" buttons that were just rendered.
  $$("#panel .highlight-btn").forEach(btn => {
    btn.addEventListener("click", () => {
      window.toggleMapHighlight(btn.dataset.kind, btn.dataset.slug, btn.dataset.label);
    });
  });
}
function hidePanel() {
  // "Close" returns to leaderboards rather than hiding the panel entirely;
  // the small × on the leaderboard view fully hides it.
  state.selectedId = null;
  state.lastPortfolio = null;
  state.lastOperator = null;
  if (state.map && state.map.getLayer("parcels-selected")) {
    state.map.setFilter("parcels-selected", ["==", "id", ""]);
  }
  renderLeaderboards();
}
function fullyHidePanel() {
  $("#panel").classList.add("hidden");
  const reopenBtn = $("#reopen-panel");
  reopenBtn.innerHTML = "▴ Open";
  reopenBtn.classList.remove("hidden");
}

async function loadDossiers() {
  if (state.dossiers) return state.dossiers;
  try {
    const r = await fetch(`${DATA_BASE}/dossiers.json`);
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    state.dossiers = await r.json();
  } catch (e) {
    console.error("dossiers load failed", e);
    state.dossiers = {};
  }
  return state.dossiers;
}

// ---------- map ----------
function initMap() {
  // Carto Positron raster (no API key, light editorial basemap)
  const map = new maplibregl.Map({
    container: "map",
    style: {
      version: 8,
      sources: {
        carto: {
          type: "raster",
          tiles: [
            "https://a.basemaps.cartocdn.com/light_nolabels/{z}/{x}/{y}.png",
            "https://b.basemaps.cartocdn.com/light_nolabels/{z}/{x}/{y}.png",
            "https://c.basemaps.cartocdn.com/light_nolabels/{z}/{x}/{y}.png",
            "https://d.basemaps.cartocdn.com/light_nolabels/{z}/{x}/{y}.png",
          ],
          tileSize: 256,
          attribution:
            "© <a href='https://www.openstreetmap.org/copyright'>OpenStreetMap</a> contributors © <a href='https://carto.com/attributions'>CARTO</a>",
        },
      },
      layers: [{ id: "carto", type: "raster", source: "carto" }],
    },
    center: [BUFFALO.lng, BUFFALO.lat],
    zoom: BUFFALO.zoom,
  });
  map.addControl(new maplibregl.NavigationControl({ showCompass: false, showZoom: true }), "top-right");
  map.addControl(new maplibregl.GeolocateControl({ positionOptions: { enableHighAccuracy: true }, trackUserLocation: false, showAccuracyCircle: true }), "top-right");
  state.map = map;

  map.on("load", async () => {
    try {
      map.addSource("parcels", { type: "geojson", data: `${DATA_BASE}/properties.geojson` });

      // Build a circle layer at the centroid of each parcel polygon for fast render.
      // Color encodes concern_score; demolished parcels override.
      // Monochrome ramp + single signal red — matches CSS --s0..--s4 tokens.
      // The point: the map is mostly quiet gray; the eye lands on red where
      // concerns are severe.
      const colorExpr = [
        "case",
        ["==", ["get", "demolished"], true], "#6e1418",  // s4 deep red
        [">=", ["get", "concern_score"], 11], "#b9292d", // s3 signal red
        [">=", ["get", "concern_score"], 5],  "#88847d", // s2 mid gray
        [">=", ["get", "concern_score"], 1],  "#b8b4ab", // s1 light gray
        "#dcd9d2",                                       // s0 nearly-paper
      ];

      // Dim backdrop covers ALL parcels at constant opacity — toggled on
      // when the map filter is active.
      map.addLayer({
        id: "parcels-dim-fill",
        type: "fill",
        source: "parcels",
        paint: {
          "fill-color": "#fafaf7",   // paper wash dims unmatched parcels
          "fill-opacity": 0.7,
        },
        layout: { "visibility": "none" },
        filter: ["==", "$type", "Polygon"],
      });

      // Polygon fill (subtle, only at high zoom)
      map.addLayer({
        id: "parcels-fill",
        type: "fill",
        source: "parcels",
        paint: {
          "fill-color": colorExpr,
          "fill-opacity": [
            "interpolate", ["linear"], ["zoom"],
            11, 0,
            13, 0.35,
            15, 0.5,
            18, 0.6,
          ],
        },
        filter: ["==", "$type", "Polygon"],
      });

      // Outline at high zoom — ink hairline
      map.addLayer({
        id: "parcels-outline",
        type: "line",
        source: "parcels",
        paint: {
          "line-color": "#0c0c0c",
          "line-width": 0.5,
          "line-opacity": [
            "interpolate", ["linear"], ["zoom"],
            14, 0, 16, 0.4,
          ],
        },
        filter: ["==", "$type", "Polygon"],
      });

      // Highlighted-parcel overlay — drawn on top of parcels-fill / dim layer.
      // Solid accent color so matched parcels stand out at every zoom.
      map.addLayer({
        id: "parcels-highlight-fill",
        type: "fill",
        source: "parcels",
        paint: {
          "fill-color": "#b9292d",   // signal red — only chromatic event
          "fill-opacity": 0.9,
        },
        layout: { "visibility": "none" },
        filter: ["==", ["get", "owner_slug"], "__none__"],
      });
      // Centroid-circle markers backed by a separate Points source — needed
      // because a circle layer on a polygon source draws one circle per
      // VERTEX (4 per rectangular parcel), not one per parcel. We populate
      // this source on demand from in-memory data when the filter is applied.
      map.addSource("highlight-points", {
        type: "geojson",
        data: { type: "FeatureCollection", features: [] },
      });
      map.addLayer({
        id: "parcels-highlight-circle",
        type: "circle",
        source: "highlight-points",
        paint: {
          "circle-color": "#b9292d",   // signal red
          "circle-radius": [
            "interpolate", ["linear"], ["zoom"],
            10, 4,
            13, 6,
            15, 7,
            17, 0,   // fade out at high zoom — polygon fill takes over
          ],
          "circle-stroke-width": 1,
          "circle-stroke-color": "#0c0c0c",   // ink hairline
          "circle-stroke-opacity": [
            "interpolate", ["linear"], ["zoom"],
            13, 0.6,
            17, 0,
          ],
        },
        layout: { "visibility": "none" },
      });

      // Selected parcel highlight
      map.addLayer({
        id: "parcels-selected",
        type: "line",
        source: "parcels",
        paint: { "line-color": "#0c0c0c", "line-width": 1.5 },   // ink selected outline
        filter: ["==", "id", ""],
      });

      map.on("click", "parcels-fill", (e) => {
        const f = e.features?.[0];
        if (f) selectParcel(f.properties.id);
      });
      map.on("mouseenter", "parcels-fill", () => { map.getCanvas().style.cursor = "pointer"; });
      map.on("mouseleave", "parcels-fill", () => { map.getCanvas().style.cursor = ""; });
    } catch (err) {
      console.error("Map data load failed:", err);
      $("#meta-info").textContent = "Couldn't load parcel data — try refreshing.";
    }
  });
}

// ---------- views ----------
async function selectParcel(parcelId) {
  const myToken = ++_selectParcelToken;
  state.selectedId = parcelId;
  if (state.map.getLayer("parcels-selected")) {
    state.map.setFilter("parcels-selected", ["==", "id", parcelId]);
  }

  // Find the feature in the rendered source
  const feats = state.map.querySourceFeatures("parcels", {
    filter: ["==", "id", parcelId],
  });
  let props = feats?.[0]?.properties;

  // Fallback: scan address_index → properties.geojson is huge, but we already
  // rendered. If empty, querySourceFeatures may need higher zoom. Skip fallback;
  // if we can't find props, we just show a minimal panel.
  if (!props) {
    showPanel(`<p class="error">Couldn't load that parcel — try zooming in and clicking again.</p>`);
    return;
  }

  // Fly to it
  const geom = feats[0].geometry;
  if (geom?.type === "Polygon" && geom.coordinates?.[0]?.length) {
    const coords = geom.coordinates[0];
    const lng = coords.reduce((a, c) => a + c[0], 0) / coords.length;
    const lat = coords.reduce((a, c) => a + c[1], 0) / coords.length;
    state.map.flyTo({ center: [lng, lat], zoom: Math.max(state.map.getZoom(), 17) });
  }

  await loadDossiers();
  const dossier = state.dossiers[parcelId];
  renderDossier(props, dossier);
  location.hash = `#/parcel/${encodeURIComponent(parcelId)}`;
}

function renderDossier(props, dossier) {
  const byDateDesc = (a, b) => (b.date || "").localeCompare(a.date || "");
  const violations = (dossier?.violations || []).slice().sort(byDateDesc);
  const complaints = (dossier?.complaints || []).slice().sort(byDateDesc);
  const openCount = violations.filter(v => (v.status || "").toUpperCase() === "ACTIVE").length;
  const closedCount = violations.length - openCount;
  const owner = props.owner ? cleanOwnerName(props.owner) : "Owner not on record";
  const portfolioCta =
    props.portfolio_n > 1
      ? `<button class="cta" onclick="window.openPortfolio('${escapeHtml(props.owner_slug)}')">
           This owner has ${props.portfolio_n - 1} other propert${props.portfolio_n - 1 === 1 ? "y" : "ies"} →
         </button>`
      : "";

  const dateChips = (target) => `
    <span class="filter-label">When:</span>
    <button class="dossier-chip" data-target="${target}" data-filter="date" data-value="all" data-active="true">All time</button>
    <button class="dossier-chip" data-target="${target}" data-filter="date" data-value="365">Last year</button>
    <button class="dossier-chip" data-target="${target}" data-filter="date" data-value="90">Last 90d</button>
    <button class="dossier-chip" data-target="${target}" data-filter="date" data-value="30">Last 30d</button>
  `;

  const violationFilters = violations.length > 0 ? `
    <div class="dossier-filters" data-target="violations">
      <span class="filter-label">Status:</span>
      <button class="dossier-chip" data-target="violations" data-filter="status" data-value="all" data-active="true">All <span class="chip-count">${violations.length}</span></button>
      <button class="dossier-chip" data-target="violations" data-filter="status" data-value="active">Open <span class="chip-count">${openCount}</span></button>
      <button class="dossier-chip" data-target="violations" data-filter="status" data-value="closed">Closed <span class="chip-count">${closedCount}</span></button>
      ${dateChips("violations")}
    </div>` : "";

  const complaintFilters = complaints.length > 0 ? `
    <div class="dossier-filters" data-target="complaints">
      ${dateChips("complaints")}
    </div>` : "";

  showPanel(`
    <h2>Property Dossier</h2>
    <div class="addr">${escapeHtml(props.addr)}</div>
    <div class="owner">Owner of record: <strong>${escapeHtml(owner)}</strong></div>

    <div class="stat-grid">
      <div class="stat ${props.violations_open > 0 ? "bad" : ""}">
        <div class="num">${props.violations_open}</div>
        <div class="label">Open code violations</div>
      </div>
      <div class="stat">
        <div class="num">${props.violations_total}</div>
        <div class="label">Violations all-time</div>
      </div>
      <div class="stat ${props.complaints_311_12mo > 2 ? "warn" : ""}">
        <div class="num">${props.complaints_311_12mo}</div>
        <div class="label">311 housing 12mo</div>
      </div>
      <div class="stat ${props.demolished ? "bad" : ""}">
        <div class="num">${props.demolished ? "Yes" : "No"}</div>
        <div class="label">Demolished</div>
      </div>
    </div>

    ${portfolioCta}

    <h3 data-section-header="violations">Recent code violations <span class="header-counts" data-counts="violations">— ${violations.length} total · ${openCount} open</span></h3>
    <div class="section-meta">${freshnessPill("violations")}</div>
    ${violationFilters}
    ${violations.length === 0
      ? `<p class="empty">No code violations on record.</p>`
      : `<ul class="violations" data-list="violations">${violations.map(v => `
          <li data-status="${escapeHtml((v.status || "").toUpperCase())}" data-iso="${escapeHtml((v.date || "").slice(0, 10))}">
            <div class="date">${fmtDate(v.date)} · ${escapeHtml(v.status || "")}</div>
            <div>${escapeHtml(v.description || v.code_section || "—")}</div>
          </li>`).join("")}</ul>`
    }

    <h3 data-section-header="complaints">Recent 311 housing complaints <span class="header-counts" data-counts="complaints">— ${complaints.length} total</span></h3>
    <div class="section-meta">${freshnessPill("311")}</div>
    ${complaintFilters}
    ${complaints.length === 0
      ? `<p class="empty">No housing-related 311 complaints in the last 18 months.</p>`
      : `<ul class="complaints" data-list="complaints">${complaints.map(c => `
          <li data-iso="${escapeHtml((c.date || "").slice(0, 10))}">
            <div class="date">${fmtDate(c.date)}</div>
            <div>${escapeHtml(c.subject || c.reason || c.type || "—")}</div>
          </li>`).join("")}</ul>`
    }

    <div class="disclaimer">
      Code violations and 311 complaints are public records. They describe specific
      facts about a property — they are not a verdict about any person.
    </div>
  `);

  _wireDossierFilters();
}

// ---------- dossier filters (status + date range) ----------
function _dossierMaxDate(target) {
  const meta = state.meta || {};
  if (target === "violations") return (meta.code_violations_max_date || "").slice(0, 10);
  if (target === "complaints") return (meta.complaints_311_max_date || "").slice(0, 10);
  return "";
}

function _cutoffIso(maxDateIso, days) {
  if (!maxDateIso) return "";
  const anchor = new Date(maxDateIso + "T00:00:00Z");
  if (isNaN(anchor)) return "";
  anchor.setUTCDate(anchor.getUTCDate() - days);
  return anchor.toISOString().slice(0, 10);
}

function _wireDossierFilters() {
  const chips = $$("#panel .dossier-chip");
  if (!chips.length) return;
  chips.forEach(chip => {
    chip.addEventListener("click", () => {
      const { target, filter } = chip.dataset;
      $$(`#panel .dossier-chip[data-target="${target}"][data-filter="${filter}"]`)
        .forEach(c => { c.dataset.active = "false"; });
      chip.dataset.active = "true";
      applyDossierFilters(target);
    });
  });
  // Run once to set initial counts (renders are pre-filtered to "all").
  applyDossierFilters("violations");
  applyDossierFilters("complaints");
}

function applyDossierFilters(target) {
  const list = $(`#panel ul[data-list="${target}"]`);
  if (!list) return;
  const activeStatus = $(`#panel .dossier-chip[data-target="${target}"][data-filter="status"][data-active="true"]`)?.dataset.value || "all";
  const activeDate   = $(`#panel .dossier-chip[data-target="${target}"][data-filter="date"][data-active="true"]`)?.dataset.value || "all";
  const maxDate = _dossierMaxDate(target);
  const cutoffIso = activeDate === "all" ? "" : _cutoffIso(maxDate, parseInt(activeDate, 10));

  let visible = 0;
  let visibleOpen = 0;
  list.querySelectorAll("li").forEach(li => {
    const status = (li.dataset.status || "").toUpperCase();
    const iso = li.dataset.iso || "";
    let show = true;
    if (activeStatus === "active") show = show && (status === "ACTIVE");
    else if (activeStatus === "closed") show = show && (status && status !== "ACTIVE");
    if (cutoffIso) show = show && (iso >= cutoffIso);
    li.style.display = show ? "" : "none";
    if (show) {
      visible++;
      if (status === "ACTIVE") visibleOpen++;
    }
  });

  const counts = $(`#panel [data-counts="${target}"]`);
  if (counts) {
    const total = list.querySelectorAll("li").length;
    if (target === "violations") {
      counts.textContent = (visible === total)
        ? `— ${total} total · ${visibleOpen} open`
        : `— ${visible} of ${total} shown · ${visibleOpen} open`;
    } else {
      counts.textContent = (visible === total)
        ? `— ${total} total`
        : `— ${visible} of ${total} shown`;
    }
  }
}

window.openPortfolio = async function (slug, opts = {}) {
  try {
    const r = await fetch(`${DATA_BASE}/owners/${slug}.json`);
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    const portfolio = await r.json();
    portfolio._slug = slug;  // attach slug for the highlight toggle
    state.lastPortfolio = portfolio;
    state.lastOperator = null;
    if (opts.highlight) {
      applyMapFilter("owner", slug, portfolio.owner_display || slug);
    }
    renderPortfolio(portfolio);
    const target = `#/owner/${encodeURIComponent(slug)}${opts.highlight ? "/highlight" : ""}`;
    if (location.hash !== target) {
      history.replaceState(null, "", target);
    }
  } catch (e) {
    showPanel(`<p class="error">Couldn't load that owner's portfolio.</p>`);
  }
};

function renderPortfolio(portfolio) {
  const variants = portfolio.owner_variants?.length > 1
    ? `<p class="empty">Also recorded as: ${portfolio.owner_variants.slice(0, 5).map(escapeHtml).join(", ")}</p>`
    : "";

  const operatorCta = portfolio.operator_slug
    ? `<button class="cta" onclick="window.openOperator('${escapeHtml(portfolio.operator_slug)}')">
         Same mailing address as related LLCs →
       </button>`
    : "";

  const ownerSlug = portfolio._slug;
  const isHighlighted = state.mapFilter
    && state.mapFilter.kind === "owner"
    && state.mapFilter.slug === ownerSlug;
  const highlightBtn = ownerSlug
    ? `<button class="cta highlight-btn ${isHighlighted ? "toggled" : ""}"
              data-kind="owner"
              data-slug="${escapeHtml(ownerSlug)}"
              data-label="${escapeHtml(portfolio.owner_display || "")}">
         ${isHighlighted ? "✓ Highlighted on map" : "Highlight on map"}
       </button>`
    : "";

  const rows = (portfolio.properties || []).map(p => `
    <tr onclick="window.gotoParcel('${escapeHtml(p.id)}', ${p.lat}, ${p.lng})">
      <td data-label="Address">${escapeHtml(p.addr)}</td>
      <td data-label="Open" class="num ${p.violations_open > 0 ? "bad" : ""}">${p.violations_open}</td>
      <td data-label="311" class="num ${p.complaints_311_12mo > 2 ? "warn" : ""}">${p.complaints_311_12mo}</td>
      <td data-label="Demo" class="num ${p.demolished ? "bad" : ""}">${p.demolished ? "✗" : "—"}</td>
    </tr>
  `).join("");

  const operatorHint = portfolio.operator_confidence
    ? `<p class="evidence">Part of a <strong>${escapeHtml(portfolio.operator_confidence)}-confidence</strong> operator cluster.</p>`
    : "";

  showPanel(`
    <div class="panel-head">
      <h2>Owner Portfolio</h2>
      ${_panelHeadActionsHtml("portfolio")}
    </div>
    <div class="addr">${escapeHtml(portfolio.owner_display)}</div>
    ${operatorHint}
    ${portfolio.operator_slug
      ? ""
      : `<p class="evidence sub-note">Single owner — no LLC grouping applied. Properties owned by the same person under shell LLCs with distinct names may appear separately.</p>`}
    ${variants}

    <div class="stat-grid stat-grid--compact">
      <div class="stat">
        <div class="num">${portfolio.total_properties}</div>
        <div class="label">Properties</div>
      </div>
      <div class="stat ${portfolio.total_violations > 20 ? "bad" : portfolio.total_violations > 5 ? "warn" : ""}">
        <div class="num">${portfolio.total_violations}</div>
        <div class="label">Violations (sum)</div>
      </div>
      <div class="stat">
        <div class="num">${fmtMoney(portfolio.total_value)}</div>
        <div class="label">Portfolio value</div>
      </div>
    </div>

    ${_violationTypesHtml(portfolio.top_violation_types)}

    ${operatorCta}
    ${highlightBtn}

    <h3>Properties (sorted by concern score)</h3>
    <div class="section-meta">${freshnessPill("violations")} ${freshnessPill("311")}</div>
    <table class="portfolio">
      <thead><tr><th>Address</th><th class="num">Open</th><th class="num">311</th><th class="num">Demo</th></tr></thead>
      <tbody>${rows}</tbody>
    </table>

    <div class="disclaimer">
      Owners are matched by name normalization. Properties owned by the same person
      under different LLCs (with distinct names) may appear separately. Bulk LLC
      ownership data is not publicly available in NYS.
    </div>
  `);
}

window.gotoParcel = function (id, lat, lng) {
  if (lat && lng) state.map.flyTo({ center: [lng, lat], zoom: 18 });
  if (state.map && state.map.loaded?.() && state.map.isStyleLoaded?.()) {
    selectParcel(id);
  } else if (state.map) {
    const gotoToken = ++_selectParcelToken;
    state.map.once("idle", () => {
      if (gotoToken !== _selectParcelToken) return;
      selectParcel(id);
    });
  }
};

// ---------- map filter (highlight an owner/operator's parcels) ----------
function _highlightedPoints(kind, slug) {
  // Returns [{lat,lng}, ...] from in-memory data — used for both bbox + the
  // centroid Points source that backs the highlight-circle layer.
  if (kind === "owner") {
    return state.addressIndex.filter(a => a.owner_slug === slug && a.lat && a.lng);
  }
  if (kind === "operator") {
    const op = state.lastOperator;
    if (op && op.operator_slug === slug) {
      return (op.properties || []).filter(p => p.lat && p.lng);
    }
  }
  return [];
}

function _bboxOf(points) {
  if (!points.length) return null;
  let minLng = points[0].lng, maxLng = points[0].lng, minLat = points[0].lat, maxLat = points[0].lat;
  for (const p of points) {
    if (p.lng < minLng) minLng = p.lng;
    if (p.lng > maxLng) maxLng = p.lng;
    if (p.lat < minLat) minLat = p.lat;
    if (p.lat > maxLat) maxLat = p.lat;
  }
  return [[minLng, minLat], [maxLng, maxLat]];
}

function applyMapFilter(kind, slug, label) {
  if (!state.map || !state.map.getLayer("parcels-fill")) return;
  const expr = kind === "owner"
    ? ["==", ["get", "owner_slug"], slug]
    : ["==", ["get", "operator_slug"], slug];

  // Show dim backdrop over all parcels.
  state.map.setLayoutProperty("parcels-dim-fill", "visibility", "visible");

  // Polygon-fill highlight (visible at higher zoom).
  state.map.setFilter("parcels-highlight-fill", expr);
  state.map.setLayoutProperty("parcels-highlight-fill", "visibility", "visible");

  // Centroid Points source for the circle markers — one per parcel.
  const points = _highlightedPoints(kind, slug);
  const fc = {
    type: "FeatureCollection",
    features: points.map(p => ({
      type: "Feature",
      geometry: { type: "Point", coordinates: [p.lng, p.lat] },
      properties: {},
    })),
  };
  state.map.getSource("highlight-points").setData(fc);
  state.map.setLayoutProperty("parcels-highlight-circle", "visibility", "visible");

  state.mapFilter = { kind, slug, label, count: points.length };

  const bounds = _bboxOf(points);
  if (bounds) {
    state.map.fitBounds(bounds, { padding: 60, maxZoom: 17, duration: 700 });
  }
  updateFilterChip();
}

function clearMapFilter() {
  if (!state.map) return;
  if (state.map.getLayer("parcels-highlight-fill")) {
    state.map.setLayoutProperty("parcels-dim-fill", "visibility", "none");
    state.map.setLayoutProperty("parcels-highlight-fill", "visibility", "none");
    state.map.setLayoutProperty("parcels-highlight-circle", "visibility", "none");
    state.map.setFilter("parcels-highlight-fill", ["==", ["get", "owner_slug"], "__none__"]);
    state.map.getSource("highlight-points").setData({ type: "FeatureCollection", features: [] });
  }
  state.mapFilter = null;
  updateFilterChip();
  // Strip /highlight suffix from URL if present, leaving the parent route intact.
  const m = location.hash.match(/^(#\/(?:owner|operator)\/[^/]+)\/highlight$/);
  if (m) {
    history.replaceState(null, "", m[1]);
  }
}

function updateFilterChip() {
  const chip = $("#filter-chip");
  if (!state.mapFilter) {
    chip.classList.add("hidden");
    chip.innerHTML = "";
    return;
  }
  const { label, count } = state.mapFilter;
  chip.innerHTML = `Showing only <strong>${escapeHtml(label)}</strong> <span class="count">· ${count} parcel${count === 1 ? "" : "s"}</span> <span class="clear">✕ Clear</span>`;
  chip.classList.remove("hidden");
}

window.toggleMapHighlight = function (kind, slug, label) {
  const turningOn = !(state.mapFilter && state.mapFilter.kind === kind && state.mapFilter.slug === slug);
  if (turningOn) {
    applyMapFilter(kind, slug, label);
  } else {
    clearMapFilter();
  }
  // Sync URL: add or strip /highlight suffix on the current owner/operator route.
  const target = `#/${kind}/${encodeURIComponent(slug)}${turningOn ? "/highlight" : ""}`;
  if (location.hash !== target) {
    history.replaceState(null, "", target);
  }
  // Re-render whichever panel is showing so the toggle reflects the new state.
  if (state.lastOperator) {
    renderOperator(state.lastOperator);
  } else if (state.lastPortfolio) {
    renderPortfolio(state.lastPortfolio);
  }
  // On phones, collapse the sheet to peek when turning highlight ON so the
  // user actually sees what got highlighted on the map.
  if (turningOn && window.matchMedia("(max-width: 480px)").matches && window.__setSheetSnap) {
    window.__setSheetSnap("sheet-peek");
  }
};

// ---------- leaderboards ----------
const BOARDS = [
  { key: "by_open_violations", label: "Open",  stat: "open",                statLabel: "open" },
  { key: "by_all_violations",  label: "All",   stat: "all_violations",      statLabel: "viol." },
  { key: "by_properties",      label: "Props", stat: "properties",          statLabel: "props" },
  { key: "by_value",           label: "Value", stat: "total_value",         statLabel: "",      money: true },
  { key: "by_complaints_311",  label: "311",   stat: "complaints_311_12mo", statLabel: "311" },
];

function _syncLeaderboardHash() {
  const target = `#/top/${state.activeBoard}/${state.activeBoardKind}`;
  if (location.hash !== target) {
    history.replaceState(null, "", target);
  }
}

function renderLeaderboards() {
  const isOperators = state.activeBoardKind === "operators";
  const data = isOperators ? state.topOperators : state.topOwners;
  if (!data) {
    showPanel(`<p class="empty">Loading leaderboards…</p>`);
    return;
  }
  // Sync hash to current tab/kind so "Copy link" reflects the view.
  _syncLeaderboardHash();
  const active = BOARDS.find(b => b.key === state.activeBoard) || BOARDS[0];
  const list = data[active.key] || [];

  const tabs = BOARDS.map(b =>
    `<button class="${b.key === active.key ? "active" : ""}" data-board="${b.key}">${b.label}</button>`
  ).join("");

  const rows = list.map((o, i) => {
    const cls = i === 0 ? "top1" : i === 1 ? "top2" : i === 2 ? "top3" : "";
    const sub = isOperators
      ? `${o.owners_n} LLCs · ${o.properties} props · ${o.open} open · ${fmtMoney(o.total_value)}`
      : `${o.properties} prop${o.properties === 1 ? "" : "s"} · ${o.open} open · ${fmtMoney(o.total_value)}`;
    const display = isOperators ? o.label : o.display;
    const action = isOperators
      ? `data-op="${escapeHtml(o.slug)}"`
      : `data-slug="${escapeHtml(o.slug)}"`;
    const statValue = active.money ? fmtMoney(o[active.stat]) : o[active.stat];
    const confDot = (isOperators && o.confidence)
      ? `<span class="conf-dot conf-${escapeHtml(o.confidence)}" title="${escapeHtml(o.evidence || "")}"></span>`
      : "";
    return `
      <li class="${cls}" ${action}>
        <span class="rank">${i + 1}</span>
        <span class="name">${confDot}${escapeHtml(display)}<span class="sub">${sub}</span></span>
        <span class="stat-num">${statValue}${active.statLabel ? ` <span class="sub" style="display:inline">${active.statLabel}</span>` : ""}</span>
      </li>`;
  }).join("");

  const phone = window.matchMedia("(max-width: 480px)").matches;
  const operatorsLabel = phone
    ? `Operators <button type="button" class="info-btn" aria-label="What does Operators mean?" aria-expanded="false" data-info-tip="Grouped by shared mailing address — typically a real signal, but lawyers and property managers can cause false merges.">ⓘ</button>`
    : "Operators (mailing-address clusters)";
  const ownersLabel = phone
    ? `Owner names <button type="button" class="info-btn" aria-label="What does Owner names mean?" aria-expanded="false" data-info-tip="Raw LLC names — every distinct LLC is treated as a separate owner.">ⓘ</button>`
    : "Owner names (raw)";
  const kindToggle = `
    <div class="kind-toggle">
      <button class="${isOperators ? "active" : ""}" data-kind="operators">${operatorsLabel}</button>
      <button class="${!isOperators ? "active" : ""}" data-kind="owners">${ownersLabel}</button>
    </div>`;

  showPanel(`
    <div class="panel-head">
      <h2>Top Landlords</h2>
      ${_panelHeadActionsHtml(null)}
    </div>
    <p class="empty" style="margin:0 0 8px;">Public records, ranked. Excludes city, county, state, and federal owners.</p>

    ${kindToggle}
    <div class="tabs">${tabs}</div>

    ${list.length === 0
      ? `<p class="empty">No entries with non-zero count for this category.</p>`
      : `<ul class="leaderboard">${rows}</ul>`
    }

    <div class="disclaimer">
      ${isOperators
        ? "Operators are inferred by clustering owners that share a mailing address — typically a real signal, but lawyers and property managers can cause false merges. Click an operator to see the constituent LLCs."
        : "Owner-name view treats every distinct LLC as separate. Switch to Operators to see clusters that share a mailing address."}
      The 311 board is anchored to 2024-05-10 (source feed stopped updating).
    </div>
  `);

  // Wire ⓘ info tooltips (mobile only — desktop renders inline label text instead)
  $$("#panel .info-btn").forEach(infoBtn => {
    const tip = infoBtn.dataset.infoTip;
    if (!tip) return;
    // Create a shared singleton popover anchored near the button
    const showTip = () => {
      let tip_el = document.getElementById("leaderboard-info-tip");
      if (!tip_el) {
        tip_el = document.createElement("div");
        tip_el.id = "leaderboard-info-tip";
        tip_el.className = "info-tip-popover";
        tip_el.setAttribute("role", "tooltip");
        document.body.appendChild(tip_el);
      }
      tip_el.textContent = infoBtn.dataset.infoTip;
      tip_el.hidden = false;
      infoBtn.setAttribute("aria-expanded", "true");
      // Position below the button
      const rect = infoBtn.getBoundingClientRect();
      tip_el.style.top = `${rect.bottom + window.scrollY + 4}px`;
      tip_el.style.left = `${Math.min(rect.left, window.innerWidth - 220)}px`;
    };
    const hideTip = () => {
      const tip_el = document.getElementById("leaderboard-info-tip");
      if (tip_el) tip_el.hidden = true;
      infoBtn.setAttribute("aria-expanded", "false");
    };
    infoBtn.addEventListener("click", (e) => {
      e.stopPropagation(); // don't fire kind-toggle parent
      const tip_el = document.getElementById("leaderboard-info-tip");
      const isOpen = tip_el && !tip_el.hidden && infoBtn.getAttribute("aria-expanded") === "true";
      isOpen ? hideTip() : showTip();
    });
    document.addEventListener("click", (e) => {
      if (!e.target.closest(".info-btn")) hideTip();
    }, { once: false });
    document.addEventListener("keydown", (e) => {
      if (e.key === "Escape") hideTip();
    });
  });

  // Wire kind toggle, tabs, rows
  $$("#panel .kind-toggle button[data-kind]").forEach(btn => {
    btn.addEventListener("click", () => {
      state.activeBoardKind = btn.dataset.kind;
      _syncLeaderboardHash();
      renderLeaderboards();
    });
  });
  $$("#panel .tabs button").forEach(btn => {
    btn.addEventListener("click", () => {
      state.activeBoard = btn.dataset.board;
      _syncLeaderboardHash();
      renderLeaderboards();
    });
  });
  $$("#panel .leaderboard li").forEach(li => {
    if (li.dataset.op) {
      li.addEventListener("click", () => window.openOperator(li.dataset.op));
    } else if (li.dataset.slug) {
      li.addEventListener("click", () => window.openPortfolio(li.dataset.slug));
    }
  });
}

// Render the "How these names are grouped" disclosure body for an operator.
// Pulls fields from op.audit (emitted by the pipeline). Falls back to the
// top-level evidence string if op.audit is missing (older data files).
function renderAuditDisclosure(op) {
  const a = op.audit;
  if (!a) {
    return op.evidence
      ? `<details class="audit-details"><summary>
           <span class="audit-summary-desktop">How these names are grouped</span>
           <span class="audit-summary-mobile">Grouping evidence</span>
         </summary>
           <p>${escapeHtml(op.evidence)}</p>
         </details>`
      : "";
  }

  const cohesion = a.cohesion || {};
  const cohesionLine = cohesion.explanation
    ? `<li><span class="audit-key">Cohesion</span> ${escapeHtml(cohesion.explanation)} <span class="sub">(score ${cohesion.score})</span></li>`
    : "";
  const patternLine = a.pattern === "alter_ego"
    ? `<li><span class="audit-key">Pattern</span> alter-ego — one person + one LLC at the same street address. Classic LLC-unmasking signal.</li>`
    : "";
  // Service-address classification (NYS DOS join). Rendered only when the
  // pipeline has classified the address; "unknown" is silent because we
  // don't want to imply false confidence either way.
  const sa = a.service_address || {};
  const serviceAddrLine = sa.classification === "registered_agent"
    ? `<li class="audit-warn"><span class="audit-key">Service address</span> ${(sa.nys_dos_entity_count || 0).toLocaleString()} unrelated NY entities are registered at this address — likely a registered-agent or filing-service address, not a real shared owner. <span class="sub">(NYS DOS, threshold ${sa.threshold})</span></li>`
    : sa.classification === "shared_owner"
    ? `<li><span class="audit-key">Service address</span> No registered-agent pool detected at this address. <span class="sub">(NYS DOS)</span></li>`
    : "";
  const dedupLines = (a.person_dedups || []).map(d => `
    <li><span class="audit-key">Name dedup</span>
      <strong>${escapeHtml(d.canonical)}</strong>
      <span class="sub">also recorded as: ${(d.variants || []).map(escapeHtml).join(", ")}</span>
    </li>`).join("");
  const memberLines = (op.owners || []).map(o => `
    <li><span class="audit-key">Member</span> ${escapeHtml(o.display)}
      <span class="sub">(${o.properties} prop${o.properties === 1 ? "" : "s"})</span>
    </li>`).join("");
  const coOwnerLines = (a.co_owners || []).map(c => `
    <li><span class="audit-key">Co-owner</span>
      <strong>${escapeHtml(c.name)}</strong>
      <span class="sub">(${c.parcels} parcel${c.parcels === 1 ? "" : "s"} in this cluster)</span>
    </li>`).join("");
  const linkedOpLines = (a.linked_operators || []).map(L => `
    <li><span class="audit-key">Linked operator</span>
      <a href="#/operator/${encodeURIComponent(L.operator_slug)}"
         onclick="event.preventDefault(); window.openOperator('${escapeHtml(L.operator_slug)}')">${escapeHtml(L.operator_label)}</a>
      <span class="sub">via ${escapeHtml(L.co_owner)} (${L.parcels} parcel${L.parcels === 1 ? "" : "s"} there)</span>
    </li>`).join("");

  const mobileSummary = [
    `${a.member_count || (op.owners || []).length} LLC${(a.member_count || 0) === 1 ? "" : "s"}`,
    a.shared_mailing_address ? "shared mailing addr" : null,
    cohesion.score != null ? `cohesion ${cohesion.score}` : null,
  ].filter(Boolean).join(" · ");

  return `
    <details class="audit-details">
      <summary>
        <span class="audit-summary-desktop">How these names are grouped</span>
        <span class="audit-summary-mobile">${escapeHtml(mobileSummary)}</span>
      </summary>
      <ul class="audit-list">
        <li><span class="audit-key">Shared mailing address</span> ${escapeHtml(a.shared_mailing_address || "—")}
          <span class="sub">(${escapeHtml(a.address_kind || "")})</span></li>
        ${cohesionLine}
        ${serviceAddrLine}
        ${patternLine}
        ${dedupLines}
        ${memberLines}
        ${coOwnerLines}
        ${linkedOpLines}
      </ul>
      <p class="audit-foot sub">${a.member_count} LLC${a.member_count === 1 ? "" : "s"} merged into one operator. Bulk LLC ownership data is not publicly available in NYS, so this is the best inference the public data allows.</p>
    </details>`;
}

// ---------- operator view ----------
window.openOperator = async function (slug, opts = {}) {
  try {
    const r = await fetch(`${DATA_BASE}/operators/${slug}.json`);
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    const op = await r.json();
    state.lastOperator = op;
    state.lastPortfolio = null;
    if (opts.highlight) {
      // applyMapFilter for operator kind reads state.lastOperator, so it must
      // be set above first.
      applyMapFilter("operator", slug, op.operator_label || slug);
    }
    renderOperator(op);
    const target = `#/operator/${encodeURIComponent(slug)}${opts.highlight ? "/highlight" : ""}`;
    if (location.hash !== target) {
      history.replaceState(null, "", target);
    }
  } catch (e) {
    showPanel(`<p class="error">Couldn't load that operator.</p>`);
  }
};

function renderOperator(op) {
  const isHighlighted = state.mapFilter
    && state.mapFilter.kind === "operator"
    && state.mapFilter.slug === op.operator_slug;
  const highlightBtn = `<button class="cta highlight-btn ${isHighlighted ? "toggled" : ""}"
            data-kind="operator"
            data-slug="${escapeHtml(op.operator_slug)}"
            data-label="${escapeHtml(op.operator_label || "")}">
       ${isHighlighted ? "✓ Highlighted on map" : "Highlight on map"}
     </button>`;

  const confBadge = op.confidence
    ? `<span class="conf-badge conf-${escapeHtml(op.confidence)}">${escapeHtml(op.confidence)}-confidence cluster</span>`
    : "";
  const serviceAddrBadge = (op.audit && op.audit.service_address && op.audit.service_address.classification === "registered_agent")
    ? `<button type="button" class="service-addr-badge"
         title="This mailing address registers ${(op.audit.service_address.nys_dos_entity_count || 0).toLocaleString()} unrelated NY entities — likely a registered-agent or filing-service pool. Click to see how these names are grouped."
         onclick="window.openAuditDisclosure()">⚠ service address</button>`
    : "";
  const evidenceLine = op.evidence
    ? `<p class="evidence">${escapeHtml(op.evidence)}</p>`
    : "";

  // Render owner_groups when present (collapses person-name variants), else
  // fall back to the raw owners list so old data still works.
  const ownerBySlug = Object.fromEntries((op.owners || []).map(o => [o.slug, o]));
  const groups = (op.owner_groups && op.owner_groups.length)
    ? op.owner_groups
    : (op.owners || []).map(o => ({
        canonical: o.display, variants: [], slugs: [o.slug], property_count: o.properties,
      }));
  const ownersList = groups.map(g => {
    const totalOpen = g.slugs.reduce((s, sl) => s + (ownerBySlug[sl]?.open || 0), 0);
    const totalAll = g.slugs.reduce((s, sl) => s + (ownerBySlug[sl]?.all_violations || 0), 0);
    const variantHint = (g.variants && g.variants.length)
      ? ` <span class="sub" style="display:inline">also: ${g.variants.map(escapeHtml).join(", ")}</span>`
      : "";
    return `
      <li data-slug="${escapeHtml(g.slugs[0] || "")}">
        <span class="name">${escapeHtml(g.canonical)}${variantHint}<span class="sub">${g.property_count} props · ${totalOpen} open · ${totalAll} all-time</span></span>
        <span class="stat-num">${totalOpen}</span>
      </li>`;
  }).join("");

  const propsRows = (op.properties || []).slice(0, 200).map(p => `
    <tr onclick="window.gotoParcel('${escapeHtml(p.id)}', ${p.lat}, ${p.lng})">
      <td data-label="Address">${escapeHtml(p.addr)}</td>
      <td data-label="Open" class="num ${p.violations_open > 0 ? "bad" : ""}">${p.violations_open}</td>
      <td data-label="311" class="num ${p.complaints_311_12mo > 2 ? "warn" : ""}">${p.complaints_311_12mo}</td>
      <td data-label="Demo" class="num ${p.demolished ? "bad" : ""}">${p.demolished ? "✗" : "—"}</td>
    </tr>
  `).join("");

  showPanel(`
    <div class="panel-head">
      <h2>Operator</h2>
      ${_panelHeadActionsHtml("operator")}
    </div>
    <div class="addr-row">
      <div class="addr">${escapeHtml(op.operator_label)}</div>
      ${confBadge}${serviceAddrBadge}
    </div>
    ${evidenceLine}
    <p class="empty" style="margin:2px 0 12px;">Mailing address: <strong>${escapeHtml(op.mailing_address)}</strong></p>
    <div class="dossier-freshness">${freshnessPill("violations")} ${freshnessPill("311")}</div>
    ${renderAuditDisclosure(op)}

    <div class="stat-grid stat-grid--compact">
      <div class="stat"><div class="num">${op.total_properties}</div><div class="label">Properties</div></div>
      <div class="stat ${op.total_open_violations > 50 ? "bad" : op.total_open_violations > 10 ? "warn" : ""}">
        <div class="num">${op.total_open_violations}</div><div class="label">Open violations</div>
      </div>
      <div class="stat"><div class="num">${op.total_all_violations}</div><div class="label">All-time violations</div></div>
      <div class="stat"><div class="num">${op.total_complaints_311_12mo}</div><div class="label">311 (12mo)</div></div>
      <div class="stat"><div class="num">${fmtMoney(op.total_value)}</div><div class="label">Portfolio value</div></div>
    </div>

    ${highlightBtn}

    ${_violationTypesHtml(op.top_violation_types)}

    <h3>Constituent LLCs (${op.owners.length})</h3>
    <ul class="leaderboard llc-list">${ownersList}</ul>

    <h3>Properties (top 200 by concern)</h3>
    <div class="section-meta">${freshnessPill("violations")} ${freshnessPill("311")}</div>
    <table class="portfolio">
      <thead><tr><th>Address</th><th class="num">Open</th><th class="num">311</th><th class="num">Demo</th></tr></thead>
      <tbody>${propsRows}</tbody>
    </table>

    <div class="disclaimer">
      These owners share a mailing address, which often (but not always) means a single
      operator. Click any LLC above to see it on its own. Bulk LLC ownership data is
      not publicly available in NYS, so this is the best inference the public data allows.
    </div>
  `);

  $$("#panel .llc-list li").forEach(li => {
    li.addEventListener("click", () => window.openPortfolio(li.dataset.slug));
  });
}

// ---------- search ----------
function setupSearch() {
  const input = $("#search");
  const results = $("#search-results");

  input.addEventListener("input", () => {
    const q = input.value.trim().toUpperCase();
    if (q.length < 3) { results.classList.remove("open"); return; }
    const matches = state.addressIndex
      .filter((a) => a.addr.toUpperCase().includes(q))
      .slice(0, 12);
    if (matches.length === 0) {
      results.innerHTML = `<li class="empty">No matches</li>`;
    } else {
      results.innerHTML = matches.map(m =>
        `<li data-id="${escapeHtml(m.id)}" data-lat="${m.lat ?? ''}" data-lng="${m.lng ?? ''}">${escapeHtml(m.addr)}</li>`
      ).join("");
    }
    results.classList.add("open");
  });

  results.addEventListener("click", (e) => {
    const li = e.target.closest("li");
    if (!li || !li.dataset.id) return;
    input.value = li.textContent;
    results.classList.remove("open");
    const lat = parseFloat(li.dataset.lat), lng = parseFloat(li.dataset.lng);
    if (!isNaN(lat) && !isNaN(lng)) {
      state.map.flyTo({ center: [lng, lat], zoom: 18 });
      // Wait for the fly + tile load before trying to read the rendered feature
      const searchToken = ++_selectParcelToken;
      state.map.once("idle", () => {
        if (searchToken !== _selectParcelToken) return;
        selectParcel(li.dataset.id);
      });
    } else {
      selectParcel(li.dataset.id);
    }
  });

  document.addEventListener("click", (e) => {
    if (!$("#search-row").contains(e.target)) results.classList.remove("open");
  });
}

// ---------- meta + bootstrap ----------
async function loadMeta() {
  try {
    const r = await fetch(`${DATA_BASE}/meta.json`);
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    state.meta = await r.json();
    const date = (state.meta.generated_at || "").slice(0, 10);
    const c311 = (state.meta.complaints_311_max_date || "").slice(0, 10);
    const c311Note = c311 ? ` · 311 data through ${c311}` : "";
    $("#meta-info").textContent =
      `Refreshed ${date} · ${(state.meta.parcels ?? 0).toLocaleString()} parcels · ${(state.meta.owners ?? 0).toLocaleString()} owners${c311Note}`;
    const issueEl = $("#issue-date");
    if (issueEl && date) issueEl.textContent = `Public records · Buffalo, N.Y. · refreshed ${date}`;
  } catch {
    $("#meta-info").textContent = "Refresh date unknown";
  }
}

async function loadAddressIndex() {
  try {
    const r = await fetch(`${DATA_BASE}/address_index.json`);
    state.addressIndex = await r.json();
  } catch (e) {
    console.error("address index load failed", e);
    state.addressIndex = [];
  }
}

async function loadTopOwners() {
  try {
    const r = await fetch(`${DATA_BASE}/top_owners.json`);
    state.topOwners = await r.json();
  } catch (e) {
    console.error("top owners load failed", e);
    state.topOwners = { by_open_violations: [], by_all_violations: [], by_properties: [], by_complaints_311: [] };
  }
}

async function loadTopOperators() {
  try {
    const r = await fetch(`${DATA_BASE}/top_operators.json`);
    state.topOperators = await r.json();
  } catch (e) {
    console.error("top operators load failed", e);
    state.topOperators = { by_open_violations: [], by_all_violations: [], by_properties: [], by_complaints_311: [] };
  }
}

function applyHashRoute() {
  const hash = location.hash;
  // Clear the search input address label when navigating away from a parcel
  if (!hash.match(/^#\/parcel\//)) {
    const searchInput = $("#search");
    if (searchInput) searchInput.value = "";
  }
  let m;
  if ((m = hash.match(/^#\/parcel\/(.+)$/))) {
    const id = decodeURIComponent(m[1]);
    if (id !== state.selectedId) selectParcel(id);
  } else if ((m = hash.match(/^#\/owner\/([^/]+)(\/highlight)?$/))) {
    const slug = decodeURIComponent(m[1]);
    window.openPortfolio(slug, { highlight: !!m[2] });
  } else if ((m = hash.match(/^#\/operator\/([^/]+)(\/highlight)?$/))) {
    const slug = decodeURIComponent(m[1]);
    window.openOperator(slug, { highlight: !!m[2] });
  } else if ((m = hash.match(/^#\/top\/([^/]+)\/([^/]+)$/))) {
    const board = m[1];
    const kind = m[2];
    if (BOARDS.find(b => b.key === board)) state.activeBoard = board;
    if (kind === "owners" || kind === "operators") state.activeBoardKind = kind;
    state.selectedId = null;
    state.lastPortfolio = null;
    state.lastOperator = null;
    renderLeaderboards();
  } else if (!hash) {
    hidePanel();
  } else {
    // Unknown hash — reset state and show leaderboards
    state.selectedId = null;
    state.lastPortfolio = null;
    state.lastOperator = null;
    renderLeaderboards();
  }
}

function setupHashRouting() {
  window.addEventListener("hashchange", applyHashRoute);
}

// ---------- panel collapse (desktop only) ----------
function setupPanelCollapse() {
  const btn = $("#panel-collapse");
  const panel = $("#panel");
  if (!btn || !panel) return;

  const isPhone = () => window.matchMedia("(max-width: 480px)").matches;

  function setCollapsed(collapsed) {
    if (collapsed) {
      document.body.classList.add("panel-collapsed");
      btn.setAttribute("aria-label", "Expand panel");
      btn.setAttribute("title", "Expand panel");
      btn.textContent = "›";
    } else {
      document.body.classList.remove("panel-collapsed");
      btn.setAttribute("aria-label", "Collapse panel");
      btn.setAttribute("title", "Collapse panel");
      btn.textContent = "‹";
    }
  }

  // Restore from localStorage on load.
  if (!isPhone() && localStorage.getItem("panelCollapsed") === "true") {
    setCollapsed(true);
  }

  btn.addEventListener("click", (e) => {
    if (isPhone()) return;
    e.stopPropagation();
    const nowCollapsed = !document.body.classList.contains("panel-collapsed");
    setCollapsed(nowCollapsed);
    localStorage.setItem("panelCollapsed", String(nowCollapsed));
  });

  // Clicking the rail (collapsed panel) expands it.
  panel.addEventListener("click", (e) => {
    if (!document.body.classList.contains("panel-collapsed")) return;
    setCollapsed(false);
    localStorage.setItem("panelCollapsed", "false");
  });

  // On resize: if phone, remove collapsed class (bottom sheet takes over),
  // but leave localStorage untouched so desktop remembers.
  window.addEventListener("resize", () => {
    if (isPhone() && document.body.classList.contains("panel-collapsed")) {
      document.body.classList.remove("panel-collapsed");
    }
  });
}

// ---------- bottom sheet (phones only) ----------
function setupBottomSheet() {
  const panel = $("#panel");
  const handle = panel.querySelector(".panel-handle");
  if (!handle) return;
  const isPhone = () => window.matchMedia("(max-width: 480px)").matches;

  const SNAPS = ["sheet-peek", "sheet-half", "sheet-full"];
  const setSnap = (name) => {
    SNAPS.forEach(c => panel.classList.remove(c));
    panel.classList.add(name);
    panel.classList.remove("hidden");
    panel.style.height = "";
    // Update reopen-panel label at peek state
    const reopenBtn = $("#reopen-panel");
    if (name === "sheet-peek") {
      reopenBtn.innerHTML = "▴ Open";
      reopenBtn.classList.remove("hidden");
    }
    // If user opened a closed panel via the handle, restore last view.
    if (!$("#panel-content").innerHTML.trim()) {
      renderLeaderboards();
    }
  };
  // Expose so other handlers (Highlight on map) can collapse the sheet.
  window.__setSheetSnap = setSnap;
  const currentSnap = () =>
    SNAPS.find(c => panel.classList.contains(c)) || "sheet-half";

  let dragging = false;
  let startY = 0;
  let startH = 0;
  let lastY = 0;

  handle.addEventListener("pointerdown", (e) => {
    if (!isPhone()) return;
    dragging = true;
    startY = lastY = e.clientY;
    startH = panel.getBoundingClientRect().height;
    panel.style.transition = "none";
    panel.classList.add("dragging");
    handle.setPointerCapture(e.pointerId);
    e.preventDefault();
  });
  handle.addEventListener("pointermove", (e) => {
    if (!dragging) return;
    lastY = e.clientY;
    const dy = e.clientY - startY;
    const newH = Math.max(80, Math.min(window.innerHeight, startH - dy));
    panel.style.height = `${newH}px`;
    e.preventDefault();
  });
  const endDrag = (e) => {
    if (!dragging) return;
    dragging = false;
    panel.style.transition = "";
    panel.classList.remove("dragging");
    const moved = Math.abs(lastY - startY);
    const heights = {
      "sheet-peek": 120,
      "sheet-half": Math.round(window.innerHeight * 0.55),
      "sheet-full": Math.round(window.innerHeight * 0.92),
    };
    let snap;
    if (moved < 6) {
      // tap — cycle peek → half → full → peek
      const cur = currentSnap();
      snap = { "sheet-peek": "sheet-half", "sheet-half": "sheet-full", "sheet-full": "sheet-peek" }[cur];
    } else {
      const h = panel.getBoundingClientRect().height;
      let bestKey = "sheet-half", bestDist = Infinity;
      for (const [key, target] of Object.entries(heights)) {
        const d = Math.abs(h - target);
        if (d < bestDist) { bestDist = d; bestKey = key; }
      }
      snap = bestKey;
    }
    setSnap(snap);
    try { handle.releasePointerCapture(e.pointerId); } catch {}
  };
  handle.addEventListener("pointerup", endDrag);
  handle.addEventListener("pointercancel", endDrag);

  // Keyboard accessibility — Enter/Space cycles snap states.
  handle.addEventListener("keydown", (e) => {
    if (!isPhone()) return;
    if (e.key === "Enter" || e.key === " ") {
      e.preventDefault();
      const cur = currentSnap();
      setSnap({ "sheet-peek": "sheet-half", "sheet-half": "sheet-full", "sheet-full": "sheet-peek" }[cur]);
    }
  });
}

async function bootstrap() {
  $("#filter-chip").addEventListener("click", clearMapFilter);
  $("#panel-close").addEventListener("click", (e) => {
    state.selectedId = null;
    state.lastPortfolio = null;
    state.lastOperator = null;
    // From a dossier/operator/owner route, go back to leaderboards.
    // From leaderboards: phones fully hide (bottom-sheet peek + reopen button);
    // desktop/tablet collapse to the rail so there's one mechanism for "give me
    // back the map" — the side-panel collapse toggle.
    const onLeaderboards = !location.hash || /^#\/top\//.test(location.hash);
    const isPhone = window.matchMedia("(max-width: 480px)").matches;
    if (onLeaderboards) {
      if (isPhone) {
        // Collapse the sheet to peek instead of fully hiding it — fully hidden
        // looks like a blank drawer and there's no parent view to return to.
        // Peek keeps the leaderboard title visible and the drag handle in reach.
        if (window.__setSheetSnap) window.__setSheetSnap("sheet-peek");
        else fullyHidePanel();
      } else if (!document.body.classList.contains("panel-collapsed")) {
        // Stop the bubble so the panel's rail-click handler doesn't immediately
        // re-expand the rail we just collapsed.
        e.stopPropagation();
        $("#panel-collapse").click();
      }
    } else {
      location.hash = "";
    }
  });
  $("#reopen-panel").addEventListener("click", () => {
    renderLeaderboards();
  });
  setupPanelCollapse();
  initMap();
  setupSearch();
  setupHashRouting();
  setupBottomSheet();
  await Promise.all([loadMeta(), loadAddressIndex(), loadTopOwners(), loadTopOperators()]);

  // Replay initial hash route after data load, otherwise show leaderboards.
  if (location.hash) {
    applyHashRoute();
  } else {
    renderLeaderboards();
  }
}

// Module scripts are deferred — they execute after DOMContentLoaded fires,
// so a plain `addEventListener("DOMContentLoaded", ...)` never runs in
// production. Branch on readyState so we work in both states (and so the
// jsdom test setup, which imports the module after the DOM is parsed,
// also runs the bootstrap).
if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", bootstrap);
} else {
  bootstrap();
}

// Test surface — these names back the tests in tests/*.test.js, which
// import this module via setupFiles. Keeping them in a single export at
// the bottom makes the test contract explicit.
export {
  // pure helpers
  escapeHtml,
  fmtDate,
  fmtMoney,
  freshnessPill,
  // shared mutable state (tests reset between cases)
  state,
  // panel helpers
  showPanel,
  hidePanel,
  fullyHidePanel,
  // view renderers
  renderDossier,
  renderPortfolio,
  renderLeaderboards,
  renderOperator,
  renderAuditDisclosure,
  // routing
  applyHashRoute,
  // map filter
  applyMapFilter,
  clearMapFilter,
  updateFilterChip,
  // dossier filters
  applyDossierFilters,
  // CSV export
  buildPortfolioCsv,
  // search wiring (tests call this directly because the bootstrap's
  // DOMContentLoaded already fired by the time test files import)
  setupSearch,
  // constants
  BOARDS,
};
