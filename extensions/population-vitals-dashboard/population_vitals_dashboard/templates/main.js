/* Population Vitals Dashboard — vanilla JS client.
 * Fetches aggregates from the /app/stats endpoint and renders them using Chart.js.
 *
 * Units: the server returns metrics in their stored base unit (weight in ounces,
 * height in inches, BP in mmHg, BMI unitless). Unit conversion for weight and
 * height is a pure display concern handled here — toggling the Unit dropdown
 * re-renders from the cached response with no extra server round-trip. This is
 * mathematically valid because mean / median / percentile / histogram edges all
 * scale linearly, and feet+inches is just a formatting of inches.
 */

(function () {
  "use strict";

  const API_PREFIX = "{{ api_prefix }}";
  const STATS_URL = API_PREFIX + "/app/stats";

  let histogramChart = null;
  let trendChart = null;
  let lastData = null; // last successful stats payload, for re-render on unit toggle

  // ── unit conversion config ────────────────────────────────────────────────
  // Only weight and height are convertible; everything else uses the server unit.
  // `toDisplay` converts a base-unit value to the chosen display unit.
  // `fmtNum` formats a display-unit number to a label (ft+in embeds its own unit).

  function formatFeetInches(inches) {
    const total = Math.round(inches);
    const ft = Math.floor(total / 12);
    const inch = total - ft * 12;
    return ft + "'" + inch + '"';
  }

  const UNIT_CONFIG = {
    weight: {
      options: [
        { value: "lb", label: "Pounds (lb)" },
        { value: "kg", label: "Kilograms (kg)" },
      ],
      convert: {
        lb: { toDisplay: function (v) { return v / 16; }, fmtNum: function (n) { return n.toFixed(1); }, unit: "lb", axis: "lb", formatsAxis: false },
        kg: { toDisplay: function (v) { return v * 0.028349523125; }, fmtNum: function (n) { return n.toFixed(1); }, unit: "kg", axis: "kg", formatsAxis: false },
      },
    },
    height: {
      options: [
        { value: "cm", label: "Centimeters (cm)" },
        { value: "ft_in", label: "Feet + inches" },
      ],
      convert: {
        cm: { toDisplay: function (v) { return v * 2.54; }, fmtNum: function (n) { return n.toFixed(1); }, unit: "cm", axis: "cm", formatsAxis: false },
        ft_in: { toDisplay: function (v) { return v; }, fmtNum: formatFeetInches, unit: "", axis: "ft/in", formatsAxis: true },
      },
    },
  };

  function getConv(metric, unitVal, serverUnit) {
    const cfg = UNIT_CONFIG[metric];
    if (cfg && cfg.convert[unitVal]) return cfg.convert[unitVal];
    // Passthrough for non-convertible metrics (BMI, BP): use the server's unit.
    return {
      toDisplay: function (v) { return v; },
      fmtNum: function (n) { return n === null ? "—" : n.toFixed(1); },
      unit: serverUnit || "",
      axis: serverUnit || "Value",
      formatsAxis: false,
    };
  }

  function withUnit(label, unit) {
    return unit ? label + " " + unit : label;
  }

  // ── DOM refs ──────────────────────────────────────────────────────────────

  const metricSel = document.getElementById("metric");
  const unitGroup = document.getElementById("unit-group");
  const unitSel = document.getElementById("unit");
  const minAgeInput = document.getElementById("min_age");
  const maxAgeInput = document.getElementById("max_age");
  const sexSel = document.getElementById("sex");
  const startInput = document.getElementById("start");
  const endInput = document.getElementById("end");
  const applyBtn = document.getElementById("apply-btn");

  const statusBanner = document.getElementById("status-banner");
  const summaryCards = document.getElementById("summary-cards");
  const chartsRow = document.getElementById("charts-row");
  const loadingOverlay = document.getElementById("loading-overlay");

  const statCohort = document.getElementById("stat-cohort");
  const statMean = document.getElementById("stat-mean");
  const statMedian = document.getElementById("stat-median");

  // ── initialise date inputs ────────────────────────────────────────────────

  function initDateDefaults() {
    const now = new Date();
    const yearAgo = new Date(now);
    yearAgo.setFullYear(yearAgo.getFullYear() - 1);
    endInput.value = toDateString(now);
    startInput.value = toDateString(yearAgo);
  }

  function toDateString(d) {
    return d.toISOString().slice(0, 10);
  }

  // ── unit dropdown ───────────────────────────────────────────────────────--

  function updateUnitDropdown() {
    const cfg = UNIT_CONFIG[metricSel.value];
    unitSel.innerHTML = "";
    if (!cfg) {
      unitGroup.style.display = "none";
      return;
    }
    cfg.options.forEach(function (o) {
      const opt = document.createElement("option");
      opt.value = o.value;
      opt.textContent = o.label;
      unitSel.appendChild(opt);
    });
    unitGroup.style.display = "";
  }

  // ── state helpers ─────────────────────────────────────────────────────────

  function setLoading(on) {
    if (on) {
      loadingOverlay.classList.remove("loading-overlay--hidden");
      applyBtn.disabled = true;
    } else {
      loadingOverlay.classList.add("loading-overlay--hidden");
      applyBtn.disabled = false;
    }
  }

  function showBanner(message, type) {
    statusBanner.textContent = message;
    statusBanner.className = "status-banner status-banner--" + type;
  }

  function hideBanner() {
    statusBanner.className = "status-banner status-banner--hidden";
  }

  function showContent() {
    summaryCards.classList.remove("summary-cards--hidden");
    chartsRow.classList.remove("charts-row--hidden");
  }

  function hideContent() {
    summaryCards.classList.add("summary-cards--hidden");
    chartsRow.classList.add("charts-row--hidden");
  }

  // ── chart helpers ─────────────────────────────────────────────────────────

  function destroyCharts() {
    if (histogramChart) { histogramChart.destroy(); histogramChart = null; }
    if (trendChart) { trendChart.destroy(); trendChart = null; }
  }

  function renderHistogram(histogram, conv) {
    const labels = histogram.map(function (b) {
      return conv.fmtNum(conv.toDisplay(b.min)) + "–" + conv.fmtNum(conv.toDisplay(b.max));
    });
    const data = histogram.map(function (b) { return b.count; });

    const ctx = document.getElementById("histogram-chart").getContext("2d");
    histogramChart = new Chart(ctx, {
      type: "bar",
      data: {
        labels: labels,
        datasets: [{
          label: conv.axis || "count",
          data: data,
          backgroundColor: "rgba(26, 111, 196, 0.7)",
          borderColor: "rgba(26, 111, 196, 1)",
          borderWidth: 1,
          borderRadius: 3,
        }],
      },
      options: {
        responsive: true,
        plugins: {
          legend: { display: false },
          tooltip: {
            callbacks: {
              label: function (ctx) { return ctx.raw + " patients"; },
            },
          },
        },
        scales: {
          y: {
            beginAtZero: true,
            title: { display: true, text: "Patients" },
          },
          x: {
            title: { display: true, text: conv.axis || "Value" },
            ticks: { maxRotation: 45 },
          },
        },
      },
    });
  }

  function renderTrend(monthlyTrend, conv) {
    const labels = monthlyTrend.map(function (p) { return p.month; });
    const data = monthlyTrend.map(function (p) {
      return p.median === null ? null : conv.toDisplay(p.median);
    });

    const yTicks = conv.formatsAxis
      ? { callback: function (value) { return conv.fmtNum(value); } }
      : {};

    const ctx = document.getElementById("trend-chart").getContext("2d");
    trendChart = new Chart(ctx, {
      type: "line",
      data: {
        labels: labels,
        datasets: [{
          label: withUnit("Median", conv.unit),
          data: data,
          fill: false,
          borderColor: "rgba(26, 111, 196, 1)",
          backgroundColor: "rgba(26, 111, 196, 0.15)",
          pointBackgroundColor: "rgba(26, 111, 196, 1)",
          tension: 0.3,
          spanGaps: true,
        }],
      },
      options: {
        responsive: true,
        plugins: {
          legend: { display: false },
          tooltip: {
            callbacks: {
              label: function (ctx) {
                return "Median " + conv.fmtNum(ctx.raw) + (conv.unit ? " " + conv.unit : "");
              },
            },
          },
        },
        scales: {
          y: {
            title: { display: true, text: conv.axis || "Value" },
            ticks: yTicks,
          },
          x: {
            title: { display: true, text: "Month" },
            ticks: { maxRotation: 45 },
          },
        },
      },
    });
  }

  // ── render from cached data (no refetch) ────────────────────────────────────

  function renderAll() {
    if (!lastData) return;
    const d = lastData;
    const conv = getConv(metricSel.value, unitSel.value, d.unit);

    statCohort.textContent = d.cohort_count.toLocaleString();
    statMean.textContent =
      d.mean !== null ? withUnit(conv.fmtNum(conv.toDisplay(d.mean)), conv.unit) : "—";
    statMedian.textContent =
      d.median !== null ? withUnit(conv.fmtNum(conv.toDisplay(d.median)), conv.unit) : "—";

    showContent();
    destroyCharts();

    if (d.histogram && d.histogram.length > 0) {
      renderHistogram(d.histogram, conv);
    }
    if (d.monthly_trend && d.monthly_trend.length > 0) {
      renderTrend(d.monthly_trend, conv);
    }
  }

  // ── fetch & render ────────────────────────────────────────────────────────

  function buildQueryString() {
    const params = new URLSearchParams();
    params.set("metric", metricSel.value);
    if (minAgeInput.value.trim()) params.set("min_age", minAgeInput.value.trim());
    if (maxAgeInput.value.trim()) params.set("max_age", maxAgeInput.value.trim());
    if (sexSel.value && sexSel.value !== "all") params.set("sex", sexSel.value);
    if (startInput.value) params.set("start", startInput.value);
    if (endInput.value) params.set("end", endInput.value);
    return params.toString();
  }

  async function fetchStats() {
    setLoading(true);
    hideBanner();
    destroyCharts();
    hideContent();
    lastData = null;

    try {
      const url = STATS_URL + "?" + buildQueryString();
      const resp = await fetch(url, { credentials: "same-origin" });

      if (!resp.ok) {
        showBanner("Server error (" + resp.status + "). Please try again.", "error");
        return;
      }

      const json = await resp.json();

      if (json.error) {
        if (json.error === "cohort_too_small") {
          showBanner(json.message || "Cohort is too small to display statistics.", "warning");
        } else if (json.error === "no_data") {
          showBanner(json.message || "No observations found for the selected filters.", "info");
        } else {
          showBanner("Error: " + (json.error || "unknown"), "error");
        }
        return;
      }

      lastData = json.data;
      renderAll();

    } catch (err) {
      showBanner("Network error. Please check your connection and try again.", "error");
      console.error("[PopulationVitalsDashboard] fetch error:", err);
    } finally {
      setLoading(false);
    }
  }

  // ── event listeners ───────────────────────────────────────────────────────

  applyBtn.addEventListener("click", fetchStats);

  // Changing the metric updates which unit options are available.
  metricSel.addEventListener("change", updateUnitDropdown);

  // Changing the unit re-renders from cached data — no server round-trip.
  unitSel.addEventListener("change", renderAll);

  // Allow pressing Enter in any input to trigger apply.
  [minAgeInput, maxAgeInput, startInput, endInput].forEach(function (el) {
    el.addEventListener("keydown", function (e) {
      if (e.key === "Enter") fetchStats();
    });
  });

  // ── init ──────────────────────────────────────────────────────────────────

  initDateDefaults();
  updateUnitDropdown();
  fetchStats(); // load data immediately with defaults
}());
