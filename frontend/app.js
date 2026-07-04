const chartRegistry = new Map();

const nf0 = new Intl.NumberFormat("en-US", { maximumFractionDigits: 0 });
const nf1 = new Intl.NumberFormat("en-US", { minimumFractionDigits: 1, maximumFractionDigits: 1 });
const nf2 = new Intl.NumberFormat("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });

function $(id) {
  return document.getElementById(id);
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

async function fetchJson(url, options = {}) {
  const response = await fetch(url, {
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
    ...options,
  });
  if (!response.ok) {
    const text = await response.text();
    throw new Error(`${response.status} ${response.statusText}${text ? ` — ${text}` : ""}`);
  }
  return response.json();
}

function setInlineError(container, message) {
  container.innerHTML = `<div class="inline-error">${escapeHtml(message)}</div>`;
}

function destroyChart(id) {
  const existing = chartRegistry.get(id);
  if (existing) {
    existing.destroy();
    chartRegistry.delete(id);
  }
}

function createChart(id, config) {
  destroyChart(id);
  const canvas = $(id);
  chartRegistry.set(id, new Chart(canvas, config));
}

function formatCurrency(value) {
  return `$${nf2.format(value)}`;
}

function formatPercent(value) {
  return `${nf1.format(value)}%`;
}

function formatDateTime(value) {
  return new Date(value).toLocaleString([], { dateStyle: "medium", timeStyle: "short" });
}

function renderKpis(kpis) {
  const items = [
    ["Total kWh", `${nf0.format(kpis.total_kwh)} kWh`, `Across ${kpis.meter_count} meters`],
    ["Total cost", formatCurrency(kpis.total_cost_usd), `Estimated utility spend`],
    ["Total CO₂", `${nf0.format(kpis.total_co2_kg)} kg`, `Carbon emissions`],
    ["Peak demand", `${nf1.format(kpis.peak_demand_kw)} kWh`, formatDateTime(kpis.peak_demand_timestamp)],
    ["Renewable share", formatPercent(kpis.renewable_share_pct), `Renewables in mix`],
    ["Meter count", nf0.format(kpis.meter_count), `Active smart meters`],
  ];

  $("kpi-grid").innerHTML = items
    .map(
      ([label, value, sub]) => `
        <article class="card kpi-card">
          <div class="kpi-label">${escapeHtml(label)}</div>
          <div class="kpi-value">${escapeHtml(value)}</div>
          <div class="kpi-sub">${escapeHtml(sub)}</div>
        </article>`,
    )
    .join("");
}

function renderLabelValues(items, labelKey = "name", valueKey = "kwh") {
  return items.map((item) => item[labelKey] ?? item[0] ?? item).join(", ");
}

function renderConsumptionChart(items) {
  createChart("consumption-time-chart", {
    type: "line",
    data: {
      labels: items.map((item) => new Date(item.timestamp).toLocaleDateString([], { month: "short", day: "numeric" })),
      datasets: [
        {
          label: "kWh",
          data: items.map((item) => item.kwh),
          borderColor: "#62d0ff",
          backgroundColor: "rgba(98, 208, 255, 0.12)",
          tension: 0.32,
          fill: true,
          pointRadius: 0,
        },
        {
          label: "Renewable kWh",
          data: items.map((item) => item.renewable_kwh),
          borderColor: "#4ade80",
          backgroundColor: "rgba(74, 222, 128, 0.12)",
          tension: 0.32,
          fill: true,
          pointRadius: 0,
        },
      ],
    },
    options: chartOptions(true),
  });
}

function renderSectorChart(items) {
  createChart("sector-chart", {
    type: "doughnut",
    data: {
      labels: items.map((item) => item.name),
      datasets: [
        {
          data: items.map((item) => item.kwh),
          backgroundColor: ["#62d0ff", "#8b5cf6", "#4ade80", "#fbbf24", "#fb7185"],
          borderWidth: 0,
        },
      ],
    },
    options: chartOptions(false, false),
  });
}

function renderZoneChart(items) {
  createChart("zone-chart", {
    type: "bar",
    data: {
      labels: items.map((item) => item.name),
      datasets: [
        {
          label: "kWh",
          data: items.map((item) => item.kwh),
          backgroundColor: "rgba(139, 92, 246, 0.7)",
          borderRadius: 10,
        },
      ],
    },
    options: chartOptions(false),
  });
}

function renderLoadProfile(items) {
  createChart("load-profile-chart", {
    type: "line",
    data: {
      labels: items.map((item) => item.hour),
      datasets: [
        {
          label: "Avg kWh",
          data: items.map((item) => item.avg_kwh),
          borderColor: "#fbbf24",
          backgroundColor: "rgba(251, 191, 36, 0.12)",
          tension: 0.32,
          fill: true,
          pointRadius: 0,
        },
      ],
    },
    options: chartOptions(true, false),
  });
}

function renderForecast(result) {
  const history = result.history || [];
  const forecast = result.forecast || [];
  const labels = [
    ...history.map((item) => new Date(item.timestamp).toLocaleDateString([], { month: "short", day: "numeric" })),
    ...forecast.map((item) => new Date(item.timestamp).toLocaleDateString([], { month: "short", day: "numeric" })),
  ];
  const historyValues = [...history.map((item) => item.kwh), ...Array(forecast.length).fill(null)];
  const forecastValues = [...Array(history.length).fill(null), ...forecast.map((item) => item.kwh_pred)];
  const lowerValues = [...Array(history.length).fill(null), ...forecast.map((item) => item.lower)];
  const upperValues = [...Array(history.length).fill(null), ...forecast.map((item) => item.upper)];

  createChart("forecast-chart", {
    type: "line",
    data: {
      labels,
      datasets: [
        {
          label: "History",
          data: historyValues,
          borderColor: "#94a3b8",
          backgroundColor: "rgba(148, 163, 184, 0.08)",
          tension: 0.25,
          pointRadius: 0,
        },
        {
          label: "Forecast",
          data: forecastValues,
          borderColor: "#62d0ff",
          backgroundColor: "rgba(98, 208, 255, 0.12)",
          tension: 0.25,
          pointRadius: 0,
        },
        {
          label: "Lower",
          data: lowerValues,
          borderColor: "rgba(98, 208, 255, 0.0)",
          backgroundColor: "rgba(98, 208, 255, 0.08)",
          pointRadius: 0,
          fill: "+1",
        },
        {
          label: "Upper",
          data: upperValues,
          borderColor: "rgba(98, 208, 255, 0.0)",
          backgroundColor: "rgba(98, 208, 255, 0.08)",
          pointRadius: 0,
        },
      ],
    },
    options: chartOptions(true),
  });

  $("forecast-metrics").innerHTML = `
    <span class="metric-pill">MAE ${nf2.format(result.metrics?.mae ?? 0)}</span>
    <span class="metric-pill">MAPE ${nf1.format(result.metrics?.mape ?? 0)}%</span>
    <span class="metric-pill">Horizon ${forecast.length} hrs</span>
  `;
}

function renderAnomalies(items) {
  const rows = items
    .map((item) => {
      const severityClass = item.severity >= 8 ? "severity-high" : item.severity >= 4 ? "severity-med" : "severity-low";
      return `
        <tr>
          <td>${escapeHtml(item.meter_id)}</td>
          <td>${escapeHtml(item.sector)}</td>
          <td>${escapeHtml(item.zone)}</td>
          <td>${escapeHtml(formatDateTime(item.timestamp))}</td>
          <td>${nf2.format(item.energy_kwh)}</td>
          <td>${nf2.format(item.expected_kwh)}</td>
          <td>${nf2.format(item.deviation)}</td>
          <td class="${severityClass}">${nf2.format(item.severity)}</td>
        </tr>`;
    })
    .join("");

  $("anomalies-table").innerHTML = `
    <table>
      <thead>
        <tr>
          <th>Meter</th><th>Sector</th><th>Zone</th><th>Timestamp</th><th>Energy</th><th>Expected</th><th>Deviation</th><th>Severity</th>
        </tr>
      </thead>
      <tbody>${rows}</tbody>
    </table>`;
}

function renderRecommendations(items) {
  $("recommendations-list").innerHTML = items
    .map(
      (item) => `
      <article class="rec-card">
        <div class="rec-title">${escapeHtml(item.title)}</div>
        <div class="rec-meta">
          <span class="pill ${item.impact === "High" ? "bad" : item.impact === "Medium" ? "warn" : "good"}">${escapeHtml(item.category)}</span>
          <span class="pill">${escapeHtml(item.impact)} priority ${escapeHtml(item.priority)}</span>
          <span class="pill">${nf0.format(item.est_savings_kwh)} kWh</span>
          <span class="pill">${formatCurrency(item.est_savings_usd)}</span>
        </div>
        <div class="muted">${escapeHtml(item.detail)}</div>
        ${item.narrative ? `<div class="status" style="margin-top:8px;">${escapeHtml(item.narrative)}</div>` : ""}
      </article>`,
    )
    .join("");
}

function renderMeta(meta) {
  $("llm-badge").textContent = `LLM: ${meta.llm_provider}`;
  $("date-range").textContent = `${formatDateTime(meta.date_range.start)} → ${formatDateTime(meta.date_range.end)}`;
}

function renderApiError(containerId, message) {
  const el = $(containerId);
  if (el) setInlineError(el, message);
}

function chartOptions(showX = true, showLegend = true) {
  return {
    responsive: true,
    maintainAspectRatio: false,
    plugins: {
      legend: { display: showLegend, labels: { color: "#d7e4f5" } },
      tooltip: { mode: "index", intersect: false },
    },
    scales: showX
      ? {
          x: { ticks: { color: "#9fb2cc" }, grid: { color: "rgba(148, 163, 184, 0.08)" } },
          y: { ticks: { color: "#9fb2cc" }, grid: { color: "rgba(148, 163, 184, 0.08)" } },
        }
      : {
          y: { ticks: { color: "#9fb2cc" }, grid: { color: "rgba(148, 163, 184, 0.08)" } },
        },
  };
}

async function loadDashboard() {
  try {
    const meta = await fetchJson("/api/meta");
    renderMeta(meta);
  } catch (error) {
    renderApiError("llm-badge", `LLM unavailable: ${error.message}`);
  }

  const dataLoaders = [
    {
      promise: fetchJson("/api/overview"),
      onSuccess: (body) => {
        renderKpis(body.kpis);
        renderSectorChart(body.by_sector);
        renderZoneChart(body.by_zone);
      },
      errorTarget: "kpi-grid",
    },
    {
      promise: fetchJson("/api/timeseries?freq=D"),
      onSuccess: (body) => renderConsumptionChart(body.items),
      errorTarget: "consumption-time-chart",
    },
    {
      promise: fetchJson("/api/load-profile"),
      onSuccess: (body) => renderLoadProfile(body.items),
      errorTarget: "load-profile-chart",
    },
    {
      promise: fetchJson("/api/forecast?horizon=168"),
      onSuccess: (body) => renderForecast(body),
      errorTarget: "forecast-chart",
    },
    {
      promise: fetchJson("/api/anomalies?limit=15"),
      onSuccess: (body) => renderAnomalies(body.items),
      errorTarget: "anomalies-table",
    },
    {
      promise: fetchJson("/api/recommendations"),
      onSuccess: (body) => renderRecommendations(body.items),
      errorTarget: "recommendations-list",
    },
  ];

  await Promise.all(
    dataLoaders.map((item) =>
      item.promise.catch((error) => {
        renderApiError(item.errorTarget, error.message);
      }).then((body) => {
        if (body) item.onSuccess(body);
      }),
    ),
  );
}

function renderAskData(data) {
  const container = $("ask-data");
  if (!data || typeof data !== "object") {
    container.innerHTML = `<div class="muted">No structured data returned.</div>`;
    return;
  }

  const entries = Object.entries(data);
  if (!entries.length) {
    container.innerHTML = `<div class="muted">No structured data returned.</div>`;
    return;
  }

  const rows = entries
    .map(([key, value]) => {
      let rendered = "";
      if (Array.isArray(value)) {
        if (value.length && typeof value[0] === "object") {
          rendered = `
            <table>
              <thead><tr>${Object.keys(value[0]).map((field) => `<th>${escapeHtml(field)}</th>`).join("")}</tr></thead>
              <tbody>
                ${value
                  .slice(0, 8)
                  .map(
                    (row) =>
                      `<tr>${Object.values(row)
                        .map((cell) => `<td>${escapeHtml(typeof cell === "number" ? nf2.format(cell) : cell)}</td>`)
                        .join("")}</tr>`,
                  )
                  .join("")}
              </tbody>
            </table>`;
        } else {
          rendered = escapeHtml(value.map((item) => (typeof item === "object" ? JSON.stringify(item) : item)).join(", "));
        }
      } else if (value && typeof value === "object") {
        rendered = `<pre>${escapeHtml(JSON.stringify(value, null, 2))}</pre>`;
      } else {
        rendered = escapeHtml(typeof value === "number" ? nf2.format(value) : String(value));
      }
      return `<tr><th>${escapeHtml(key)}</th><td>${rendered}</td></tr>`;
    })
    .join("");

  container.innerHTML = `<table><tbody>${rows}</tbody></table>`;
}

function renderAskChart(chart) {
  const container = $("ask-chart");
  destroyChart("ask-chart");
  if (!chart || !chart.series) {
    container.getContext("2d").clearRect(0, 0, container.width, container.height);
    return;
  }

  const series = chart.series || [];
  const labels = series.map((item, index) => item.timestamp || item.hour || item.name || index);
  const numericKeys = Object.keys(series[0] || {}).filter((key) => key !== "timestamp" && key !== "hour" && key !== "name");
  const datasets = numericKeys.slice(0, 3).map((key, index) => ({
    label: key,
    data: series.map((item) => item[key]),
    borderColor: ["#62d0ff", "#4ade80", "#fbbf24"][index],
    backgroundColor: "transparent",
    tension: 0.3,
    pointRadius: 0,
  }));

  chartRegistry.set(
    "ask-chart",
    new Chart(container, {
      type: chart.type === "bar" ? "bar" : "line",
      data: { labels, datasets },
      options: chartOptions(true, true),
    }),
  );
}

async function askQuestion(question) {
  $("ask-status").textContent = "Thinking...";
  $("ask-button").disabled = true;
  $("ask-answer").classList.remove("error-box");
  $("ask-answer").textContent = "";
  $("ask-data").innerHTML = "";
  destroyChart("ask-chart");

  try {
    const body = await fetchJson("/api/ask", {
      method: "POST",
      body: JSON.stringify({ question }),
    });
    $("ask-status").textContent = `Intent: ${body.intent}`;
    $("ask-answer").textContent = body.answer;
    renderAskData(body.data);
    renderAskChart(body.chart);
  } catch (error) {
    $("ask-status").textContent = "Request failed";
    $("ask-answer").classList.add("error-box");
    $("ask-answer").textContent = error.message;
  } finally {
    $("ask-button").disabled = false;
  }
}

function initAskPanel() {
  const examples = [
    "What is the total energy overview?",
    "Which sector uses the most energy?",
    "Show anomalies and unusual spikes.",
    "Forecast next week demand.",
    "How can I reduce energy cost?",
    "What is the renewable share?",
  ];
  $("example-chips").innerHTML = examples
    .map((question) => `<button type="button" class="chip">${escapeHtml(question)}</button>`)
    .join("");
  $("example-chips").querySelectorAll(".chip").forEach((button) => {
    button.addEventListener("click", () => {
      $("question-input").value = button.textContent || "";
      askQuestion(button.textContent || "");
    });
  });

  $("ask-form").addEventListener("submit", (event) => {
    event.preventDefault();
    const question = $("question-input").value.trim();
    if (!question) {
      $("ask-status").textContent = "Please enter a question.";
      return;
    }
    askQuestion(question);
  });
}

document.addEventListener("DOMContentLoaded", () => {
  initAskPanel();
  loadDashboard();
  if (new URLSearchParams(window.location.search).get("demo") === "1") {
    window.setTimeout(() => {
      askQuestion("How can I reduce energy cost?");
    }, 2000);
  }
});
