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
  selectedId: null,
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
function showPanel(html) {
  $("#panel-content").innerHTML = html;
  $("#panel").classList.remove("hidden");
}
function hidePanel() {
  $("#panel").classList.add("hidden");
  state.selectedId = null;
  if (state.map && state.map.getLayer("parcels-selected")) {
    state.map.setFilter("parcels-selected", ["==", "id", ""]);
  }
  if (location.hash) location.hash = "";
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
    </div>

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

function setupHashRouting() {
  window.addEventListener("hashchange", () => {
    const m = location.hash.match(/^#\/parcel\/(.+)/);
    const o = location.hash.match(/^#\/owner\/(.+)/);
    if (m && m[1] !== state.selectedId) {
      selectParcel(decodeURIComponent(m[1]));
    } else if (o) {
      window.openPortfolio(decodeURIComponent(o[1]));
    } else if (!location.hash) {
      hidePanel();
    }
  });
}

document.addEventListener("DOMContentLoaded", async () => {
  $("#panel-close").addEventListener("click", hidePanel);
  initMap();
  setupSearch();
  setupHashRouting();
  await Promise.all([loadMeta(), loadAddressIndex()]);

  // Replay initial hash route after data load
  if (location.hash) {
    window.dispatchEvent(new HashChangeEvent("hashchange"));
  }
});
