// Buffalo Landlord Lookup — vanilla-JS frontend
// Loads static JSON artifacts emitted by ../pipeline and renders three views:
//   - Landing: full Buffalo map, parcels colored by concern score
//   - Dossier: clicked parcel detail
//   - Portfolio: every parcel an owner has

const BUFFALO = { lng: -78.8784, lat: 42.8864, zoom: 12 };

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
function fmtMoney(n) {
  n = Number(n) || 0;
  if (n === 0) return "—";
  if (n >= 1_000_000_000) return `$${(n / 1_000_000_000).toFixed(1)}B`;
  if (n >= 1_000_000)     return `$${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000)         return `$${Math.round(n / 1_000)}K`;
  return `$${n}`;
}
function showPanel(html) {
  $("#panel-content").innerHTML = html;
  $("#panel").classList.remove("hidden");
  $("#reopen-panel").classList.add("hidden");
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
  if (state.map && state.map.getLayer("parcels-selected")) {
    state.map.setFilter("parcels-selected", ["==", "id", ""]);
  }
  if (location.hash) {
    history.replaceState(null, "", location.pathname + location.search);
  }
  renderLeaderboards();
}
function fullyHidePanel() {
  $("#panel").classList.add("hidden");
  $("#reopen-panel").classList.remove("hidden");
}

async function loadDossiers() {
  if (state.dossiers) return state.dossiers;
  try {
    const r = await fetch("data/dossiers.json");
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
  // Pure raster style — no Mapbox token needed
  const map = new maplibregl.Map({
    container: "map",
    style: {
      version: 8,
      sources: {
        osm: {
          type: "raster",
          tiles: ["https://tile.openstreetmap.org/{z}/{x}/{y}.png"],
          tileSize: 256,
          attribution: "© OpenStreetMap contributors",
        },
      },
      layers: [{ id: "osm", type: "raster", source: "osm" }],
    },
    center: [BUFFALO.lng, BUFFALO.lat],
    zoom: BUFFALO.zoom,
  });
  map.addControl(new maplibregl.NavigationControl(), "top-right");
  state.map = map;

  map.on("load", async () => {
    try {
      map.addSource("parcels", { type: "geojson", data: "data/properties.geojson" });

      // Build a circle layer at the centroid of each parcel polygon for fast render.
      // Color encodes concern_score; demolished parcels override.
      const colorExpr = [
        "case",
        ["==", ["get", "demolished"], true], "#b62324",
        [">=", ["get", "concern_score"], 11], "#f85149",
        [">=", ["get", "concern_score"], 5], "#f97316",
        [">=", ["get", "concern_score"], 1], "#facc15",
        "#475569",
      ];

      // Dim backdrop covers ALL parcels at constant opacity — toggled on
      // when the map filter is active.
      map.addLayer({
        id: "parcels-dim-fill",
        type: "fill",
        source: "parcels",
        paint: {
          "fill-color": "#0a0d12",
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
            13, 0,
            15, 0.35,
            18, 0.55,
          ],
        },
        filter: ["==", "$type", "Polygon"],
      });

      // Outline at high zoom
      map.addLayer({
        id: "parcels-outline",
        type: "line",
        source: "parcels",
        paint: {
          "line-color": "#0008",
          "line-width": 0.5,
          "line-opacity": [
            "interpolate", ["linear"], ["zoom"],
            14, 0, 16, 0.6,
          ],
        },
        filter: ["==", "$type", "Polygon"],
      });

      // Highlighted-parcel overlay — drawn on top of parcels-fill / dim layer.
      // Constant high opacity so the matched parcels stand out at every zoom.
      map.addLayer({
        id: "parcels-highlight-fill",
        type: "fill",
        source: "parcels",
        paint: {
          "fill-color": colorExpr,
          "fill-opacity": 0.95,
        },
        layout: { "visibility": "none" },
        filter: ["==", ["get", "owner_slug"], "__none__"],
      });
      map.addLayer({
        id: "parcels-highlight-outline",
        type: "line",
        source: "parcels",
        paint: { "line-color": "#fff", "line-width": 1.5, "line-opacity": 0.7 },
        layout: { "visibility": "none" },
        filter: ["==", ["get", "owner_slug"], "__none__"],
      });

      // Selected parcel highlight
      map.addLayer({
        id: "parcels-selected",
        type: "line",
        source: "parcels",
        paint: { "line-color": "#fb8500", "line-width": 3 },
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
  const violations = (dossier?.violations || []);
  const complaints = (dossier?.complaints || []);
  const owner = props.owner || "Owner not on record";
  const portfolioCta =
    props.portfolio_n > 1
      ? `<button class="cta" onclick="window.openPortfolio('${escapeHtml(props.owner_slug)}')">
           This owner has ${props.portfolio_n - 1} other propert${props.portfolio_n - 1 === 1 ? "y" : "ies"} →
         </button>`
      : "";

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

    <h3>Recent code violations (${violations.length})</h3>
    ${violations.length === 0
      ? `<p class="empty">No code violations on record.</p>`
      : `<ul class="violations">${violations.slice(0, 10).map(v => `
          <li>
            <div class="date">${fmtDate(v.date)} · ${escapeHtml(v.status || "")}</div>
            <div>${escapeHtml(v.description || v.code_section || "—")}</div>
          </li>`).join("")}</ul>`
    }

    <h3>Recent 311 housing complaints (${complaints.length})</h3>
    ${complaints.length === 0
      ? `<p class="empty">No housing-related 311 complaints in the last 18 months.</p>`
      : `<ul class="complaints">${complaints.slice(0, 10).map(c => `
          <li>
            <div class="date">${fmtDate(c.date)}</div>
            <div>${escapeHtml(c.subject || c.reason || c.type || "—")}</div>
          </li>`).join("")}</ul>`
    }

    <div class="disclaimer">
      Code violations and 311 complaints are public records. They describe specific
      facts about a property — they are not a verdict about any person.
    </div>
  `);
}

window.openPortfolio = async function (slug) {
  try {
    const r = await fetch(`data/owners/${slug}.json`);
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    const portfolio = await r.json();
    portfolio._slug = slug;  // attach slug for the highlight toggle
    state.lastPortfolio = portfolio;
    state.lastOperator = null;
    renderPortfolio(portfolio);
    location.hash = `#/owner/${encodeURIComponent(slug)}`;
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

  const rows = portfolio.properties.map(p => `
    <tr onclick="window.gotoParcel('${escapeHtml(p.id)}', ${p.lat}, ${p.lng})">
      <td>${escapeHtml(p.addr)}</td>
      <td class="num ${p.violations_open > 0 ? "bad" : ""}">${p.violations_open}</td>
      <td class="num ${p.complaints_311_12mo > 2 ? "warn" : ""}">${p.complaints_311_12mo}</td>
      <td class="num ${p.demolished ? "bad" : ""}">${p.demolished ? "✗" : ""}</td>
    </tr>
  `).join("");

  showPanel(`
    <h2>Owner Portfolio</h2>
    <div class="addr">${escapeHtml(portfolio.owner_display)}</div>
    ${variants}

    <div class="stat-grid">
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

    ${operatorCta}
    ${highlightBtn}

    <h3>Properties (sorted by concern score)</h3>
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
  setTimeout(() => selectParcel(id), 600);
};

// ---------- map filter (highlight an owner/operator's parcels) ----------
function _highlightedBbox(kind, slug) {
  // Returns [[minLng, minLat], [maxLng, maxLat]] from in-memory data.
  let pts = [];
  if (kind === "owner") {
    pts = state.addressIndex
      .filter(a => a.owner_slug === slug && a.lat && a.lng)
      .map(a => [a.lng, a.lat]);
  } else if (kind === "operator") {
    // The operator portfolio JSON is loaded by openOperator and holds lat/lng.
    // We stash it on state.lastOperator for bbox lookup; fall back to scanning
    // the address_index by joining owner_slugs in the operator (loaded ad-hoc).
    const op = state.lastOperator;
    if (op && op.operator_slug === slug) {
      pts = (op.properties || []).filter(p => p.lat && p.lng).map(p => [p.lng, p.lat]);
    }
  }
  if (pts.length === 0) return null;
  let minLng = pts[0][0], maxLng = pts[0][0], minLat = pts[0][1], maxLat = pts[0][1];
  for (const [lng, lat] of pts) {
    if (lng < minLng) minLng = lng;
    if (lng > maxLng) maxLng = lng;
    if (lat < minLat) minLat = lat;
    if (lat > maxLat) maxLat = lat;
  }
  return { bounds: [[minLng, minLat], [maxLng, maxLat]], count: pts.length };
}

function applyMapFilter(kind, slug, label) {
  if (!state.map || !state.map.getLayer("parcels-fill")) return;
  const expr = kind === "owner"
    ? ["==", ["get", "owner_slug"], slug]
    : ["==", ["get", "operator_slug"], slug];

  // Show dim backdrop over all parcels.
  state.map.setLayoutProperty("parcels-dim-fill", "visibility", "visible");

  // Show the bright highlight overlay only for matched parcels.
  state.map.setFilter("parcels-highlight-fill", expr);
  state.map.setFilter("parcels-highlight-outline", expr);
  state.map.setLayoutProperty("parcels-highlight-fill", "visibility", "visible");
  state.map.setLayoutProperty("parcels-highlight-outline", "visibility", "visible");

  // Existing colorful base layer stays unfiltered — its zoom-aware opacity
  // means it's invisible at low zoom and only adds detail when zoomed in,
  // which is fine.

  const bbox = _highlightedBbox(kind, slug);
  state.mapFilter = { kind, slug, label, count: bbox?.count ?? 0 };

  if (bbox) {
    state.map.fitBounds(bbox.bounds, { padding: 60, maxZoom: 17, duration: 700 });
  }
  updateFilterChip();
}

function clearMapFilter() {
  if (!state.map) return;
  if (state.map.getLayer("parcels-highlight-fill")) {
    state.map.setLayoutProperty("parcels-dim-fill", "visibility", "none");
    state.map.setLayoutProperty("parcels-highlight-fill", "visibility", "none");
    state.map.setLayoutProperty("parcels-highlight-outline", "visibility", "none");
    // Reset the highlight filter so re-show starts clean.
    state.map.setFilter("parcels-highlight-fill", ["==", ["get", "owner_slug"], "__none__"]);
    state.map.setFilter("parcels-highlight-outline", ["==", ["get", "owner_slug"], "__none__"]);
  }
  state.mapFilter = null;
  updateFilterChip();
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
  if (state.mapFilter && state.mapFilter.kind === kind && state.mapFilter.slug === slug) {
    clearMapFilter();
  } else {
    applyMapFilter(kind, slug, label);
  }
  // Re-render whichever panel is showing so the toggle reflects the new state.
  if (state.lastOperator) {
    renderOperator(state.lastOperator);
  } else if (state.lastPortfolio) {
    renderPortfolio(state.lastPortfolio);
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

function renderLeaderboards() {
  const isOperators = state.activeBoardKind === "operators";
  const data = isOperators ? state.topOperators : state.topOwners;
  if (!data) {
    showPanel(`<p class="empty">Loading leaderboards…</p>`);
    return;
  }
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
    return `
      <li class="${cls}" ${action}>
        <span class="rank">${i + 1}</span>
        <span class="name">${escapeHtml(display)}<span class="sub">${sub}</span></span>
        <span class="stat-num">${statValue}${active.statLabel ? ` <span class="sub" style="display:inline">${active.statLabel}</span>` : ""}</span>
      </li>`;
  }).join("");

  const kindToggle = `
    <div class="kind-toggle">
      <button class="${isOperators ? "active" : ""}" data-kind="operators">Operators (mailing-address clusters)</button>
      <button class="${!isOperators ? "active" : ""}" data-kind="owners">Owner names (raw)</button>
    </div>`;

  showPanel(`
    <h2>Top Landlords</h2>
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

  // Wire kind toggle, tabs, rows
  $$("#panel .kind-toggle button").forEach(btn => {
    btn.addEventListener("click", () => {
      state.activeBoardKind = btn.dataset.kind;
      renderLeaderboards();
    });
  });
  $$("#panel .tabs button").forEach(btn => {
    btn.addEventListener("click", () => {
      state.activeBoard = btn.dataset.board;
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

// ---------- operator view ----------
window.openOperator = async function (slug) {
  try {
    const r = await fetch(`data/operators/${slug}.json`);
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    const op = await r.json();
    state.lastOperator = op;
    state.lastPortfolio = null;
    renderOperator(op);
    location.hash = `#/operator/${encodeURIComponent(slug)}`;
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

  const ownersList = op.owners.map(o => `
    <li data-slug="${escapeHtml(o.slug)}">
      <span class="name">${escapeHtml(o.display)}<span class="sub">${o.properties} props · ${o.open} open · ${o.all_violations} all-time</span></span>
      <span class="stat-num">${o.open}</span>
    </li>
  `).join("");

  const propsRows = op.properties.slice(0, 200).map(p => `
    <tr onclick="window.gotoParcel('${escapeHtml(p.id)}', ${p.lat}, ${p.lng})">
      <td>${escapeHtml(p.addr)}</td>
      <td class="num ${p.violations_open > 0 ? "bad" : ""}">${p.violations_open}</td>
      <td class="num ${p.complaints_311_12mo > 2 ? "warn" : ""}">${p.complaints_311_12mo}</td>
      <td class="num ${p.demolished ? "bad" : ""}">${p.demolished ? "✗" : ""}</td>
    </tr>
  `).join("");

  showPanel(`
    <h2>Operator</h2>
    <div class="addr">${escapeHtml(op.operator_label)}</div>
    <p class="empty" style="margin:2px 0 12px;">Mailing address: <strong>${escapeHtml(op.mailing_address)}</strong></p>

    <div class="stat-grid">
      <div class="stat"><div class="num">${op.total_properties}</div><div class="label">Properties</div></div>
      <div class="stat ${op.total_open_violations > 50 ? "bad" : op.total_open_violations > 10 ? "warn" : ""}">
        <div class="num">${op.total_open_violations}</div><div class="label">Open violations</div>
      </div>
      <div class="stat"><div class="num">${op.total_all_violations}</div><div class="label">All-time violations</div></div>
      <div class="stat"><div class="num">${op.total_complaints_311_12mo}</div><div class="label">311 (12mo)</div></div>
      <div class="stat"><div class="num">${fmtMoney(op.total_value)}</div><div class="label">Portfolio value</div></div>
    </div>

    ${highlightBtn}

    <h3>Constituent LLCs (${op.owners.length})</h3>
    <ul class="leaderboard llc-list">${ownersList}</ul>

    <h3>Properties (top 200 by concern)</h3>
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
      state.map.once("idle", () => selectParcel(li.dataset.id));
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
    const r = await fetch("data/meta.json");
    state.meta = await r.json();
    const date = (state.meta.generated_at || "").slice(0, 10);
    const c311 = (state.meta.complaints_311_max_date || "").slice(0, 10);
    const c311Note = c311 ? ` · 311 data through ${c311}` : "";
    $("#meta-info").textContent =
      `Refreshed ${date} · ${state.meta.parcels.toLocaleString()} parcels · ${state.meta.owners.toLocaleString()} owners${c311Note}`;
  } catch {
    $("#meta-info").textContent = "Refresh date unknown";
  }
}

async function loadAddressIndex() {
  try {
    const r = await fetch("data/address_index.json");
    state.addressIndex = await r.json();
  } catch (e) {
    console.error("address index load failed", e);
    state.addressIndex = [];
  }
}

async function loadTopOwners() {
  try {
    const r = await fetch("data/top_owners.json");
    state.topOwners = await r.json();
  } catch (e) {
    console.error("top owners load failed", e);
    state.topOwners = { by_open_violations: [], by_all_violations: [], by_properties: [], by_complaints_311: [] };
  }
}

async function loadTopOperators() {
  try {
    const r = await fetch("data/top_operators.json");
    state.topOperators = await r.json();
  } catch (e) {
    console.error("top operators load failed", e);
    state.topOperators = { by_open_violations: [], by_all_violations: [], by_properties: [], by_complaints_311: [] };
  }
}

function setupHashRouting() {
  window.addEventListener("hashchange", () => {
    const m = location.hash.match(/^#\/parcel\/(.+)/);
    const o = location.hash.match(/^#\/owner\/(.+)/);
    const op = location.hash.match(/^#\/operator\/(.+)/);
    if (m && m[1] !== state.selectedId) {
      selectParcel(decodeURIComponent(m[1]));
    } else if (o) {
      window.openPortfolio(decodeURIComponent(o[1]));
    } else if (op) {
      window.openOperator(decodeURIComponent(op[1]));
    } else if (!location.hash) {
      hidePanel();
    }
  });
}

document.addEventListener("DOMContentLoaded", async () => {
  $("#filter-chip").addEventListener("click", clearMapFilter);
  $("#panel-close").addEventListener("click", () => {
    // If we're on the leaderboard view already, fully hide; otherwise return to leaderboards.
    if (!state.selectedId && !location.hash) {
      fullyHidePanel();
    } else {
      hidePanel();
    }
  });
  $("#reopen-panel").addEventListener("click", () => {
    renderLeaderboards();
  });
  initMap();
  setupSearch();
  setupHashRouting();
  await Promise.all([loadMeta(), loadAddressIndex(), loadTopOwners(), loadTopOperators()]);

  // Replay initial hash route after data load, otherwise show leaderboards.
  if (location.hash) {
    window.dispatchEvent(new HashChangeEvent("hashchange"));
  } else {
    renderLeaderboards();
  }
});
