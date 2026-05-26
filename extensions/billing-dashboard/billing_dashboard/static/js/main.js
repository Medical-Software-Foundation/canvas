    (function() {
        /* ---- Tab switching ---- */
        var buttons = document.querySelectorAll('.tab-button');
        var panels = document.querySelectorAll('.tab-panel');
        buttons.forEach(function(btn) {
            btn.addEventListener('click', function() {
                var tab = btn.getAttribute('data-tab');
                buttons.forEach(function(b) { b.classList.remove('active'); b.setAttribute('aria-selected', 'false'); });
                panels.forEach(function(p) { p.classList.remove('active'); });
                btn.classList.add('active');
                btn.setAttribute('aria-selected', 'true');
                document.getElementById('panel-' + tab).classList.add('active');
            });
        });

        /* ---- Helpers ---- */
        function fmtCurrency(val) {
            return '$' + Number(val).toLocaleString('en-US', {minimumFractionDigits: 0, maximumFractionDigits: 0});
        }
        function renderBadge(source) {
            return source === 'mock' ? ' <span class="demo-badge">Demo data</span>' : '';
        }
        function setCardBadge(id, source) {
            document.getElementById(id).innerHTML = renderBadge(source);
        }
        function escapeHtml(s) {
            if (s === null || s === undefined) return '';
            return String(s)
                .replace(/&/g, '&amp;')
                .replace(/</g, '&lt;')
                .replace(/>/g, '&gt;')
                .replace(/"/g, '&quot;')
                .replace(/'/g, '&#39;');
        }
        function setTrend(el, pct) {
            if (pct > 0) {
                el.className = 'metric-trend up';
                el.textContent = '\u2191 ' + pct.toFixed(1) + '% from prior month';
            } else if (pct < 0) {
                el.className = 'metric-trend down';
                el.textContent = '\u2193 ' + Math.abs(pct).toFixed(1) + '% from prior month';
            } else {
                el.className = 'metric-trend neutral';
                el.textContent = '\u2192 No change';
            }
        }

        /* ---- Tab 1: Financial Overview ---- */
        fetch('/plugin-io/api/billing_dashboard/api/metrics?tab=overview')
            .then(function(r) { return r.json(); })
            .then(function(data) {
                var s = data.summary;
                document.getElementById('val-last-month').textContent = fmtCurrency(s.last_month_collected.value);
                document.getElementById('val-this-month').textContent = fmtCurrency(s.this_month_collected.value);
                document.getElementById('val-next-month').textContent = fmtCurrency(s.next_month_projected.value);
                document.getElementById('val-acceptance').textContent = s.claim_acceptance_rate.value.toFixed(1) + '%';
                setCardBadge('badge-last-month', s.last_month_collected.source);
                setCardBadge('badge-this-month', s.this_month_collected.source);
                setCardBadge('badge-next-month', s.next_month_projected.source);
                setCardBadge('badge-acceptance', s.claim_acceptance_rate.source);
                setTrend(document.getElementById('trend-last-month'), s.last_month_trend_pct.value);
                var nextTrend = document.getElementById('trend-next-month');
                nextTrend.className = 'metric-trend neutral';
                nextTrend.textContent = s.next_month_appt_count.value + ' appointments scheduled';

                /* Chart title badges */
                document.getElementById('daily-chart-title').innerHTML =
                    'Daily Volume &amp; Revenue (trailing month)' + renderBadge(data.daily && data.daily.source);
                document.getElementById('monthly-chart-title').innerHTML =
                    'Monthly Revenue Trend (trailing 12 months)' + renderBadge(data.monthly && data.monthly.source);

                /* Daily chart */
                if (typeof Chart !== 'undefined' && data.daily && data.daily.data) {
                    var dailyRows = data.daily.data;
                    var dLabels = dailyRows.map(function(d) { return d.date; });
                    new Chart(document.getElementById('daily-chart').getContext('2d'), {
                        type: 'bar',
                        data: {
                            labels: dLabels,
                            datasets: [
                                {
                                    label: 'Collected',
                                    data: dailyRows.map(function(d) { return d.collected; }),
                                    backgroundColor: 'rgba(37,99,235,0.15)',
                                    borderColor: '#2563eb',
                                    borderWidth: 1,
                                    borderRadius: 3,
                                    yAxisID: 'y',
                                    order: 2
                                },
                                {
                                    label: 'Visits',
                                    data: dailyRows.map(function(d) { return d.visits; }),
                                    type: 'line',
                                    borderColor: '#7c3aed',
                                    backgroundColor: 'rgba(124,58,237,0.1)',
                                    tension: 0.3,
                                    pointRadius: 3,
                                    yAxisID: 'y1',
                                    order: 1
                                }
                            ]
                        },
                        options: {
                            responsive: true, maintainAspectRatio: false,
                            scales: {
                                y: { beginAtZero: true, position: 'left', ticks: { callback: function(v) { return '$' + v; } } },
                                y1: { beginAtZero: true, position: 'right', grid: { drawOnChartArea: false }, ticks: { stepSize: 5 } }
                            },
                            plugins: { legend: { position: 'bottom', labels: { boxWidth: 12, padding: 12, font: { size: 11 } } } }
                        }
                    });
                }

                /* Monthly chart */
                if (typeof Chart !== 'undefined' && data.monthly && data.monthly.data) {
                    var monthlyRows = data.monthly.data;
                    new Chart(document.getElementById('monthly-chart').getContext('2d'), {
                        type: 'bar',
                        data: {
                            labels: monthlyRows.map(function(m) { return m.month; }),
                            datasets: [{
                                label: 'Monthly Collected',
                                data: monthlyRows.map(function(m) { return m.collected; }),
                                backgroundColor: monthlyRows.map(function(m, i) { return i === monthlyRows.length - 1 ? 'rgba(37,99,235,0.3)' : 'rgba(37,99,235,0.7)'; }),
                                borderRadius: 4
                            }]
                        },
                        options: {
                            responsive: true, maintainAspectRatio: false,
                            scales: { y: { beginAtZero: true, ticks: { callback: function(v) { return '$' + (v/1000) + 'k'; } } } },
                            plugins: { legend: { display: false } }
                        }
                    });
                }

                /* Insights */
                var insightsList = document.getElementById('insights-list');
                var insightsData = (data.insights && data.insights.data) ? data.insights.data : [];
                if (insightsData.length) {
                    var ihtml = '';
                    insightsData.forEach(function(ins) {
                        var icon = ins.severity === 'critical' ? '\u26a0\ufe0f' : (ins.severity === 'warning' ? '\u26a0' : '\u2139\ufe0f');
                        ihtml += '<div class="insight-card ' + ins.severity + '">' +
                            '<span class="insight-icon">' + icon + '</span>' +
                            '<div class="insight-content">' +
                            '<div class="insight-title">' + ins.title + '</div>' +
                            '<div class="insight-desc">' + ins.description + '</div>' +
                            '<span class="insight-tag">' + ins.tag + '</span>' +
                            '</div></div>';
                    });
                    insightsList.innerHTML = ihtml;
                } else {
                    insightsList.innerHTML = '<p class="insights-empty" style="color:#6b7280;font-size:13px;padding:12px 0;">No notable trends — metrics are steady.</p>';
                }

                document.getElementById('overview-status').textContent = '';
            })
            .catch(function(err) {
                document.getElementById('overview-status').textContent = 'Error loading metrics: ' + err.message;
                document.getElementById('overview-status').style.color = '#dc2626';
            });

        /* ---- Tab 2: Payer Analysis ---- */
        var payerLoaded = false;
        document.querySelector('[data-tab="payer"]').addEventListener('click', function() {
            if (payerLoaded) return;
            payerLoaded = true;
            fetch('/plugin-io/api/billing_dashboard/api/metrics?tab=payer')
                .then(function(r) { return r.json(); })
                .then(function(data) {
                    document.getElementById('payer-table-title').innerHTML =
                        'Payer Performance (trailing 90 days)' + renderBadge(data.payers && data.payers.source);
                    var tbody = document.getElementById('payer-table-body');
                    var payers = (data.payers && data.payers.data) ? data.payers.data : [];
                    if (payers.length === 0) {
                        tbody.innerHTML = '<tr><td colspan="4" style="text-align:center;padding:24px;color:#9ca3af">No payer data available.</td></tr>';
                        return;
                    }
                    var html = '';
                    payers.forEach(function(p) {
                        var deltaHtml = '\u2014';
                        if (p.cms_delta !== null && p.cms_delta !== undefined) {
                            var cls = p.cms_delta >= 0 ? 'positive' : 'negative';
                            var sign = p.cms_delta >= 0 ? '+' : '';
                            deltaHtml = '<span class="delta-badge ' + cls + '">' + sign + '$' + Math.abs(p.cms_delta).toFixed(2) + '</span>';
                        }
                        html += '<tr>' +
                            '<td>' + escapeHtml(p.name) + '</td>' +
                            '<td class="td-number">' + fmtCurrency(p.collected) + '</td>' +
                            '<td class="td-number">' + p.acceptance_rate.toFixed(1) + '%</td>' +
                            '<td>' + deltaHtml + '</td>' +
                            '</tr>';
                    });
                    tbody.innerHTML = html;

                    /* Doughnut chart */
                    var values = payers.map(function(p) { return p.collected; });
                    var totalRevenue = values.reduce(function(a, b) { return a + b; }, 0);
                    var chartCanvas = document.getElementById('payer-chart');
                    if (totalRevenue === 0) {
                        chartCanvas.parentElement.innerHTML =
                            '<p style="color:#6b7280;font-size:13px;text-align:center;padding:40px 16px;">' +
                            'No collected revenue in the trailing 90 days &mdash; payer mix is unavailable until claims post.' +
                            '</p>';
                    } else if (typeof Chart !== 'undefined') {
                        var labels = payers.map(function(p) { return p.name; });
                        var colors = ['#2563eb','#7c3aed','#db2777','#ea580c','#16a34a','#0891b2','#9ca3af'];
                        new Chart(chartCanvas.getContext('2d'), {
                            type: 'doughnut',
                            data: {
                                labels: labels,
                                datasets: [{ data: values, backgroundColor: colors.slice(0, labels.length), borderWidth: 0 }]
                            },
                            options: {
                                responsive: true,
                                maintainAspectRatio: false,
                                plugins: {
                                    legend: { position: 'bottom', labels: { boxWidth: 12, padding: 12, font: { size: 11 } } }
                                }
                            }
                        });
                    }
                })
                .catch(function(err) {
                    document.getElementById('payer-table-body').innerHTML =
                        '<tr><td colspan="4" style="text-align:center;padding:24px;color:#dc2626">Error: ' + err.message + '</td></tr>';
                });
        });

        /* ---- Tab 3: Reimbursement Trends ---- */
        var trendsLoaded = false;
        document.querySelector('[data-tab="trends"]').addEventListener('click', function() {
            if (trendsLoaded) return;
            trendsLoaded = true;
            fetch('/plugin-io/api/billing_dashboard/api/metrics?tab=trends')
                .then(function(r) { return r.json(); })
                .then(function(data) {
                    document.getElementById('cpt-table-title').innerHTML =
                        'Top CPT Codes by Volume (trailing 90 days)' + renderBadge(data.cpt_codes && data.cpt_codes.source);
                    /* CPT table */
                    var tbody = document.getElementById('cpt-table-body');
                    var cpts = (data.cpt_codes && data.cpt_codes.data) ? data.cpt_codes.data : [];
                    if (cpts.length === 0) {
                        tbody.innerHTML = '<tr><td colspan="6" style="text-align:center;padding:24px;color:#9ca3af">No CPT data available.</td></tr>';
                    } else {
                        var html = '';
                        cpts.forEach(function(c) {
                            var cmsRate = c.cms_rate;
                            var hasRate = cmsRate !== null && cmsRate !== undefined;
                            var deltaVal = hasRate ? (c.your_avg_charge - cmsRate) : 0;
                            var cls = deltaVal >= 0 ? 'positive' : 'negative';
                            var sign = deltaVal >= 0 ? '+' : '';
                            var trendCls = c.trend > 0 ? 'up' : (c.trend < 0 ? 'down' : 'flat');
                            var trendIcon = c.trend > 0 ? '\u2191' : (c.trend < 0 ? '\u2193' : '\u2192');
                            html += '<tr>' +
                                '<td class="td-number">' + escapeHtml(c.code) + '</td>' +
                                '<td>' + escapeHtml(c.description) + '</td>' +
                                '<td class="td-number">$' + c.your_avg_charge.toFixed(2) + '</td>' +
                                '<td class="td-number">' + (hasRate ? '$' + cmsRate.toFixed(2) : '—') + '</td>' +
                                '<td>' + (hasRate ? '<span class="delta-badge ' + cls + '">' + sign + '$' + Math.abs(deltaVal).toFixed(2) + '</span>' : '—') + '</td>' +
                                '<td><span class="trend-arrow ' + trendCls + '">' + trendIcon + '</span></td>' +
                                '</tr>';
                        });
                        tbody.innerHTML = html;
                    }

                    /* Trends line chart */
                    if (typeof Chart !== 'undefined' && data.monthly_avg && data.monthly_avg.data) {
                        var monthlyAvgRows = data.monthly_avg.data;
                        var months = monthlyAvgRows.map(function(m) { return m.month; });
                        var avgs = monthlyAvgRows.map(function(m) { return m.avg_charge; });
                        var benchmark = data.cms_benchmark || 128.94;
                        new Chart(document.getElementById('trends-chart').getContext('2d'), {
                            type: 'line',
                            data: {
                                labels: months,
                                datasets: [
                                    {
                                        label: 'Your Avg Charge',
                                        data: avgs,
                                        borderColor: '#2563eb',
                                        backgroundColor: 'rgba(37,99,235,0.1)',
                                        fill: true,
                                        tension: 0.3,
                                        pointRadius: 4
                                    },
                                    {
                                        label: 'CMS Benchmark',
                                        data: months.map(function() { return benchmark; }),
                                        borderColor: '#dc2626',
                                        borderDash: [6, 3],
                                        pointRadius: 0,
                                        fill: false
                                    }
                                ]
                            },
                            options: {
                                responsive: true,
                                maintainAspectRatio: false,
                                scales: {
                                    y: { beginAtZero: false, ticks: { callback: function(v) { return '$' + v; } } }
                                },
                                plugins: {
                                    legend: { position: 'bottom', labels: { boxWidth: 12, padding: 12, font: { size: 11 } } }
                                }
                            }
                        });
                    }
                })
                .catch(function(err) {
                    document.getElementById('cpt-table-body').innerHTML =
                        '<tr><td colspan="6" style="text-align:center;padding:24px;color:#dc2626">Error: ' + err.message + '</td></tr>';
                });
        });
    })();
