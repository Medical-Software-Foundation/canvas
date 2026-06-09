(function () {
  const base = window.API_BASE;
  const statusEl = document.getElementById("status");
  const table = document.getElementById("results");
  const head = document.getElementById("period-cols-head");
  const body = document.getElementById("results-body");

  const reportSpec = {
    dataset_key: "appointments",
    measure_key: "no_show_rate",
    group_by: "provider",
    filters: [],
    period: { granularity: "month", count: 3, include_rolling_12: false },
  };

  function escapeHtml(s) {
    return String(s).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }

  fetch(base + "/run", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(reportSpec),
  })
    .then((r) => {
      if (!r.ok) throw new Error("Request failed: " + r.status);
      return r.json();
    })
    .then((data) => {
      const periods = data.periods || [];
      head.outerHTML = periods
        .map((p) => `<th class="num">${p}</th>`)
        .join("");
      body.innerHTML = (data.rows || [])
        .map((row) => {
          const cells = periods
            .map((p) => `<td class="num">${row.values[p] ?? "—"}</td>`)
            .join("");
          return `<tr><td>${escapeHtml(row.group_label)}</td>${cells}</tr>`;
        })
        .join("");
      statusEl.hidden = true;
      table.hidden = false;
    })
    .catch((err) => {
      statusEl.textContent = "Could not load report: " + err.message;
    });
})();
