const ROUTES = ["overview", "timing", "types", "outcomes", "map"];
const CAT_KEYS = {
  t: "Traffic",
  d: "Disturbance",
  p: "Patrol",
  r: "Property",
  a: "Alarms",
  w: "Welfare",
  s: "Suspicious",
  v: "Person",
  o: "Other",
};

const ink = "#1c2430";
const accent = "#1f4e79";
const muted = "#8a93a0";
const charts = {};
let map;
let mapLayer;
let selectedCell = null;
let mapReady = false;

const fmt = (n) => Number(n).toLocaleString("en-US");
const pct = (n, total) => `${((n / total) * 100).toFixed(1)}%`;

function monthLabel(ym) {
  const [y, m] = ym.split("-");
  const names = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
  return `${names[Number(m) - 1]} '${y.slice(2)}`;
}

function prettyDate(iso) {
  const [y, m, d] = iso.split("-").map(Number);
  return new Date(y, m - 1, d).toLocaleDateString("en-US", {
    weekday: "short",
    month: "short",
    day: "numeric",
    year: "numeric",
  });
}

function table(headers, rows) {
  const head = headers.map((h) => `<th>${h}</th>`).join("");
  const body = rows
    .map((row) => `<tr>${row.map((cell) => `<td>${cell}</td>`).join("")}</tr>`)
    .join("");
  return `<table><thead><tr>${head}</tr></thead><tbody>${body}</tbody></table>`;
}

function lineOrBar(id, type, labels, values, options = {}) {
  const ctx = document.getElementById(id);
  if (charts[id]) charts[id].destroy();
  charts[id] = new Chart(ctx, {
    type,
    data: {
      labels,
      datasets: [
        {
          label: options.label || "Calls",
          data: values,
          borderColor: accent,
          backgroundColor: type === "line" ? "rgba(31, 78, 121, 0.18)" : accent,
          fill: type === "line",
          tension: 0.2,
          pointRadius: type === "line" ? 0 : undefined,
        },
      ],
    },
    options: {
      responsive: true,
      plugins: {
        legend: { display: false },
        annotation: undefined,
      },
      indexAxis: options.horizontal ? "y" : "x",
      scales: {
        x: {
          ticks: { color: muted, maxRotation: 60, autoSkip: true },
          grid: { color: "#ece7df" },
        },
        y: {
          beginAtZero: !options.horizontal,
          ticks: { color: muted },
          grid: { color: "#ece7df" },
        },
      },
    },
  });
}

function renderOverview(s) {
  document.getElementById("overview-stats").innerHTML = [
    ["Total calls", fmt(s.total)],
    ["Average per day", s.avgPerDay],
    ["Call-type codes", fmt(s.uniqueTypes)],
    ["Distinct addresses", fmt(s.uniqueAddresses)],
  ]
    .map(([label, value]) => `<div class="stat"><strong>${value}</strong><span>${label}</span></div>`)
    .join("");

  const delta = s.janAug2026 - s.janAug2025;
  const deltaPct = ((delta / s.janAug2025) * 100).toFixed(1);
  document.getElementById("overview-callout").innerHTML = `
    <strong>2026 is running hotter than 2025</strong>
    January–August 2026 logged ${fmt(s.janAug2026)} calls, ${deltaPct}% above the
    same months in 2025 (${fmt(s.janAug2025)}). August 2026 is the busiest
    complete month (${fmt(s.months.values[s.months.labels.indexOf("2026-08")])}).
  `;

  if (charts["chart-month"]) charts["chart-month"].destroy();
  charts["chart-month"] = new Chart(document.getElementById("chart-month"), {
    type: "line",
    data: {
      labels: s.months.labels.map(monthLabel),
      datasets: [
        {
          label: "Calls",
          data: s.months.values,
          borderColor: accent,
          backgroundColor: "rgba(31, 78, 121, 0.18)",
          fill: true,
          tension: 0.2,
          pointRadius: 0,
        },
        {
          label: "Complete-month avg",
          data: s.months.labels.map(() => s.months.completeMonthAvg),
          borderColor: muted,
          borderDash: [6, 4],
          pointRadius: 0,
          fill: false,
        },
      ],
    },
    options: {
      responsive: true,
      plugins: { legend: { display: false } },
      scales: {
        x: { ticks: { color: muted, maxRotation: 60, autoSkip: true }, grid: { color: "#ece7df" } },
        y: { beginAtZero: true, ticks: { color: muted }, grid: { color: "#ece7df" } },
      },
    },
  });

  document.getElementById("busiest-table").innerHTML = table(
    ["Date", "Calls", "Note"],
    s.busiestDays.map((d) => [prettyDate(d.date), fmt(d.count), d.note || ""]),
  );
  document.getElementById("quietest-table").innerHTML = table(
    ["Date", "Calls"],
    s.quietestDays.map((d) => [prettyDate(d.date), fmt(d.count)]),
  );
}

function renderTiming(s) {
  lineOrBar("chart-dow", "bar", s.weekday.labels, s.weekday.values);
  lineOrBar("chart-hour", "line", s.hour.labels, s.hour.values);
}

function renderTypes(s) {
  const top = s.topTypes.slice(0, 12);
  lineOrBar(
    "chart-types",
    "bar",
    top.map((t) => t.label),
    top.map((t) => t.count),
    { horizontal: true },
  );
  document.getElementById("types-table").innerHTML = table(
    ["Final call type", "Calls", "Share"],
    s.topTypes.map((t) => [t.label, fmt(t.count), pct(t.count, s.total)]),
  );
  document.getElementById("crime-table").innerHTML = table(
    ["Grouped type", "Calls"],
    s.crimeGroups.map((t) => [t.label, fmt(t.count)]),
  );
  const alarms = s.alarms.business + s.alarms.residential;
  document.getElementById("alarm-stats").innerHTML = `
    <div class="stat"><strong>${fmt(s.alarms.business)}</strong><span>Business burglary alarms</span></div>
    <div class="stat" style="margin-top:12px"><strong>${fmt(s.alarms.residential)}</strong><span>Residential burglary alarms</span></div>
    <p class="caption">Alarm traffic (${fmt(alarms)}) is far larger than confirmed burglary reports in the grouped table.</p>
  `;
}

function renderOutcomes(s) {
  const top = s.cleared.slice(0, 8);
  const rest = s.cleared.slice(8).reduce((n, x) => n + x.count, 0);
  const pie = [...top, { label: "All other outcomes", count: rest }];
  const arrests = s.cleared.find((x) => x.label === "ARREST MADE")?.count || 0;
  const cited = s.cleared.find((x) => x.label === "CITED")?.count || 0;
  const reports = s.cleared.find((x) => x.label === "REPORT")?.count || 0;

  document.getElementById("outcome-stats").innerHTML = [
    [`${fmt(arrests)}`, `Arrests (${pct(arrests, s.total)})`],
    [`${fmt(cited)}`, `Cited (${pct(cited, s.total)})`],
    [`${fmt(reports)}`, `Reports taken (${pct(reports, s.total)})`],
    [s.cleared[0].label, `${pct(s.cleared[0].count, s.total)} of all calls`],
  ]
    .map(([value, label]) => `<div class="stat"><strong>${value}</strong><span>${label}</span></div>`)
    .join("");

  if (charts["chart-cleared"]) charts["chart-cleared"].destroy();
  charts["chart-cleared"] = new Chart(document.getElementById("chart-cleared"), {
    type: "doughnut",
    data: {
      labels: pie.map((x) => x.label),
      datasets: [
        {
          data: pie.map((x) => x.count),
          backgroundColor: [
            accent, "#3d6d99", "#6b7c8a", "#8a4b12", "#4f6f4f",
            "#8b2e2e", "#5b6573", "#9aa3ad", "#c5cdd6",
          ],
        },
      ],
    },
    options: {
      plugins: { legend: { position: "bottom", labels: { color: ink, boxWidth: 12 } } },
    },
  });

  document.getElementById("cleared-table").innerHTML = table(
    ["Cleared by", "Calls", "Share"],
    s.cleared.slice(0, 15).map((x) => [x.label, fmt(x.count), pct(x.count, s.total)]),
  );
}

function binValue(bin, year, cat, tod) {
  if (year === "all" && cat === "all" && tod === "all") return bin.n;
  let sum = 0;
  for (const key of Object.keys(bin)) {
    if (key === "x" || key === "y" || key === "n") continue;
    if (year !== "all" && key.slice(0, 2) !== year) continue;
    if (cat !== "all" && key[2] !== cat) continue;
    if (tod !== "all" && key[3] !== tod) continue;
    sum += bin[key];
  }
  return sum;
}

function nearestMark(lon, lat, marks) {
  let best = marks[0];
  let bestD = Infinity;
  for (const mark of marks) {
    const d = (mark.lon - lon) ** 2 + (mark.lat - lat) ** 2;
    if (d < bestD) {
      bestD = d;
      best = mark;
    }
  }
  if (!best || bestD > 0.01 ** 2) return `${lat.toFixed(3)}°, ${lon.toFixed(3)}°`;
  return `Near ${best.name}`;
}

function currentFilters() {
  return {
    year: document.querySelector("[data-filter=year].active")?.dataset.value || "all",
    cat: document.querySelector("[data-filter=cat].active")?.dataset.value || "all",
    tod: document.querySelector("[data-filter=tod].active")?.dataset.value || "all",
  };
}

function renderMapFilters() {
  const groups = [
    ["year", [["all", "All years"], ["24", "2024"], ["25", "2025"], ["26", "2026"]]],
    ["cat", [["all", "All types"], ...Object.entries(CAT_KEYS)]],
    ["tod", [["all", "Any hour"], ["D", "Day 6a–6p"], ["N", "Night"]]],
  ];
  document.getElementById("map-filters").innerHTML = groups
    .map(
      ([key, opts]) =>
        `<div class="filter-row">${opts
          .map(
            ([id, label], i) =>
              `<button type="button" data-filter="${key}" data-value="${id}" class="${i === 0 ? "active" : ""}">${label}</button>`,
          )
          .join("")}</div>`,
    )
    .join("");
}

function drawMap(mapData) {
  const { year, cat, tod } = currentFilters();
  const rows = mapData.c
    .map((bin) => ({ bin, v: binValue(bin, year, cat, tod) }))
    .filter((row) => row.v > 0)
    .sort((a, b) => a.v - b.v);
  const total = rows.reduce((n, r) => n + r.v, 0);
  const peak = rows.length ? rows[rows.length - 1].v : 1;
  const marks = mapData.l || [];

  document.getElementById("map-stats").innerHTML = [
    [fmt(total), "Calls in view"],
    [fmt(rows.length), "Cells with volume"],
    [fmt(peak), "Busiest cell"],
  ]
    .map(([value, label]) => `<div class="stat"><strong>${value}</strong><span>${label}</span></div>`)
    .join("");

  const top = [...rows].reverse().slice(0, 8);
  const selected = selectedCell
    ? rows.find((r) => r.bin.x === selectedCell.x && r.bin.y === selectedCell.y)
    : null;
  document.getElementById("map-side-title").textContent = selected
    ? "Selected cell"
    : "Hottest cells";
  document.getElementById("map-side").innerHTML = table(
    ["Area", "Calls"],
    (selected ? [selected, ...top.filter((r) => r !== selected)] : top)
      .slice(0, 8)
      .map((r) => [nearestMark(r.bin.x, r.bin.y, marks), fmt(r.v)]),
  );

  if (mapLayer) mapLayer.clearLayers();
  else mapLayer = L.layerGroup().addTo(map);

  for (const row of rows) {
    const r = 4 + Math.sqrt(row.v / peak) * 18;
    const marker = L.circleMarker([row.bin.y, row.bin.x], {
      radius: r,
      color: accent,
      weight: 1,
      fillColor: accent,
      fillOpacity: 0.45,
    }).bindTooltip(`${fmt(row.v)} calls · ${nearestMark(row.bin.x, row.bin.y, marks)}`);
    marker.on("click", () => {
      selectedCell = row.bin;
      drawMap(mapData);
    });
    mapLayer.addLayer(marker);
  }
}

function ensureMap(mapData) {
  if (!mapReady) {
    map = L.map("leaflet-map", { scrollWheelZoom: true }).setView([34.18, -118.325], 13);
    L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
      attribution: "&copy; OpenStreetMap",
      maxZoom: 18,
    }).addTo(map);
    if (mapData.p?.length) {
      const latlngs = mapData.p.map(([lon, lat]) => [lat, lon]);
      L.polygon(latlngs, {
        color: ink,
        weight: 1.4,
        fillColor: "#f0c14b",
        fillOpacity: 0.08,
      }).addTo(map);
    }
    for (const mark of mapData.l || []) {
      L.marker([mark.lat, mark.lon]).addTo(map).bindTooltip(mark.name, { permanent: true, direction: "right" });
    }
    mapReady = true;
  }
  drawMap(mapData);
  setTimeout(() => map.invalidateSize(), 50);
}

function showRoute(name, mapData) {
  const route = ROUTES.includes(name) ? name : "overview";
  for (const id of ROUTES) {
    document.getElementById(id).hidden = id !== route;
  }
  for (const link of document.querySelectorAll(".tabs a")) {
    link.classList.toggle("active", link.dataset.route === route);
  }
  if (route === "map") ensureMap(mapData);
}

async function main() {
  const [summary, mapData] = await Promise.all([
    fetch("./data/summary.json").then((r) => r.json()),
    fetch("./data/map.json").then((r) => r.json()),
  ]);

  document.getElementById("lede").textContent =
    `${fmt(summary.total)} incidents from ${prettyDate(summary.dateMin)} through ${prettyDate(summary.dateMax)}. ` +
    `Every calendar day in that span has at least one record.`;
  document.getElementById("footer-source").textContent =
    `Source: ${summary.source} · ${fmt(summary.total)} rows · ${fmt(summary.testCalls)} TEST CALL rows left in the totals`;
  document.getElementById("map-caption").textContent =
    `${fmt(mapData.m)} calls (95.2%) are mapped into ~350-meter cells. ` +
    `${fmt(mapData.u)} addresses could not be placed. Filters combine.`;

  renderOverview(summary);
  renderTiming(summary);
  renderTypes(summary);
  renderOutcomes(summary);
  renderMapFilters();

  document.getElementById("map-filters").addEventListener("click", (event) => {
    const btn = event.target.closest("button[data-filter]");
    if (!btn) return;
    for (const other of btn.parentElement.querySelectorAll("button")) {
      other.classList.toggle("active", other === btn);
    }
    if (mapReady) drawMap(mapData);
  });

  const apply = () => showRoute(location.hash.replace("#", ""), mapData);
  window.addEventListener("hashchange", apply);
  apply();
}

main();
