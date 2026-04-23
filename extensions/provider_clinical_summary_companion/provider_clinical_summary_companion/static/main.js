(function () {
    var API_BASE = '/plugin-io/api/provider_clinical_summary_companion/app';
    var WS_BASE = '/plugin-io/ws/provider_clinical_summary_companion';
    var COALESCE_MS = 100;

    var SECTION_META = [
        { key: 'socialDeterminants', title: 'Social Determinants', render: listRenderer(renderSocialDeterminants), icon: iconSocialDeterminants, empty: 'No social determinants on record.' },
        { key: 'conditions',         title: 'Conditions',           render: listRenderer(renderConditions),          icon: iconConditions,           empty: 'No conditions on record.' },
        { key: 'medications',        title: 'Medications',          render: listRenderer(renderMedications),         icon: iconMedications,          empty: 'No medications on record.' },
        { key: 'allergies',          title: 'Allergies',            render: listRenderer(renderAllergies),           icon: iconAllergies,            empty: 'No allergies on record.' },
        { key: 'vitals',             title: 'Vitals',               render: renderVitalsTable,                       icon: iconVitals,               empty: 'No vitals on record.' },
        { key: 'immunizations',      title: 'Immunizations',        render: listRenderer(renderImmunizations),       icon: iconImmunizations,        empty: 'No immunizations on record.' },
        { key: 'surgicalHistory',    title: 'Surgical History',     render: listRenderer(renderSurgicalHistory),     icon: iconSurgicalHistory,      empty: 'No surgical history on record.' },
    ];

    var state = {
        patientId: '',
        data: {},                 // section key → raw server payload
        pendingKeys: new Set(),
        flushTimer: null,
        vitalsPanelId: null,      // currently-viewed Vitals panel (sticky across refreshes)
    };

    function getPatientId() {
        var params = new URLSearchParams(window.location.search);
        return (params.get('patient_id') || '').trim();
    }

    // ---------- fetch helpers ----------

    function fetchSections(sectionKeys) {
        var url = API_BASE + '/data.json?patient_id=' + encodeURIComponent(state.patientId);
        if (sectionKeys && sectionKeys.length) {
            url += '&sections=' + encodeURIComponent(sectionKeys.join(','));
        }
        return fetch(url).then(function (res) {
            if (!res.ok) throw new Error('data.json ' + res.status);
            return res.json();
        });
    }

    function mergeSections(payload) {
        var sections = (payload && payload.sections) || {};
        Object.keys(sections).forEach(function (key) {
            state.data[key] = sections[key];
        });
    }

    function refetchAll() {
        return fetchSections(null).then(function (payload) {
            mergeSections(payload);
            renderAll();
        });
    }

    function refetchKeys(keys) {
        return fetchSections(keys).then(function (payload) {
            mergeSections(payload);
            keys.forEach(renderSection);
            keys.forEach(flashSection);
        });
    }

    function schedulePending(key) {
        state.pendingKeys.add(key);
        if (state.flushTimer) return;
        state.flushTimer = setTimeout(function () {
            var keys = Array.from(state.pendingKeys);
            state.pendingKeys.clear();
            state.flushTimer = null;
            if (keys.length) refetchKeys(keys).catch(function () { /* next WS msg retries */ });
        }, COALESCE_MS);
    }

    // ---------- rendering ----------

    function renderAll() {
        var root = document.getElementById('sections');
        root.textContent = '';
        SECTION_META.forEach(function (meta) {
            var section = document.createElement('section');
            section.className = 'section';
            section.dataset.key = meta.key;
            section.appendChild(sectionHeader(meta));
            var body = document.createElement('div');
            body.className = 'section-body';
            section.appendChild(body);
            root.appendChild(section);
            renderSection(meta.key);
        });
    }

    function sectionHeader(meta) {
        var header = document.createElement('div');
        header.className = 'section-header';
        var icon = meta.icon();
        icon.classList.add('section-icon');
        header.appendChild(icon);
        var title = document.createElement('div');
        title.className = 'section-title';
        title.textContent = meta.title;
        header.appendChild(title);
        return header;
    }

    function sectionForKey(key) {
        return document.querySelector('.section[data-key="' + key + '"]');
    }

    function addEmpty(body, text) {
        var empty = document.createElement('div');
        empty.className = 'empty';
        empty.textContent = text;
        body.appendChild(empty);
    }

    function renderSection(key) {
        var meta = SECTION_META.find(function (m) { return m.key === key; });
        if (!meta) return;
        var section = sectionForKey(key);
        if (!section) return;
        var body = section.querySelector('.section-body');
        body.textContent = '';
        meta.render(state.data[key], body, meta.empty);
    }

    function flashSection(key) {
        var section = sectionForKey(key);
        if (!section) return;
        section.classList.remove('flash');
        void section.offsetWidth;  // restart animation
        section.classList.add('flash');
    }

    function listRenderer(rowFn) {
        return function (data, body, emptyText) {
            var rows = Array.isArray(data) ? data : [];
            if (rows.length === 0) {
                addEmpty(body, emptyText);
                return 0;
            }
            rows.forEach(function (row) { body.appendChild(rowFn(row)); });
            return rows.length;
        };
    }

    // ---------- list row renderers ----------

    function row(primary, metaParts) {
        var el = document.createElement('div');
        el.className = 'row';
        var p = document.createElement('div');
        p.className = 'row-primary';
        p.textContent = primary;
        el.appendChild(p);
        var parts = (metaParts || []).filter(Boolean);
        if (parts.length) {
            var m = document.createElement('div');
            m.className = 'row-meta';
            parts.forEach(function (part, idx) {
                if (idx > 0) {
                    var sep = document.createElement('span');
                    sep.className = 'sep';
                    sep.textContent = '·';
                    m.appendChild(sep);
                }
                var span = document.createElement('span');
                span.textContent = part;
                m.appendChild(span);
            });
            el.appendChild(m);
        }
        return el;
    }

    function renderConditions(r) {
        return row(r.name || '(unnamed)', [
            r.clinical_status && r.clinical_status.charAt(0).toUpperCase() + r.clinical_status.slice(1),
            r.onset_date && 'onset ' + r.onset_date,
            r.resolution_date && 'resolved ' + r.resolution_date,
            r.coding && r.coding.code ? r.coding.code : null,
        ]);
    }

    function renderSurgicalHistory(r) {
        return row(r.name || '(unnamed)', [
            r.onset_date && r.onset_date,
            r.coding && r.coding.code ? r.coding.code : null,
        ]);
    }

    function renderMedications(r) {
        return row(r.name || '(unnamed)', [
            r.status && r.status.charAt(0).toUpperCase() + r.status.slice(1),
            r.sig,
            r.start_date && 'since ' + r.start_date.slice(0, 10),
        ]);
    }

    function renderAllergies(r) {
        return row(r.name || '(unnamed)', [
            r.severity,
            r.status,
            r.narrative,
        ]);
    }

    function renderImmunizations(r) {
        return row(r.name || '(unnamed)', [
            r.kind === 'statement' ? 'Statement' : 'Administered',
            r.date,
            r.comment,
        ]);
    }

    function renderSocialDeterminants(r) {
        return row(r.question || '(question)', [
            r.value,
            r.recorded_at && r.recorded_at.slice(0, 10),
        ]);
    }

    // ---------- vitals table renderer ----------

    function renderVitalsTable(data, body, emptyText) {
        var panels = (data && data.panels) || [];
        var types = (data && data.types) || [];
        if (!panels.length || !types.length) {
            state.vitalsPanelId = null;
            addEmpty(body, emptyText);
            return 0;
        }

        // Preserve the currently-viewed panel across refreshes by ID when
        // possible; otherwise fall back to the latest (index 0).
        var currentIndex = 0;
        if (state.vitalsPanelId) {
            var found = panels.findIndex(function (p) { return p.id === state.vitalsPanelId; });
            if (found >= 0) currentIndex = found;
        }
        state.vitalsPanelId = panels[currentIndex].id;

        renderVitalsPanel(body, panels, types, currentIndex);
        return panels.length;
    }

    function renderVitalsPanel(body, panels, types, currentIndex) {
        body.textContent = '';

        var nav = document.createElement('div');
        nav.className = 'vitals-nav';

        var older = document.createElement('button');
        older.type = 'button';
        older.className = 'vitals-nav-btn';
        older.setAttribute('aria-label', 'Older reading');
        older.textContent = '\u2190';
        older.disabled = currentIndex >= panels.length - 1;
        older.addEventListener('click', function () {
            if (currentIndex < panels.length - 1) {
                state.vitalsPanelId = panels[currentIndex + 1].id;
                renderVitalsPanel(body, panels, types, currentIndex + 1);
            }
        });
        nav.appendChild(older);

        var dateLabel = document.createElement('div');
        dateLabel.className = 'vitals-nav-date';
        var panel = panels[currentIndex];
        dateLabel.textContent = (panel.effective_datetime || '').slice(0, 10) || '—';
        nav.appendChild(dateLabel);

        var latest = document.createElement('button');
        latest.type = 'button';
        latest.className = 'vitals-nav-btn vitals-nav-latest';
        latest.textContent = 'Latest';
        latest.disabled = currentIndex === 0;
        latest.addEventListener('click', function () {
            if (currentIndex !== 0) {
                state.vitalsPanelId = panels[0].id;
                renderVitalsPanel(body, panels, types, 0);
            }
        });
        nav.appendChild(latest);

        var newer = document.createElement('button');
        newer.type = 'button';
        newer.className = 'vitals-nav-btn';
        newer.setAttribute('aria-label', 'Newer reading');
        newer.textContent = '\u2192';
        newer.disabled = currentIndex <= 0;
        newer.addEventListener('click', function () {
            if (currentIndex > 0) {
                state.vitalsPanelId = panels[currentIndex - 1].id;
                renderVitalsPanel(body, panels, types, currentIndex - 1);
            }
        });
        nav.appendChild(newer);

        body.appendChild(nav);

        var table = document.createElement('table');
        table.className = 'vitals-table';
        var tbody = document.createElement('tbody');
        types.forEach(function (type) {
            var tr = document.createElement('tr');
            var label = document.createElement('th');
            label.scope = 'row';
            label.appendChild(document.createTextNode(type.label));
            if (type.units) {
                var unit = document.createElement('span');
                unit.className = 'unit';
                unit.textContent = type.units;
                label.appendChild(unit);
            }
            tr.appendChild(label);
            var td = document.createElement('td');
            var value = panel.values && panel.values[type.key];
            if (value == null || value === '') {
                td.classList.add('missing');
                td.textContent = '\u2014';
            } else {
                td.textContent = value;
            }
            tr.appendChild(td);
            tbody.appendChild(tr);
        });
        table.appendChild(tbody);
        body.appendChild(table);
    }

    // ---------- icons (inline SVG, currentColor) ----------

    function svg(children) {
        var ns = 'http://www.w3.org/2000/svg';
        var el = document.createElementNS(ns, 'svg');
        el.setAttribute('viewBox', '0 0 24 24');
        el.setAttribute('fill', 'none');
        el.setAttribute('stroke', 'currentColor');
        el.setAttribute('stroke-width', '1.8');
        el.setAttribute('stroke-linecap', 'round');
        el.setAttribute('stroke-linejoin', 'round');
        if (typeof children === 'string') {
            var path = document.createElementNS(ns, 'path');
            path.setAttribute('d', children);
            el.appendChild(path);
        } else {
            children.forEach(function (child) { el.appendChild(child); });
        }
        return el;
    }

    function svgElem(tag, attrs) {
        var ns = 'http://www.w3.org/2000/svg';
        var el = document.createElementNS(ns, tag);
        Object.keys(attrs).forEach(function (k) { el.setAttribute(k, attrs[k]); });
        return el;
    }

    function iconSocialDeterminants() {
        return svg([
            svgElem('circle', { cx: 9,  cy: 9,  r: 3 }),
            svgElem('circle', { cx: 16, cy: 10, r: 2.5 }),
            svgElem('path', { d: 'M3 19c1-3.5 4-5 6-5s5 1.5 6 5' }),
            svgElem('path', { d: 'M14 19c0.5-2.5 2.5-4 4-4s3.5 1.5 4 4' }),
        ]);
    }
    function iconConditions() {
        return svg([
            svgElem('rect', { x: 5, y: 4, width: 14, height: 17, rx: 2 }),
            svgElem('rect', { x: 9, y: 2, width: 6, height: 3, rx: 1 }),
            svgElem('path', { d: 'M8.5 10l1.5 1.5L13 8.5' }),
            svgElem('path', { d: 'M15 14h-6' }),
            svgElem('path', { d: 'M15 17h-6' }),
        ]);
    }
    function iconMedications() {
        // Prescription bottle: slightly-wider cap on top, a rounded body
        // beneath, and two short label lines for visual texture.
        return svg([
            svgElem('rect', { x: 5,  y: 3, width: 14, height: 3,    rx: 0.8 }),
            svgElem('rect', { x: 6,  y: 6, width: 12, height: 15,   rx: 1.8 }),
            svgElem('line', { x1: 9, y1: 12, x2: 15, y2: 12 }),
            svgElem('line', { x1: 9, y1: 15, x2: 15, y2: 15 }),
        ]);
    }
    function iconAllergies() {
        return svg([
            svgElem('path', { d: 'M12 3l10 17H2L12 3z' }),
            svgElem('path', { d: 'M12 10v5' }),
            svgElem('circle', { cx: 12, cy: 18, r: 0.6, fill: 'currentColor', stroke: 'none' }),
        ]);
    }
    function iconVitals() {
        return svg('M3 12h4l2-5 3 10 2-5h7');
    }
    function iconImmunizations() {
        // Horizontal syringe: plunger flange on the left, barrel with tick
        // marks in the middle, needle on the right.
        return svg([
            svgElem('line', { x1: 3,  y1: 9,  x2: 3,  y2: 15 }),
            svgElem('line', { x1: 3,  y1: 12, x2: 6,  y2: 12 }),
            svgElem('rect', { x: 6,  y: 9,  width: 10, height: 6, rx: 0.5 }),
            svgElem('line', { x1: 9,  y1: 9,  x2: 9,  y2: 10.5 }),
            svgElem('line', { x1: 12, y1: 9,  x2: 12, y2: 10.5 }),
            svgElem('line', { x1: 15, y1: 9,  x2: 15, y2: 10.5 }),
            svgElem('line', { x1: 16, y1: 12, x2: 21, y2: 12 }),
        ]);
    }
    function iconSurgicalHistory() {
        // Scalpel tilted ~30°: rectangular handle on the left, asymmetric
        // blade on the right with a flat top flush against the handle top,
        // a sloping cutting edge beneath, and a pointed tip.
        var g = svgElem('g', { transform: 'rotate(30 12 12)' });
        g.appendChild(svgElem('rect', { x: 2, y: 11, width: 11, height: 2.5, rx: 0.8 }));
        g.appendChild(svgElem('path', { d: 'M13 11 L20 11 L22 13 L13 14 Z' }));
        return svg([g]);
    }

    // ---------- WebSocket wiring ----------

    function openSocket() {
        var scheme = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
        var url = scheme + '//' + window.location.host + WS_BASE + '/patient-' + state.patientId + '/';
        var socket;
        try {
            socket = new WebSocket(url);
        } catch (e) {
            setTimeout(openSocket, 4000);
            return;
        }
        socket.addEventListener('message', function (event) {
            var envelope;
            try { envelope = JSON.parse(event.data); } catch (e) { return; }
            // Platform wraps broadcast dicts as {"message": {...}}; unwrap.
            var payload = envelope && envelope.message ? envelope.message : envelope;
            var section = payload && payload.section;
            if (section) schedulePending(section);
        });
        socket.addEventListener('close', function () {
            setTimeout(openSocket, 4000);
        });
        socket.addEventListener('error', function () { /* close handler reconnects */ });
    }

    // ---------- boot ----------

    document.addEventListener('DOMContentLoaded', function () {
        state.patientId = getPatientId();
        if (!state.patientId) {
            document.getElementById('sections').textContent = 'Missing patient context.';
            return;
        }

        refetchAll()
            .then(function () { openSocket(); })
            .catch(function () {
                document.getElementById('sections').textContent = 'Failed to load clinical summary. Close and try again.';
            });

        document.addEventListener('visibilitychange', function () {
            if (!document.hidden) refetchAll().catch(function () { /* next visibility retries */ });
        });
        window.addEventListener('focus', function () {
            refetchAll().catch(function () { /* next focus retries */ });
        });
    });
})();
