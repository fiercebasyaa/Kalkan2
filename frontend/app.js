const API_BASE = "";
const TELEGRAM_CHANNEL = "https://t.me/TurkAlertC";

// Zerion's chain ids are long, hyphenated slugs (e.g. "binance-smart-chain") —
// fine as an identifier, unreadable and prone to wrapping inside a small
// pill badge. Short display labels for the ones we actually see; anything
// not in this map just falls back to the raw id, still functional.
const CHAIN_LABELS = {
  ethereum: "ETH",
  "binance-smart-chain": "BSC",
  arbitrum: "Arbitrum",
  base: "Base",
  polygon: "Polygon",
  optimism: "Optimism",
  avalanche: "Avalanche",
  "zksync-era": "zkSync",
  blast: "Blast",
  scroll: "Scroll",
  "polygon-zkevm": "Polygon zkEVM",
};
function chainLabel(chain) {
  return CHAIN_LABELS[chain] || chain;
}

// ---------- i18n ----------
const DICTS = {};
let currentLang = localStorage.getItem("kalkan_lang") || "ru";

async function loadDicts() {
  // no-store: these dictionaries change often while iterating on the UI —
  // a browser-cached stale copy silently falls back to printing the raw
  // "reasons.some_code" key instead of real text, which looks like a bug
  // in the app rather than what it actually is (a stale cache).
  const langs = ["ru", "en", "tr"];
  const results = await Promise.all(
    langs.map((l) => fetch(`i18n/${l}.json`, { cache: "no-store" }).then((r) => r.json()))
  );
  langs.forEach((l, i) => (DICTS[l] = results[i]));
}

function resolve(dict, path) {
  return path.split(".").reduce((acc, key) => (acc && acc[key] !== undefined ? acc[key] : undefined), dict);
}

function t(path, params) {
  let str = resolve(DICTS[currentLang], path) ?? resolve(DICTS.ru, path) ?? path;
  if (params) {
    for (const [k, v] of Object.entries(params)) {
      str = str.replaceAll(`{${k}}`, v);
    }
  }
  return str;
}

function applyStaticTranslations() {
  document.documentElement.lang = currentLang;
  document.querySelectorAll("[data-i18n]").forEach((el) => {
    if (el.hasAttribute("data-i18n-params")) return; // filled dynamically elsewhere
    el.textContent = t(el.getAttribute("data-i18n"));
  });
  document.querySelectorAll("[data-i18n-placeholder]").forEach((el) => {
    el.placeholder = t(el.getAttribute("data-i18n-placeholder"));
  });
  document.getElementById("lang-current").textContent = currentLang.toUpperCase();
  refreshDynamicText();
}

function setLang(lang) {
  currentLang = lang;
  localStorage.setItem("kalkan_lang", lang);
  applyStaticTranslations();
}

document.getElementById("lang-current").addEventListener("click", () => {
  document.getElementById("lang-menu").classList.toggle("open");
});
document.querySelectorAll("#lang-menu button").forEach((btn) => {
  btn.addEventListener("click", () => {
    setLang(btn.dataset.lang);
    document.getElementById("lang-menu").classList.remove("open");
  });
});
document.addEventListener("click", (e) => {
  if (!document.getElementById("lang-switch").contains(e.target)) {
    document.getElementById("lang-menu").classList.remove("open");
  }
});

// Explicit locale everywhere numbers are shown — relying on the browser's
// ambient locale (toLocaleString() with no args) made figures look
// different, and sometimes just wrong, depending on the visitor's OS
// settings: e.g. under a tr-TR/ru-RU locale, "," is the DECIMAL separator,
// so $54.55 rendered as "$54,369"-looking nonsense and a $18B total grew
// three pointless decimal places. Numbers now always use en-US grouping
// regardless of UI language — that's the universal convention for USD
// figures — with fraction digits capped based on magnitude.
function fmtUsd(n) {
  if (n == null) return null;
  const digits = Math.abs(n) >= 1000 ? 0 : 2;
  return "$" + Number(n).toLocaleString("en-US", { maximumFractionDigits: digits });
}
function fmtNum(n, maxDigits = 6) {
  if (n == null) return null;
  const digits = Math.abs(n) >= 1000 ? 0 : maxDigits;
  return Number(n).toLocaleString("en-US", { maximumFractionDigits: digits });
}

function renderReason(reason) {
  const params = { ...reason.params };
  if (typeof params.balance === "number") params.balance = fmtNum(params.balance);
  ["prev", "curr"].forEach((k) => {
    if (typeof params[k] === "number") params[k] = fmtUsd(params[k]).slice(1);
  });
  return t(`reasons.${reason.code}`, params);
}

// values that depend on live data, re-rendered whenever the language
// changes too — otherwise switching language leaves already-rendered
// dynamic content (watchlist cards, the address report) stuck in
// whatever language was active when they were first drawn.
let lastStats = null;
let lastHealth = null;
let lastReportData = null;
let lastWatchlistEntries = null;
function refreshDynamicText() {
  if (lastReportData) renderReport(lastReportData);
  if (lastWatchlistEntries) renderWatchlist(lastWatchlistEntries);
  if (lastHealth) {
    const n = Object.values(lastHealth.quicknode_networks).filter((v) => v === "configured").length;
    document.getElementById("live-badge-text").textContent = t("hero.liveBadge", { chains: n });
    document.getElementById("supported-label").textContent = t("hero.supportedLabel", { n });
  }
  document.getElementById("footer-copyright").textContent = t("footer.copyright", { year: new Date().getFullYear() });
}

// ---------- header links ----------
document.getElementById("telegram-cta").href = TELEGRAM_CHANNEL;
document.getElementById("telegram-banner-cta").href = TELEGRAM_CHANNEL;
document.getElementById("footer-telegram").href = TELEGRAM_CHANNEL;

// ---------- stats + health ----------
async function loadStatsAndHealth() {
  try {
    const [stats, health] = await Promise.all([
      fetch(`${API_BASE}/api/stats`).then((r) => r.json()),
      fetch(`${API_BASE}/api/health`).then((r) => r.json()),
    ]);
    lastStats = stats;
    lastHealth = health;
    document.getElementById("stat-checks").textContent = stats.checks_today;
    document.getElementById("stat-platforms").textContent = stats.platforms_monitored;
    document.getElementById("stat-langs").textContent = stats.languages;
    refreshDynamicText();
  } catch (err) {
    console.warn("stats/health load failed", err);
  }
}

// ---------- address check ----------
const form = document.getElementById("address-form");
const input = document.getElementById("address-input");
const errorEl = document.getElementById("form-error");
const reportEl = document.getElementById("report");
let flowNetwork = null;

form.addEventListener("submit", async (e) => {
  e.preventDefault();
  const address = input.value.trim();
  errorEl.classList.add("hidden");
  if (!/^0x[a-fA-F0-9]{40}$/.test(address)) {
    errorEl.textContent = t("report.invalidAddress");
    errorEl.classList.remove("hidden");
    return;
  }

  const btn = form.querySelector("button");
  const btnLabel = btn.querySelector("span[data-i18n]");
  btn.disabled = true;
  btnLabel.textContent = t("hero.searchButtonLoading");
  try {
    const res = await fetch(`${API_BASE}/api/address/${address}`);
    if (!res.ok) {
      const body = await res.json().catch(() => ({}));
      throw new Error(body.detail || `Error ${res.status}`);
    }
    const data = await res.json();
    renderReport(data);
    loadStatsAndHealth();
    reportEl.scrollIntoView({ behavior: "smooth", block: "start" });
  } catch (err) {
    errorEl.textContent = err.message;
    errorEl.classList.remove("hidden");
    reportEl.classList.add("hidden");
  } finally {
    btn.disabled = false;
    btnLabel.textContent = t("hero.searchButton");
  }
});

function renderReport(data) {
  lastReportData = data;
  reportEl.classList.remove("hidden");

  const dot = document.getElementById("risk-dot");
  dot.className = "risk-dot " + data.risk.level;
  document.getElementById("risk-score").textContent = data.risk.score;
  document.getElementById("risk-level-label").textContent = t(
    { green: "report.riskGreen", yellow: "report.riskYellow", red: "report.riskRed", unknown: "report.riskUnknown" }[
      data.risk.level
    ]
  );

  const reasons = document.getElementById("risk-reasons");
  reasons.innerHTML = "";
  data.risk.reasons.forEach((r) => {
    const li = document.createElement("li");
    li.textContent = renderReason(r);
    reasons.appendChild(li);
  });

  document.getElementById("portfolio-total").textContent =
    data.portfolio.total_usd_value != null ? fmtUsd(data.portfolio.total_usd_value) : t("report.portfolioEmpty");
  document.getElementById("portfolio-source").textContent = t("report.portfolioSource", { source: data.portfolio.source });

  const tbody = document.querySelector("#portfolio-table tbody");
  tbody.innerHTML = "";
  data.portfolio.tokens.forEach((tk) => {
    const tr = document.createElement("tr");
    // Same symbol can appear multiple times — one row per (asset, chain),
    // e.g. ETH held on both mainnet and Base are separate real balances,
    // not a duplicate. Tag the chain so that reads as distinct, not broken.
    const chainTag = tk.chain ? `<span class="chain-tag">${chainLabel(tk.chain)}</span>` : "";
    tr.innerHTML = `<td>${tk.symbol} ${chainTag}</td><td>${fmtNum(tk.quantity)}</td><td>${
      tk.usd_value != null ? fmtUsd(tk.usd_value) : "—"
    }</td>`;
    tbody.appendChild(tr);
  });

  const flagsList = document.getElementById("flags-list");
  flagsList.innerHTML = "";
  if (data.flags.length === 0) {
    const li = document.createElement("li");
    li.className = "muted";
    li.textContent = t("report.flagsEmpty");
    flagsList.appendChild(li);
  } else {
    data.flags.forEach((f) => {
      const li = document.createElement("li");
      li.className = "flag-item " + (f.severity === "low" ? "sev-low" : "");
      // Repeating the same address on every card is pure noise when it's
      // a direct flag on the address being checked (the common case) —
      // only show it when it's actually new information: a counterparty.
      const isDirect = f.address.toLowerCase() === data.address.toLowerCase();
      const addrLine = isDirect ? "" : `<div class="muted">${short(f.address)}</div>`;
      li.innerHTML = `<div class="flag-source">${f.source} · ${f.severity}</div>${f.label}${addrLine}`;
      flagsList.appendChild(li);
    });
  }

  const txBody = document.querySelector("#tx-table tbody");
  txBody.innerHTML = "";
  data.recent_transactions.forEach((tx) => {
    const dirLabel = { in: t("report.dirIn"), out: t("report.dirOut") }[tx.direction] || t("report.dirUnknown");
    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td>${tx.hash.slice(0, 10)}...</td>
      <td class="dir-${tx.direction}">${dirLabel}</td>
      <td>${tx.counterparty ? tx.counterparty.slice(0, 10) + "..." : "—"}</td>
      <td>${tx.value_usd != null ? fmtUsd(tx.value_usd) : "—"}</td>
      <td>${tx.asset || "—"}</td>`;
    txBody.appendChild(tr);
  });

  renderFlowGraph(data);

  const warningsEl = document.getElementById("warnings");
  if (data.warnings.length) {
    warningsEl.classList.remove("hidden");
    warningsEl.innerHTML = data.warnings.map((w) => `<div>⚠ ${renderReason(w)}</div>`).join("");
  } else {
    warningsEl.classList.add("hidden");
  }

  document.getElementById("export-json").onclick = () =>
    window.open(`${API_BASE}/api/address/${data.address}/export?format=json`, "_blank");
  document.getElementById("export-csv").onclick = () =>
    window.open(`${API_BASE}/api/address/${data.address}/export?format=csv`, "_blank");
}

function renderFlowGraph(data) {
  const nodes = [{ id: data.address, label: short(data.address), color: "#2dd4c8", font: { color: "#04141a" } }];
  const edges = [];
  const seen = new Set([data.address.toLowerCase()]);
  const flaggedAddrs = new Set(data.flags.map((f) => f.address.toLowerCase()));

  data.recent_transactions.forEach((tx) => {
    if (!tx.counterparty) return;
    const cp = tx.counterparty;
    if (!seen.has(cp.toLowerCase())) {
      seen.add(cp.toLowerCase());
      nodes.push({
        id: cp,
        label: short(cp),
        color: flaggedAddrs.has(cp.toLowerCase()) ? "#ef4a5a" : "#1c2b42",
        font: { color: "#e9eefb" },
      });
    }
    edges.push({
      from: tx.direction === "out" ? data.address : cp,
      to: tx.direction === "out" ? cp : data.address,
      arrows: "to",
      color: { color: "#2a3a54" },
    });
  });

  const container = document.getElementById("flow-graph");
  // Force a synchronous reflow before vis-network measures the container.
  // reportEl.classList.remove("hidden") ran earlier in the same tick — the
  // browser hasn't necessarily recalculated layout yet, so without this
  // vis-network can measure a stale/zero height, size its canvas too
  // small, and never learn the container is actually 360px tall. Result:
  // nodes clustered in a shrunk viewport at the top, dead space below.
  void container.offsetHeight;
  const graphData = { nodes: new vis.DataSet(nodes), edges: new vis.DataSet(edges) };
  const options = {
    physics: {
      stabilization: true,
      barnesHut: { gravitationalConstant: -4000, springLength: 160, springConstant: 0.03 },
    },
    interaction: { hover: true },
    nodes: { shape: "dot", size: 16, borderWidth: 0 },
  };
  if (flowNetwork) flowNetwork.destroy();
  flowNetwork = new vis.Network(container, graphData, options);
  // The container-sizing fix above wasn't the whole story: vis-network's
  // fit() defaults to maxZoomLevel: 1 — it will center a small node
  // cluster in the canvas but refuses to zoom in past 1:1 scale to make
  // it fill more of the space. With few nodes settled close together
  // that's most of the card left empty no matter how correctly the
  // container is sized. Raising maxZoomLevel is the actual fix.
  const fit = () => flowNetwork.fit({ maxZoomLevel: 4, animation: false });
  flowNetwork.once("stabilizationIterationsDone", fit);
  fit();
}

function short(addr) {
  return addr.slice(0, 6) + "…" + addr.slice(-4);
}

// ---------- watchlist ----------
const watchlistGrid = document.getElementById("watchlist-cards");
document.getElementById("watchlist-refresh").addEventListener("click", async () => {
  await fetch(`${API_BASE}/api/watchlist/poll`, { method: "POST" });
  loadWatchlist();
});

async function loadWatchlist() {
  try {
    const res = await fetch(`${API_BASE}/api/watchlist`);
    const entries = await res.json();
    renderWatchlist(entries);
  } catch (err) {
    watchlistGrid.innerHTML = `<p class="error">${err.message}</p>`;
  }
}

function renderWatchlist(entries) {
  lastWatchlistEntries = entries;
  document.getElementById("stat-alerts").textContent = entries.filter((e) => e.alert_active).length;
  watchlistGrid.innerHTML = "";
  if (entries.length === 0) {
    watchlistGrid.innerHTML = `<p class="muted">${t("watchlistSection.empty")}</p>`;
    return;
  }

  entries.forEach((e, idx) => {
    const statusClass = e.alert_active ? "risk" : e.change_24h_pct != null && e.change_24h_pct < 0 ? "watch" : "stable";
    const statusText = { risk: t("watchlistSection.statusRisk"), watch: t("watchlistSection.statusWatch"), stable: t("watchlistSection.statusStable") }[
      statusClass
    ];

    const card = document.createElement("div");
    card.className = "watchlist-card" + (e.alert_active ? " alert" : "");
    card.innerHTML = `
      <div class="wc-header">
        <span class="wc-label">${e.label}</span>
        <span class="wc-status ${statusClass}">${statusText}</span>
      </div>
      <div class="wc-address">${e.address}</div>
      <div class="wc-value">${
        e.portfolio.total_usd_value != null ? fmtUsd(e.portfolio.total_usd_value) : t("report.portfolioEmpty")
      }</div>
      <canvas id="wc-chart-${idx}"></canvas>
      ${e.alert_active && e.alert_reason ? `<div class="wc-alert-banner">⚠ ${renderReason(e.alert_reason)}</div>` : ""}
    `;
    watchlistGrid.appendChild(card);

    const ctx = card.querySelector(`#wc-chart-${idx}`);
    new Chart(ctx, {
      type: "line",
      data: {
        labels: e.history.map((h) => new Date(h.timestamp).toLocaleTimeString()),
        datasets: [
          {
            data: e.history.map((h) => h.total_usd_value),
            borderColor: "#2dd4c8",
            backgroundColor: "rgba(45,212,200,0.15)",
            tension: 0.3,
            fill: true,
            pointRadius: 0,
          },
        ],
      },
      options: {
        plugins: { legend: { display: false } },
        scales: { x: { display: false }, y: { display: false } },
      },
    });
  });
}

// ---------- init ----------
(async function init() {
  await loadDicts();
  applyStaticTranslations();
  await loadStatsAndHealth();
  await loadWatchlist();
})();
