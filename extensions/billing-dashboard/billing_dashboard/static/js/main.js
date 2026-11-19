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
        function escapeHtml(s) {
            if (s === null || s === undefined) return '';
            return String(s)
                .replace(/&/g, '&amp;')
                .replace(/</g, '&lt;')
                .replace(/>/g, '&gt;')
                .replace(/"/g, '&quot;')
                .replace(/'/g, '&#39;');
        }
        function setTrend(el, pct, source, noBaselineMsg) {
            if (source === 'no_baseline') {
                el.className = 'metric-trend neutral';
                el.textContent = '— ' + (noBaselineMsg || 'No prior-month baseline');
                return;
            }
            if (pct > 0) {
                el.className = 'metric-trend up';
                el.textContent = '↑ ' + pct.toFixed(1) + '% from prior month';
            } else if (pct < 0) {
                el.className = 'metric-trend down';
                el.textContent = '↓ ' + Math.abs(pct).toFixed(1) + '% from prior month';
            } else {
                el.className = 'metric-trend neutral';
                el.textContent = '→ No change';
            }
        }
        function renderEmptyChart(canvasId, message) {
            var c = document.getElementById(canvasId);
            if (c && c.parentElement) {
                c.parentElement.innerHTML =
                    '<p style="color:#6b7280;font-size:13px;text-align:center;padding:40px 16px;">' +
                    message + '</p>';
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
                if (s.claim_acceptance_rate.source === 'no_baseline') {
                    document.getElementById('val-acceptance').textContent = '—';
                } else {
                    document.getElementById('val-acceptance').textContent = s.claim_acceptance_rate.value.toFixed(1) + '%';
                }
                setTrend(document.getElementById('trend-last-month'), s.last_month_trend_pct.value, s.last_month_trend_pct.source);
                var thisMonthTrend = document.getElementById('trend-this-month');
                thisMonthTrend.className = 'metric-trend neutral';
                thisMonthTrend.textContent = 'Month-to-date';
                var nextTrend = document.getElementById('trend-next-month');
                nextTrend.className = 'metric-trend neutral';
                nextTrend.textContent = s.next_month_appt_count.value + ' appointments scheduled';
                var acceptanceTrend = document.getElementById('trend-acceptance');
                if (s.claim_acceptance_rate.source === 'no_baseline') {
                    setTrend(acceptanceTrend, null, 'no_baseline', 'No claims to rate');
                } else {
                    acceptanceTrend.className = 'metric-trend neutral';
                    acceptanceTrend.textContent = 'Trailing 30 days';
                }

                document.getElementById('daily-chart-title').textContent = 'Daily Volume & Revenue (trailing month)';
                document.getElementById('monthly-chart-title').textContent = 'Monthly Revenue Trend (trailing 12 months)';

                /* Daily chart */
                var dailyRows = (data.daily && data.daily.data) ? data.daily.data : [];
                if (dailyRows.length === 0) {
                    renderEmptyChart('daily-chart', 'No data in this window.');
                } else if (typeof Chart !== 'undefined') {
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
                var monthlyRows = (data.monthly && data.monthly.data) ? data.monthly.data : [];
                if (monthlyRows.length === 0) {
                    renderEmptyChart('monthly-chart', 'No data in this window.');
                } else if (typeof Chart !== 'undefined') {
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
                        var icon = ins.severity === 'critical' ? '⚠️' : (ins.severity === 'warning' ? '⚠' : 'ℹ️');
                        ihtml += '<div class="insight-card ' + ins.severity + '">' +
                            '<span class="insight-icon">' + icon + '</span>' +
                            '<div class="insight-content">' +
                            '<div class="insight-title">' + escapeHtml(ins.title) + '</div>' +
                            '<div class="insight-desc">' + escapeHtml(ins.description) + '</div>' +
                            '<span class="insight-tag">' + escapeHtml(ins.tag) + '</span>' +
                            '</div></div>';
                    });
                    insightsList.innerHTML = ihtml;
                } else {
                    insightsList.innerHTML = '<p class="insights-empty" style="color:#6b7280;font-size:13px;padding:12px 0;">No notable trends — metrics are steady.</p>';
                }

                document.getElementById('overview-status').textContent = '';
            })
            .catch(function(err) {
                console.error('[billing_dashboard] overview fetch failed:', err);
                ['val-last-month', 'val-this-month', 'val-next-month', 'val-acceptance'].forEach(function(id) {
                    document.getElementById(id).textContent = '—';
                });
                var status = document.getElementById('overview-status');
                status.textContent = 'Could not load metrics. Refresh the page to retry.';
                status.style.color = '#dc2626';
            });

        /* ---- Tab 2: Payer Analysis ---- */
        var payerLoaded = false;
        document.querySelector('[data-tab="payer"]').addEventListener('click', function() {
            if (payerLoaded) return;
            payerLoaded = true;
            fetch('/plugin-io/api/billing_dashboard/api/metrics?tab=payer')
                .then(function(r) { return r.json(); })
                .then(function(data) {
                    document.getElementById('payer-table-title').textContent = 'Payer Performance (trailing 90 days)';
                    var tbody = document.getElementById('payer-table-body');
                    var payers = (data.payers && data.payers.data) ? data.payers.data : [];
                    if (payers.length === 0) {
                        tbody.innerHTML = '<tr><td colspan="4" style="text-align:center;padding:24px;color:#9ca3af">No payer data available.</td></tr>';
                        renderEmptyChart('payer-chart', 'No collected revenue in the trailing 90 days &mdash; payer mix is unavailable until claims post.');
                        return;
                    }
                    var html = '';
                    payers.forEach(function(p) {
                        var deltaHtml = '—';
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
                    if (totalRevenue === 0) {
                        renderEmptyChart('payer-chart', 'No collected revenue in the trailing 90 days &mdash; payer mix is unavailable until claims post.');
                    } else if (typeof Chart !== 'undefined') {
                        var labels = payers.map(function(p) { return p.name; });
                        var colors = ['#2563eb','#7c3aed','#db2777','#ea580c','#16a34a','#0891b2','#9ca3af'];
                        new Chart(document.getElementById('payer-chart').getContext('2d'), {
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
                    console.error('[billing_dashboard] payer fetch failed:', err);
                    payerLoaded = false;
                    document.getElementById('payer-table-body').innerHTML =
                        '<tr><td colspan="4" style="text-align:center;padding:24px;color:#dc2626">' +
                        'Could not load payer data. Switch tabs and back to retry.' +
                        '</td></tr>';
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
                    document.getElementById('cpt-table-title').textContent = 'Top CPT Codes by Volume (trailing 90 days)';
                    /* CPT table */
                    var tbody = document.getElementById('cpt-table-body');
                    var cpts = (data.cpt_codes && data.cpt_codes.data) ? data.cpt_codes.data : [];
                    if (cpts.length === 0) {
                        tbody.innerHTML = '<tr><td colspan="5" style="text-align:center;padding:24px;color:#9ca3af">No CPT data available.</td></tr>';
                    } else {
                        var html = '';
                        cpts.forEach(function(c) {
                            var cmsRate = c.cms_rate;
                            var hasRate = cmsRate !== null && cmsRate !== undefined;
                            var deltaVal = hasRate ? (c.your_avg_charge - cmsRate) : 0;
                            var cls = deltaVal >= 0 ? 'positive' : 'negative';
                            var sign = deltaVal >= 0 ? '+' : '';
                            html += '<tr>' +
                                '<td class="td-number">' + escapeHtml(c.code) + '</td>' +
                                '<td>' + escapeHtml(c.description) + '</td>' +
                                '<td class="td-number">$' + c.your_avg_charge.toFixed(2) + '</td>' +
                                '<td class="td-number">' + (hasRate ? '$' + cmsRate.toFixed(2) : '—') + '</td>' +
                                '<td>' + (hasRate ? '<span class="delta-badge ' + cls + '">' + sign + '$' + Math.abs(deltaVal).toFixed(2) + '</span>' : '—') + '</td>' +
                                '</tr>';
                        });
                        tbody.innerHTML = html;
                    }

                    /* Trends line chart */
                    var monthlyAvgRows = (data.monthly_avg && data.monthly_avg.data) ? data.monthly_avg.data : [];
                    if (monthlyAvgRows.length === 0) {
                        renderEmptyChart('trends-chart', 'No data in this window.');
                    } else if (typeof Chart !== 'undefined') {
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
                    console.error('[billing_dashboard] trends fetch failed:', err);
                    trendsLoaded = false;
                    document.getElementById('cpt-table-body').innerHTML =
                        '<tr><td colspan="5" style="text-align:center;padding:24px;color:#dc2626">' +
                        'Could not load trends data. Switch tabs and back to retry.' +
                        '</td></tr>';
                });
        });

        /* ---- Tab 4: Claims (server-side sort + filters, CSV export) ---- */
        var CLAIMS_API = '/plugin-io/api/billing_dashboard/api/claims';
        var CLAIM_COLUMNS = [
            {key: 'claim_number', label: 'Claim #', sortable: false, number: false},
            {key: 'date_of_service', label: 'Date of service', sortable: true},
            {key: 'patient', label: 'Patient', sortable: true},
            {key: 'provider', label: 'Provider', sortable: true},
            {key: 'payer', label: 'Payer', sortable: true},
            {key: 'queue', label: 'Queue', sortable: true},
            {key: 'business_line', label: 'Business line', sortable: true, businessLineOnly: true},
            {key: 'patient_balance', label: 'Patient bal.', sortable: true, money: true},
            {key: 'coverage_balance', label: 'Coverage bal.', sortable: true, money: true},
            {key: 'balance', label: 'Total bal.', sortable: true, money: true}
        ];
        var claimsState = {sort: 'date_of_service', dir: 'desc', window: '90', queue: '', business_line: ''};
        var claimsFiltersReady = false;
        var claimsBusinessLineEnabled = false;
        var claimsLoaded = false;

        function fmtMoney2(val) {
            return '$' + Number(val).toLocaleString('en-US', {minimumFractionDigits: 2, maximumFractionDigits: 2});
        }
        function claimsQueryString() {
            var p = new URLSearchParams();
            p.set('sort', claimsState.sort);
            p.set('dir', claimsState.dir);
            p.set('window', claimsState.window);
            if (claimsState.queue) p.set('queue', claimsState.queue);
            if (claimsBusinessLineEnabled && claimsState.business_line) p.set('business_line', claimsState.business_line);
            return p.toString();
        }
        function visibleClaimColumns() {
            return CLAIM_COLUMNS.filter(function(c) { return !c.businessLineOnly || claimsBusinessLineEnabled; });
        }
        function renderClaimsHead() {
            var head = document.getElementById('claims-head');
            head.innerHTML = '';
            visibleClaimColumns().forEach(function(col) {
                var th = document.createElement('th');
                th.textContent = col.label;
                if (col.sortable) {
                    var arrow = document.createElement('span');
                    arrow.className = 'sort-arrow';
                    var active = claimsState.sort === col.key;
                    arrow.textContent = active ? (claimsState.dir === 'asc' ? '▲' : '▼') : '↕';
                    th.appendChild(arrow);
                    if (active) th.classList.add('sorted');
                    th.setAttribute('aria-sort', active ? (claimsState.dir === 'asc' ? 'ascending' : 'descending') : 'none');
                    th.addEventListener('click', function() {
                        if (claimsState.sort === col.key) {
                            claimsState.dir = claimsState.dir === 'asc' ? 'desc' : 'asc';
                        } else {
                            claimsState.sort = col.key;
                            claimsState.dir = col.money || col.key === 'date_of_service' ? 'desc' : 'asc';
                        }
                        loadClaims();
                    });
                } else {
                    th.style.cursor = 'default';
                }
                head.appendChild(th);
            });
        }
        function fillSelect(sel, options, current) {
            options.forEach(function(o) {
                var opt = document.createElement('option');
                opt.value = o.value;
                opt.textContent = o.label;
                if (o.value === current) opt.selected = true;
                sel.appendChild(opt);
            });
        }
        function setupClaimsFilters(filters) {
            claimsBusinessLineEnabled = !!filters.business_line_enabled;
            var winSel = document.getElementById('claims-window');
            fillSelect(winSel, filters.windows.map(function(d) {
                return {value: String(d), label: 'Last ' + d + ' days'};
            }), claimsState.window);
            winSel.addEventListener('change', function() { claimsState.window = winSel.value; loadClaims(); });

            var qSel = document.getElementById('claims-queue');
            fillSelect(qSel, filters.queues.map(function(q) {
                return {value: q.name, label: q.display_name};
            }), claimsState.queue);
            qSel.addEventListener('change', function() { claimsState.queue = qSel.value; loadClaims(); });

            if (claimsBusinessLineEnabled) {
                document.getElementById('claims-bl-wrap').hidden = false;
                var blSel = document.getElementById('claims-business-line');
                fillSelect(blSel, filters.business_lines.map(function(b) {
                    return {value: b.id, label: b.name};
                }), claimsState.business_line);
                blSel.addEventListener('change', function() { claimsState.business_line = blSel.value; loadClaims(); });
            }
            claimsFiltersReady = true;
        }
        function showClaimsError(msg) {
            var el = document.getElementById('claims-error');
            el.textContent = msg;
            el.classList.toggle('visible', !!msg);
        }
        function renderClaimsBody(data) {
            var cols = visibleClaimColumns();
            var body = document.getElementById('claims-body');
            if (!data.claims.length) {
                body.innerHTML = '<tr><td colspan="' + cols.length +
                    '" style="text-align:center;padding:24px;color:#9ca3af">No claims match these filters.</td></tr>';
            } else {
                body.innerHTML = data.claims.map(function(row) {
                    return '<tr>' + cols.map(function(col) {
                        var v = row[col.key];
                        if (col.money) return '<td class="td-number">' + fmtMoney2(v) + '</td>';
                        return '<td>' + escapeHtml(v) + '</td>';
                    }).join('') + '</tr>';
                }).join('');
            }
            var note = data.claims.length + ' claim' + (data.claims.length === 1 ? '' : 's') + ' shown.';
            if (data.truncated) {
                note += ' Showing the first ' + data.row_limit + ' rows; narrow the filters or use Download CSV for more.';
            }
            document.getElementById('claims-footnote').textContent = note;
        }
        function loadClaims() {
            var qs = claimsQueryString();
            document.getElementById('claims-export').setAttribute('href', CLAIMS_API + '.csv?' + qs);
            fetch(CLAIMS_API + '?' + qs)
                .then(function(r) {
                    return r.json().then(function(body) { return {ok: r.ok, body: body}; });
                })
                .then(function(res) {
                    if (!res.ok) {
                        // A failed first load leaves no filters to change, so let a
                        // tab switch retry instead of leaving the tab stuck.
                        if (!claimsFiltersReady) claimsLoaded = false;
                        showClaimsError(res.body.error || 'Could not load claims.');
                        return;
                    }
                    showClaimsError('');
                    if (!claimsFiltersReady) setupClaimsFilters(res.body.filters);
                    renderClaimsHead();
                    renderClaimsBody(res.body);
                })
                .catch(function(err) {
                    console.error('[billing_dashboard] claims fetch failed:', err);
                    claimsLoaded = false;
                    showClaimsError('Could not load claims. Switch tabs and back to retry.');
                });
        }
        document.querySelector('[data-tab="claims"]').addEventListener('click', function() {
            if (claimsLoaded) return;
            claimsLoaded = true;
            loadClaims();
        });
    })();
