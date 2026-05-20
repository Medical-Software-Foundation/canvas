// Availability Manager — week view with drag-create, multi-provider, recurrence
// Replaces the previous card-list UI.

(function () {
    'use strict';

    // ---------------- Constants ----------------
    const DAY_CODES = ['SU', 'MO', 'TU', 'WE', 'TH', 'FR', 'SA'];
    const DAY_LABELS_LONG = ['Sunday', 'Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday'];
    const DAY_LABELS_SHORT = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];
    const DAY_LABELS_INITIAL = ['S', 'M', 'T', 'W', 'T', 'F', 'S'];
    const MONTH_LABELS = ['January', 'February', 'March', 'April', 'May', 'June',
        'July', 'August', 'September', 'October', 'November', 'December'];
    const MS_DAY = 24 * 60 * 60 * 1000;
    const HOUR_PX = 48;
    const SNAP_MIN = 15;
    // Right-side empty strip in every day column reserved for drag-create.
    const DRAG_GUTTER_PX = 14;

    // Calendar type constants from server (window.calendarTypes is provided)
    const TYPE_AVAILABLE = (window.calendarTypes || []).find(t => t.label === 'Available')?.value || 'Clinic';
    const TYPE_BLOCK = (window.calendarTypes || []).find(t => t.label === 'Busy')?.value || 'Admin';

    // ---------------- State ----------------
    // Default the provider filter to just the logged-in user when they are
    // themselves a provider; otherwise leave it empty so a non-provider user
    // (e.g. a scheduler) is forced to pick — defaulting to "all" produces a
    // wall of overlapping tiles for an org with many providers.
    const initialSelectedProviderIds = (() => {
        const loggedIn = window.loggedInUserId ? String(window.loggedInUserId) : '';
        const providers = window.providers || [];
        if (loggedIn && providers.some(p => String(p.id) === loggedIn)) {
            return new Set([loggedIn]);
        }
        return new Set();
    })();

    const state = {
        providers: window.providers || [],
        locations: window.locations || [],
        noteTypes: window.noteTypes || [],
        events: (window.events || []).slice(),       // master records
        locationId: '',
        weekStart: weekStartOf(new Date()),           // Sunday of visible week
        modal: null,        // null | { mode: 'create'|'edit', initial..., editScope: 'all'|'this' }
        tilePopup: null,    // null | { masterId, occurrence } — read-only detail
        scopePrompt: null,  // null | { masterId, occurrence, action: 'edit'|'delete' }
        selectedProviderIds: initialSelectedProviderIds,
        openFilter: null, // null | 'providers' | 'rooms'
        // Display timezone — events are stored in UTC server-side; we send
        // this as ?tz=… on fetch and `timezone` in the body on writes so the
        // server converts to/from UTC for us.
        viewTimezone: (Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC'),
        saving: false,
        error: '',
    };
    if (state.locations.length === 1) state.locationId = String(state.locations[0].id);

    // ---------------- DOM helpers ----------------
    const app = document.getElementById('app');
    const modalRoot = document.getElementById('modal-root');
    function el(tag, attrs = {}, children = []) {
        const node = document.createElement(tag);
        for (const k of Object.keys(attrs)) {
            const v = attrs[k];
            if (v == null || v === false) continue;
            if (k === 'class') node.className = v;
            else if (k === 'style' && typeof v === 'object') Object.assign(node.style, v);
            else if (k === 'dataset') Object.assign(node.dataset, v);
            else if (k.startsWith('on') && typeof v === 'function') {
                node.addEventListener(k.slice(2).toLowerCase(), v);
            } else if (k === 'html') {
                node.innerHTML = v;
            } else {
                node.setAttribute(k, v);
            }
        }
        for (const c of [].concat(children)) {
            if (c == null || c === false) continue;
            if (typeof c === 'string' || typeof c === 'number') node.appendChild(document.createTextNode(c));
            else node.appendChild(c);
        }
        return node;
    }

    // ---------------- Date helpers ----------------
    function startOfDay(d) {
        return new Date(d.getFullYear(), d.getMonth(), d.getDate());
    }
    function addDays(d, n) {
        const r = new Date(d);
        r.setDate(r.getDate() + n);
        return r;
    }
    function weekStartOf(d) {
        const s = startOfDay(d);
        s.setDate(s.getDate() - s.getDay()); // Sunday
        return s;
    }
    function weekEndOf(d) {
        return new Date(addDays(weekStartOf(d), 7).getTime() - 1);
    }
    function pad2(n) { return String(n).padStart(2, '0'); }
    function isoLocal(d) {
        return d.getFullYear() + '-' + pad2(d.getMonth() + 1) + '-' + pad2(d.getDate())
            + 'T' + pad2(d.getHours()) + ':' + pad2(d.getMinutes());
    }
    function dateOnly(d) {
        return d.getFullYear() + '-' + pad2(d.getMonth() + 1) + '-' + pad2(d.getDate());
    }
    function parseLocalISO(str) {
        if (!str) return null;
        const m = str.match(/(\d{4})-(\d{2})-(\d{2})(?:T(\d{2}):(\d{2}))?/);
        if (!m) return null;
        return new Date(+m[1], +m[2] - 1, +m[3], +(m[4] || 0), +(m[5] || 0));
    }
    function fmtTime12(d) {
        let h = d.getHours();
        const m = d.getMinutes();
        const ap = h >= 12 ? 'PM' : 'AM';
        h = h % 12; if (h === 0) h = 12;
        return h + ':' + pad2(m) + ' ' + ap;
    }
    function fmtWeekRange(start) {
        const end = addDays(start, 6);
        const sameMonth = start.getMonth() === end.getMonth() && start.getFullYear() === end.getFullYear();
        const sameYear = start.getFullYear() === end.getFullYear();
        if (sameMonth) {
            return MONTH_LABELS[start.getMonth()] + ' ' + start.getDate() + ' – ' + end.getDate() + ', ' + start.getFullYear();
        } else if (sameYear) {
            return MONTH_LABELS[start.getMonth()] + ' ' + start.getDate() + ' – '
                + MONTH_LABELS[end.getMonth()] + ' ' + end.getDate() + ', ' + start.getFullYear();
        }
        return MONTH_LABELS[start.getMonth()] + ' ' + start.getDate() + ', ' + start.getFullYear() + ' – '
            + MONTH_LABELS[end.getMonth()] + ' ' + end.getDate() + ', ' + end.getFullYear();
    }
    function isSameDay(a, b) {
        return a.getFullYear() === b.getFullYear() && a.getMonth() === b.getMonth() && a.getDate() === b.getDate();
    }

    // ---------------- Lookup helpers ----------------
    function providerName(id) {
        const p = state.providers.find(p => String(p.id) === String(id));
        return p ? (p.full_name || p.name) : id;
    }
    function locationName(id) {
        const l = state.locations.find(l => String(l.id) === String(id));
        return l ? l.name : '';
    }
    function noteTypeName(id) {
        const key = String(id);
        // window.noteTypeNames is the full id→name map (includes inactive /
        // non-scheduleable types). state.noteTypes is the chip list (active +
        // scheduleable only). Resolve display names from the full map first.
        const nameMap = window.noteTypeNames || {};
        if (nameMap[key]) return nameMap[key];
        const nt = state.noteTypes.find(nt => String(nt.id) === key);
        return nt ? nt.name : key;
    }
    function dayOfWeekCode(date) { return DAY_CODES[date.getDay()]; }

    // ---------------- Recurrence helpers ----------------
    // Parse master event's recurrence into a normalized rule object
    function ruleOf(event) {
        const t = event.recurrence?.type || '';
        return {
            type: t || '',
            interval: Math.max(1, +(event.recurrence?.interval || 0) || 1),
            days: (event.daysOfWeek || []).slice().sort(),
            endDate: event.recurrence?.endDate || '',
        };
    }
    function ruleEqual(a, b) {
        return a.type === b.type
            && a.interval === b.interval
            && a.days.join(',') === b.days.join(',');
    }

    // Expand a master event into occurrences within [rangeStart, rangeEnd]
    function expandOccurrences(event, rangeStart, rangeEnd) {
        const startDt = parseLocalISO(event.startTime);
        const endDt = parseLocalISO(event.endTime);
        if (!startDt || !endDt) return [];
        const duration = endDt.getTime() - startDt.getTime();
        const type = event.recurrence?.type || '';
        const interval = Math.max(1, +(event.recurrence?.interval || 0) || 1);
        const days = (event.daysOfWeek || []).filter(d => DAY_CODES.includes(d));
        const recEnd = parseLocalISO(event.recurrence?.endDate);

        if (!type) {
            if (startDt >= rangeStart && startDt <= rangeEnd) {
                return [{ start: startDt, end: new Date(startDt.getTime() + duration), masterId: event.id }];
            }
            return [];
        }

        const eventDayStart = startOfDay(startDt);
        const stop = recEnd ? new Date(Math.min(rangeEnd.getTime(), recEnd.getTime())) : rangeEnd;
        const begin = new Date(Math.max(rangeStart.getTime(), eventDayStart.getTime()));

        const out = [];
        for (let d = startOfDay(begin); d.getTime() <= stop.getTime(); d = addDays(d, 1)) {
            if (d.getTime() < eventDayStart.getTime()) continue;
            let match = false;
            if (type === 'DAILY') {
                const daysSince = Math.round((d - eventDayStart) / MS_DAY);
                match = daysSince >= 0 && (daysSince % interval === 0);
            } else if (type === 'WEEKLY') {
                const wsd = weekStartOf(d);
                const wse = weekStartOf(eventDayStart);
                const weeksSince = Math.round((wsd - wse) / (7 * MS_DAY));
                const intervalMatch = weeksSince >= 0 && (weeksSince % interval === 0);
                const dayMatch = days.length === 0 ? (d.getDay() === startDt.getDay())
                    : days.includes(dayOfWeekCode(d));
                match = intervalMatch && dayMatch;
            }
            if (!match) continue;
            const occStart = new Date(d.getFullYear(), d.getMonth(), d.getDate(),
                startDt.getHours(), startDt.getMinutes());
            const occEnd = new Date(occStart.getTime() + duration);
            if (occStart >= rangeStart && occStart <= rangeEnd) {
                out.push({ start: occStart, end: occEnd, masterId: event.id });
            }
        }
        return out;
    }

    // ---------------- Series consolidation ----------------
    // Group master events into "logical series" by (location, type, title,
    // startTime hh:mm, endTime hh:mm, recurrence rule, allowedNoteTypes set).
    // Multi-provider events and edit-this-only splits all roll up here.
    function seriesKeyOf(event) {
        const startDt = parseLocalISO(event.startTime);
        const endDt = parseLocalISO(event.endTime);
        const hhStart = startDt ? pad2(startDt.getHours()) + ':' + pad2(startDt.getMinutes()) : '';
        const hhEnd = endDt ? pad2(endDt.getHours()) + ':' + pad2(endDt.getMinutes()) : '';
        const rule = ruleOf(event);
        const ntKey = (event.allowedNoteTypes || []).slice().sort().join(',');
        // Non-recurring events share a key only when they are literally the
        // same event (same date too). The hh:mm-only key was intentional for
        // recurring series (so multi-provider rolls up; so this-only
        // overrides stay grouped with the parent) — but for one-offs, two
        // distinct dates would collapse into one logical series and a
        // single delete or edit would silently affect both.
        const dateComponent = rule.type === ''
            ? (startDt ? [startDt.getFullYear(), pad2(startDt.getMonth() + 1), pad2(startDt.getDate())].join('-') : '')
            : '';
        return [
            event.location || '',
            event.calendarType || '',
            event.title || '',
            hhStart, hhEnd,
            rule.type, rule.interval, rule.days.join(','),
            ntKey,
            dateComponent,
        ].join('||');
    }
    function seriesFor(masterEventId) {
        const ev = state.events.find(e => e.id === masterEventId);
        if (!ev) return [];
        const key = seriesKeyOf(ev);
        return state.events.filter(e => seriesKeyOf(e) === key);
    }
    function providersInSeries(records) {
        const ids = new Set(records.map(r => String(r.provider)).filter(Boolean));
        return Array.from(ids);
    }

    // ---------------- API helpers ----------------
    async function apiCall(path, options = {}) {
        const res = await fetch(path, {
            credentials: 'same-origin',
            headers: { 'Content-Type': 'application/json' },
            ...options,
        });
        if (!res.ok) {
            const text = await res.text();
            throw new Error('HTTP ' + res.status + ': ' + text);
        }
        const ct = res.headers.get('content-type') || '';
        return ct.includes('application/json') ? res.json() : res.text();
    }
    async function refreshEvents(excludedIds, truncations) {
        try {
            const url = '/plugin-io/api/provider_availability_manager/events?tz=' + encodeURIComponent(state.viewTimezone || 'UTC');
            const data = await apiCall(url);
            // Filter any IDs we just deleted in case the read path is lagging
            // behind the write — without this guard, a stale GET re-introduces
            // the just-deleted records and the user has to delete twice.
            const filtered = excludedIds && excludedIds.size
                ? (data || []).filter(e => !excludedIds.has(String(e.id)))
                : (data || []);
            // Same lag affects PATCHes — re-apply truncations we just sent so
            // a stale read can't re-extend a series past its new end date.
            if (truncations) {
                for (const ev of filtered) {
                    const t = truncations[String(ev.id)];
                    if (t) {
                        ev.recurrence = Object.assign({}, ev.recurrence || {}, { endDate: t });
                    }
                }
            }
            state.events = filtered;
        } catch (err) {
            console.warn('Failed to refresh events:', err);
        }
    }
    async function ensureCalendar(provider, type, locationId) {
        const provName = providerName(provider);
        const locName = locationName(locationId);
        const typeLabel = type === TYPE_AVAILABLE ? 'Clinic' : 'Admin';
        // Description is the staff UUID — the durable mapping key the
        // scheduler uses to associate a Calendar with a Staff record. The
        // human-readable bits stay in the title, which the SDK builds from
        // (provider_name, type, location). Renaming the staff later won't
        // break the link because the lookup keys off this UUID.
        const body = {
            provider: provider,
            providerName: provName,
            location: locationId || null,
            locationName: locName || null,
            type: typeLabel,
            description: String(provider),
        };
        const result = await apiCall('/plugin-io/api/provider_availability_manager/calendar', {
            method: 'POST',
            body: JSON.stringify(body),
        });
        return result.calendarId;
    }
    function eventBody(form, calendarId) {
        const startISO = form.date + 'T' + form.startTime + ':00';
        const endISO = form.date + 'T' + form.endTime + ':00';
        // The form holds raw UI state (mode/customRepeatFreq/...). Convert it
        // into the wire shape the API expects (frequency/interval/days/endsAt).
        const recurrence = buildRecurrencePayload(form);
        const body = {
            calendar: calendarId,
            timezone: state.viewTimezone || undefined,
            title: form.title,
            startTime: startISO,
            endTime: endISO,
            allowedNoteTypes: form.type === TYPE_AVAILABLE ? (form.allowedNoteTypes || []) : [],
        };
        if (recurrence.frequency) {
            body.recurrenceFrequency = recurrence.frequency;
            body.recurrenceInterval = recurrence.interval || 1;
            body.recurrenceDays = recurrence.days || [];
            body.recurrenceEndsAt = recurrence.endsAt || null;
        }
        return body;
    }

    // ---------------- Render: Toolbar ----------------
    function renderToolbar() {
        const showAllLoc = state.locations.length > 1;
        const locOptions = state.locations.map(l =>
            el('option', { value: String(l.id), selected: String(l.id) === state.locationId }, l.name)
        );
        if (showAllLoc) {
            locOptions.unshift(el('option', { value: '', selected: state.locationId === '' }, 'All locations'));
        }
        const locSelect = el('select', { onchange: e => { state.locationId = e.target.value; renderAll(); } }, locOptions);

        const dateJump = el('input', {
            type: 'date',
            value: dateOnly(state.weekStart),
            onchange: e => {
                const v = parseLocalISO(e.target.value);
                if (v) { state.weekStart = weekStartOf(v); renderAll(); }
            },
        });

        const onlyProviders = state.providers;

        const popoverFor = (group, label) => {
            if (state.openFilter !== label) return null;
            return el('div', { class: 'av-popover', onclick: e => e.stopPropagation() }, [
                el('div', { class: 'av-popover-actions' }, [
                    el('button', { onclick: () => {
                        group.forEach(p => state.selectedProviderIds.add(String(p.id)));
                        renderAll();
                    } }, 'Select all'),
                    el('button', { onclick: () => {
                        group.forEach(p => state.selectedProviderIds.delete(String(p.id)));
                        renderAll();
                    } }, 'Clear'),
                ]),
                ...group.map(p => {
                    const id = String(p.id);
                    const checked = state.selectedProviderIds.has(id);
                    return el('label', { class: 'av-popover-row' }, [
                        el('input', {
                            type: 'checkbox',
                            checked: checked,
                            onchange: () => {
                                if (state.selectedProviderIds.has(id)) state.selectedProviderIds.delete(id);
                                else state.selectedProviderIds.add(id);
                                renderAll();
                            },
                        }),
                        el('span', {}, p.full_name || p.name),
                    ]);
                }),
            ]);
        };

        const filterBtnLabel = (group, kind) => {
            const total = group.length;
            const selected = group.reduce((n, p) => n + (state.selectedProviderIds.has(String(p.id)) ? 1 : 0), 0);
            if (total === 0) return 'No ' + kind;
            if (selected === total) return 'All ' + kind;
            if (selected === 0) return 'No ' + kind;
            return selected + ' of ' + total;
        };

        const providerPopover = popoverFor(onlyProviders, 'providers');

        // Timezone dropdown — populated from Intl.supportedValuesOf when
        // available, otherwise a curated US list. Always include the
        // browser tz and UTC.
        const tzList = (() => {
            const seen = new Set();
            const out = [];
            const add = (z) => { if (z && !seen.has(z)) { seen.add(z); out.push(z); } };
            add(state.viewTimezone);
            try {
                if (typeof Intl.supportedValuesOf === 'function') {
                    Intl.supportedValuesOf('timeZone').forEach(add);
                }
            } catch (e) { /* noop */ }
            ['UTC', 'America/New_York', 'America/Chicago', 'America/Denver',
             'America/Phoenix', 'America/Los_Angeles', 'America/Anchorage',
             'Pacific/Honolulu'].forEach(add);
            return out;
        })();
        const tzSelect = el('select', {
            onchange: (e) => {
                state.viewTimezone = e.target.value;
                refreshEvents().then(renderAll);
            },
        }, tzList.map(z => el('option', { value: z, selected: z === state.viewTimezone }, z)));

        // Transparent full-viewport overlay when a filter popover is open.
        // Catches clicks anywhere in the iframe (including above the popover
        // where the document-level click listener sometimes misses) so users
        // can dismiss with a single click anywhere outside.
        const overlay = state.openFilter
            ? el('div', {
                class: 'av-popover-overlay',
                onclick: () => { state.openFilter = null; renderAll(); },
            })
            : null;

        return el('div', { class: 'av-toolbar' }, [
            overlay,
            el('div', { class: 'left' }, [
                el('button', { class: 'av-btn', onclick: () => { state.weekStart = weekStartOf(new Date()); renderAll(); } }, 'Today'),
                el('button', {
                    class: 'av-btn av-icon-btn',
                    title: 'Previous week',
                    onclick: () => { state.weekStart = addDays(state.weekStart, -7); renderAll(); },
                }, '‹'),
                el('button', {
                    class: 'av-btn av-icon-btn',
                    title: 'Next week',
                    onclick: () => { state.weekStart = addDays(state.weekStart, 7); renderAll(); },
                }, '›'),
                el('div', { class: 'av-week-label' }, fmtWeekRange(state.weekStart)),
                dateJump,
            ]),
            el('div', { class: 'right' }, [
                el('div', { class: 'av-popover-anchor' }, [
                    el('button', {
                        class: 'av-btn',
                        onclick: (e) => {
                            e.stopPropagation();
                            state.openFilter = state.openFilter === 'providers' ? null : 'providers';
                            renderAll();
                        },
                    }, 'Providers: ' + filterBtnLabel(onlyProviders, 'providers') + ' ▾'),
                    providerPopover,
                ]),
                el('label', { style: { fontSize: '11.5px', fontWeight: '600', color: '#5A6475', textTransform: 'uppercase', letterSpacing: '0.04em' } }, 'Timezone'),
                tzSelect,
                el('label', { style: { fontSize: '11.5px', fontWeight: '600', color: '#5A6475', textTransform: 'uppercase', letterSpacing: '0.04em' } }, 'Location'),
                locSelect,
            ]),
        ]);
    }

    // ---------------- Render: Week grid ----------------
    function renderGrid() {
        const wrap = el('div', { class: 'av-grid-wrap' });
        const grid = el('div', { class: 'av-grid' });

        // Header row (single grid: corner + 7 day headers).
        grid.appendChild(el('div', { class: 'av-day-corner' }));
        for (let i = 0; i < 7; i++) {
            const d = addDays(state.weekStart, i);
            const today = isSameDay(d, new Date());
            grid.appendChild(el('div', {
                class: 'av-day-header' + (today ? ' today' : ''),
                style: { gridColumn: String(i + 2) },
            }, [
                DAY_LABELS_SHORT[d.getDay()],
                el('strong', {}, String(d.getDate())),
            ]));
        }

        // Hour gutter cells (column 1, rows 2-25).
        for (let h = 0; h < 24; h++) {
            const label = h === 0 ? '12 AM' : (h < 12 ? h + ' AM' : (h === 12 ? '12 PM' : (h - 12) + ' PM'));
            grid.appendChild(el('div', { class: 'av-hour-cell', style: { gridRow: String(h + 2) } }, label));
        }

        // Day columns (each column 2-8, spanning rows 2-25).
        const rangeStart = state.weekStart;
        const rangeEnd = new Date(addDays(state.weekStart, 7).getTime() - 1);
        // Filter events by location and selected provider set.
        const filtered = state.events.filter(ev => {
            if (state.locationId && String(ev.location) !== String(state.locationId)) return false;
            if (ev.provider && !state.selectedProviderIds.has(String(ev.provider))) return false;
            return true;
        });
        // One tile per (provider record, occurrence) — sub-columns within each
        // day display each provider's events side-by-side.
        const occurrences = [];
        for (const ev of filtered) {
            for (const occ of expandOccurrences(ev, rangeStart, rangeEnd)) {
                occurrences.push({ event: ev, occ });
            }
        }

        // Stable order of providers to determine sub-column positions.
        const visibleProviders = state.providers
            .filter(p => state.selectedProviderIds.has(String(p.id)))
            .map(p => String(p.id));
        const subColumnCount = Math.max(1, visibleProviders.length);
        const subColumnIdx = new Map(visibleProviders.map((id, i) => [id, i]));

        for (let i = 0; i < 7; i++) {
            const dayDate = addDays(state.weekStart, i);
            const col = el('div', {
                class: 'av-day-col',
                dataset: { dayIndex: String(i) },
                style: { gridColumn: String(i + 2) },
            });
            attachDragHandlers(col, dayDate);

            // Sub-column dividers (visual only).
            for (let s = 1; s < subColumnCount; s++) {
                col.appendChild(el('div', {
                    class: 'av-provider-divider',
                    style: { left: 'calc(' + (s / subColumnCount * 100) + '% - 0.5px)' },
                }));
            }

            // Render occurrences whose start date matches this column.
            const dayOccs = occurrences.filter(o =>
                o.occ.start.getFullYear() === dayDate.getFullYear()
                && o.occ.start.getMonth() === dayDate.getMonth()
                && o.occ.start.getDate() === dayDate.getDate()
            );
            dayOccs.sort((a, b) => a.occ.start - b.occ.start);
            for (const item of dayOccs) {
                const provIdx = subColumnIdx.has(String(item.event.provider))
                    ? subColumnIdx.get(String(item.event.provider))
                    : 0;
                col.appendChild(renderEventTile(item.event, item.occ, provIdx, subColumnCount));
            }

            // Now-line on today's column
            if (isSameDay(dayDate, new Date())) {
                const now = new Date();
                const top = (now.getHours() + now.getMinutes() / 60) * HOUR_PX;
                col.appendChild(el('div', { class: 'av-now-line', style: { top: top + 'px' } }));
            }

            grid.appendChild(col);
        }
        wrap.appendChild(grid);
        return wrap;
    }

    function renderEventTile(event, occ, provIdx, subColumnCount) {
        const top = (occ.start.getHours() + occ.start.getMinutes() / 60) * HOUR_PX;
        const heightPx = Math.max(20, ((occ.end - occ.start) / (60 * 1000)) / 60 * HOUR_PX);
        const isAvail = (event.calendarType || 'Clinic') === 'Clinic';
        // Reserve a fixed-pixel gutter on the right of every day column so
        // there's an always-visible empty strip the user can mousedown into
        // to drag-create a new event (matches Google Calendar's pattern).
        const gutterPx = DRAG_GUTTER_PX;
        const fraction = 1 / subColumnCount;
        const tile = el('div', {
            class: 'av-event ' + (isAvail ? 'available' : 'block'),
            style: {
                top: top + 'px',
                height: heightPx + 'px',
                left: 'calc((100% - ' + gutterPx + 'px) * ' + (provIdx * fraction) + ' + 2px)',
                right: 'auto',
                width: 'calc((100% - ' + gutterPx + 'px) * ' + fraction + ' - 4px)',
            },
            onclick: (ev) => { ev.stopPropagation(); openTilePopup(event.id, occ); },
        }, [
            el('div', { class: 'ev-title' }, [
                event.title || (isAvail ? 'Available' : 'Block'),
                event.recurrence?.type ? el('span', { class: 'ev-recurring', title: 'Recurring' }, '↻') : null,
            ]),
            el('div', { class: 'ev-time' }, fmtTime12(occ.start) + ' – ' + fmtTime12(occ.end)),
            event.provider ? el('div', { class: 'ev-providers' }, providerName(event.provider)) : null,
        ]);
        return tile;
    }

    // ---------------- Drag-create ----------------
    // mousedown on a day column starts a drag; mousemove + mouseup are handled
    // at the document level so the drag works even when the cursor leaves the
    // column or the visible viewport. The grid wrap auto-scrolls when the
    // cursor approaches the top/bottom edge.
    let drag = null;
    let autoScrollRaf = null;
    let autoScrollDir = 0;

    function attachDragHandlers(col, dayDate) {
        col.addEventListener('mousedown', (e) => {
            if (e.button !== 0) return;
            // Mousedown on an event tile opens the tile popup (handled by the
            // tile's own onclick) — never start a drag-create from there.
            // Users get a visible right-side gutter on every day for drag-create.
            if (e.target.closest('.av-event')) return;
            const rect = col.getBoundingClientRect();
            const startMin = snapToMinutes((e.clientY - rect.top) / HOUR_PX * 60);
            drag = {
                col, dayDate,
                startMin,
                endMin: startMin + SNAP_MIN,
                rect: el('div', { class: 'av-drag-rect' }),
            };
            updateDragRect();
            col.appendChild(drag.rect);
            e.preventDefault();
        });
    }

    function snapToMinutes(min) {
        return Math.max(0, Math.min(24 * 60, Math.round(min / SNAP_MIN) * SNAP_MIN));
    }
    function clamp(n, lo, hi) { return Math.max(lo, Math.min(hi, n)); }

    function updateDragRect() {
        if (!drag || !drag.rect) return;
        const lo = Math.min(drag.startMin, drag.endMin);
        const hi = Math.max(drag.startMin, drag.endMin);
        drag.rect.style.top = (lo / 60 * HOUR_PX) + 'px';
        drag.rect.style.height = ((hi - lo) / 60 * HOUR_PX) + 'px';
    }

    function gridWrap() { return app.querySelector('.av-grid-wrap'); }

    function tickAutoScroll() {
        autoScrollRaf = null;
        if (!drag || !autoScrollDir) return;
        const wrap = gridWrap();
        if (wrap) wrap.scrollTop = clamp(wrap.scrollTop + autoScrollDir * 18, 0, wrap.scrollHeight);
        // Re-trigger drag-rect update based on the cached last clientY.
        if (drag._lastClientY != null) updateDragFromClientY(drag._lastClientY);
        autoScrollRaf = requestAnimationFrame(tickAutoScroll);
    }

    function updateDragFromClientY(clientY) {
        if (!drag) return;
        drag._lastClientY = clientY;
        const colRect = drag.col.getBoundingClientRect();
        const mins = snapToMinutes((clientY - colRect.top) / HOUR_PX * 60);
        drag.endMin = clamp(mins, 0, 24 * 60);
        updateDragRect();
    }

    document.addEventListener('mousemove', (e) => {
        if (!drag) return;
        updateDragFromClientY(e.clientY);
        // Auto-scroll the grid when the cursor is near top/bottom edge of the wrap.
        const wrap = gridWrap();
        if (wrap) {
            const wrapRect = wrap.getBoundingClientRect();
            const nearTop = e.clientY - wrapRect.top;
            const nearBottom = wrapRect.bottom - e.clientY;
            const margin = 40;
            let dir = 0;
            if (nearTop < margin) dir = -1;
            else if (nearBottom < margin) dir = 1;
            if (dir !== autoScrollDir) {
                autoScrollDir = dir;
                if (dir !== 0 && autoScrollRaf == null) autoScrollRaf = requestAnimationFrame(tickAutoScroll);
            }
        }
    });

    // Dismiss anything floating (filter popover, tile popup, scope prompt,
    // or the create/edit modal) when the user clicks outside the iframe.
    // Inside the iframe, each layer's own backdrop already handles dismissal.
    const dismissFloatingLayers = () => {
        let changed = false;
        if (state.openFilter) { state.openFilter = null; changed = true; }
        if (state.tilePopup) { state.tilePopup = null; changed = true; }
        if (state.scopePrompt) { state.scopePrompt = null; changed = true; }
        if (state.modal) { state.modal = null; changed = true; }
        if (changed) renderAll();
    };
    // Filter popover dismissal still uses document-level clicks within the
    // iframe (modals/tilepopups have their own backdrop handlers there).
    document.addEventListener('click', () => {
        if (state.openFilter) {
            state.openFilter = null;
            renderAll();
        }
    });
    // Same-origin parent page hosts the iframe — clicks there don't bubble in.
    // Mirror the dismiss handler onto the parent document so any click outside
    // the iframe (page header, tab bar, surrounding chrome) closes whichever
    // floating layer is open.
    try {
        if (window.parent && window.parent !== window && window.parent.document) {
            window.parent.document.addEventListener('click', dismissFloatingLayers, true);
        }
    } catch (e) { /* cross-origin parent — nothing we can do */ }

    document.addEventListener('mouseup', () => {
        if (!drag) return;
        autoScrollDir = 0;
        if (autoScrollRaf != null) { cancelAnimationFrame(autoScrollRaf); autoScrollRaf = null; }
        const lo = Math.min(drag.startMin, drag.endMin);
        const hi = Math.max(drag.startMin, drag.endMin);
        if (drag.rect && drag.rect.parentNode) drag.rect.parentNode.removeChild(drag.rect);
        const dayDate = drag.dayDate;
        drag = null;
        if (hi - lo < SNAP_MIN) return;
        if (!state.locationId) {
            alert('Pick a specific location before creating availability.');
            return;
        }
        openCreateModal(dayDate, lo, hi);
    });

    // ---------------- Modal: Create / Edit ----------------
    function defaultRecurrenceFromDate(date) {
        return {
            mode: 'none',
            customRepeatFreq: 'WEEKLY',
            customInterval: 1,
            customDays: [dayOfWeekCode(date)],
            customEnds: 'never',
            customEndDate: dateOnly(addDays(date, 30)),
            customCount: 4,
        };
    }

    function openCreateModal(dayDate, startMin, endMin) {
        // Pre-select whoever is currently active in the top-level provider
        // filter — if the user has narrowed the grid to a few providers, the
        // event they're about to draft almost certainly applies to them.
        const seededProviders = state.providers
            .map(p => String(p.id))
            .filter(id => state.selectedProviderIds.has(id));
        state.modal = {
            mode: 'create',
            seriesRecords: [],
            originalEvent: null,
            occurrenceDate: null,
            form: {
                date: dateOnly(dayDate),
                startTime: pad2(Math.floor(startMin / 60)) + ':' + pad2(startMin % 60),
                endTime: pad2(Math.floor(endMin / 60)) + ':' + pad2(endMin % 60),
                title: '',
                type: TYPE_AVAILABLE,
                providers: seededProviders,
                allowedNoteTypes: state.noteTypes.map(nt => String(nt.id)), // default all
                recurrence: defaultRecurrenceFromDate(dayDate),
            },
            error: '',
        };
        state.scopePrompt = null;
        renderAll();
    }

    function openEditModal(masterId, scope, occurrence, recordsOverride) {
        // recordsOverride lets the scope prompt narrow the edit to a single
        // provider's records on a multi-provider series.
        const records = recordsOverride && recordsOverride.length
            ? recordsOverride
            : seriesFor(masterId);
        if (!records.length) return;
        const ref = records[0];
        const startDt = parseLocalISO(ref.startTime);
        // For 'this' and 'following' scopes, the form's date defaults to the
        // clicked occurrence — the new fragment starts from there. For 'all'
        // we keep the original series start.
        const occDate = (scope === 'this' || scope === 'following') && occurrence
            ? occurrence.start
            : startDt;
        const occHHMMStart = startDt ? pad2(startDt.getHours()) + ':' + pad2(startDt.getMinutes()) : '00:00';
        const endDt = parseLocalISO(ref.endTime);
        // Clamp cross-midnight ends to 23:59 for the same-day form. Some
        // existing data has ends_at on the next day (legacy "all-day until
        // midnight" entries) which would otherwise fail the start<end check.
        let occHHMMEnd;
        if (startDt && endDt) {
            const sameDay = startDt.getFullYear() === endDt.getFullYear()
                && startDt.getMonth() === endDt.getMonth()
                && startDt.getDate() === endDt.getDate();
            occHHMMEnd = sameDay
                ? pad2(endDt.getHours()) + ':' + pad2(endDt.getMinutes())
                : '23:59';
        } else {
            occHHMMEnd = endDt ? pad2(endDt.getHours()) + ':' + pad2(endDt.getMinutes()) : '00:00';
        }

        const recObj = ref.recurrence || {};
        const recMode = inferRecurrenceMode(ref);

        state.modal = {
            mode: 'edit',
            scope: scope, // 'all' | 'this' | 'following'
            seriesRecords: records,
            originalEvent: ref,
            occurrenceDate: occDate,
            form: {
                date: dateOnly(occDate),
                startTime: occHHMMStart,
                endTime: occHHMMEnd,
                title: ref.title || '',
                type: ref.calendarType === 'Admin' ? TYPE_BLOCK : TYPE_AVAILABLE,
                providers: providersInSeries(records),
                allowedNoteTypes: (ref.allowedNoteTypes || []).slice(),
                recurrence: scope === 'this'
                    ? Object.assign(defaultRecurrenceFromDate(occDate), { mode: 'none' })
                    : Object.assign(defaultRecurrenceFromDate(parseLocalISO(ref.startTime) || occDate), {
                        mode: recMode,
                        customRepeatFreq: recObj.type === 'DAILY' ? 'DAILY' : 'WEEKLY',
                        customInterval: Math.max(1, +(recObj.interval || 0) || 1),
                        customDays: (ref.daysOfWeek && ref.daysOfWeek.length ? ref.daysOfWeek.slice() : [dayOfWeekCode(parseLocalISO(ref.startTime) || occDate)]),
                        customEnds: recObj.endDate ? 'on' : 'never',
                        customEndDate: recObj.endDate ? recObj.endDate.slice(0, 10) : dateOnly(addDays(parseLocalISO(ref.startTime) || occDate, 30)),
                        customCount: 4,
                    }),
            },
            error: '',
        };
        state.scopePrompt = null;
        renderAll();
    }

    function inferRecurrenceMode(ref) {
        const rec = ref.recurrence || {};
        if (!rec.type) return 'none';
        const type = rec.type;
        const interval = +(rec.interval || 1) || 1;
        const days = (ref.daysOfWeek || []).slice().sort();
        const startDt = parseLocalISO(ref.startTime);
        const startDayCode = startDt ? dayOfWeekCode(startDt) : '';
        if (type === 'DAILY' && interval === 1) return 'daily';
        if (type === 'WEEKLY' && interval === 1) {
            const weekdaysSet = ['MO', 'TU', 'WE', 'TH', 'FR'].sort().join(',');
            if (days.join(',') === weekdaysSet) return 'every_weekday';
            if (days.length === 1 && days[0] === startDayCode) return 'weekly_day';
            if (days.length === 0) return 'weekly_day';
        }
        return 'custom';
    }

    function openTilePopup(masterId, occurrence) {
        state.tilePopup = { masterId, occurrence };
        state.scopePrompt = null;
        state.modal = null;
        renderAll();
    }

    function closeTilePopup() {
        state.tilePopup = null;
        renderAll();
    }

    function recurrenceSummary(ref) {
        const r = ref?.recurrence || {};
        if (!r.type) return '';
        const interval = +(r.interval || 1) || 1;
        if (r.type === 'DAILY') return interval > 1 ? 'Every ' + interval + ' days' : 'Daily';
        if (r.type === 'WEEKLY') {
            const days = (ref.daysOfWeek || []);
            if (days.length === 5 && ['MO','TU','WE','TH','FR'].every(d => days.includes(d))) {
                return interval > 1 ? 'Every ' + interval + ' weeks (Mon–Fri)' : 'Every weekday (Mon–Fri)';
            }
            if (days.length) {
                const names = days.map(d => DAY_LABELS_LONG[DAY_CODES.indexOf(d)] || d).join(', ');
                return interval > 1 ? 'Every ' + interval + ' weeks on ' + names : 'Weekly on ' + names;
            }
            return interval > 1 ? 'Every ' + interval + ' weeks' : 'Weekly';
        }
        return '';
    }

    function fmtDateLong(d) {
        return DAY_LABELS_LONG[d.getDay()] + ', ' + MONTH_LABELS[d.getMonth()] + ' ' + d.getDate() + ', ' + d.getFullYear();
    }

    function renderTilePopup() {
        if (!state.tilePopup) return null;
        const { masterId, occurrence } = state.tilePopup;
        const records = seriesFor(masterId);
        if (!records.length) { state.tilePopup = null; return null; }
        const ref = records[0];
        const isRecurring = !!ref.recurrence?.type;
        const isAvail = (ref.calendarType || 'Clinic') === 'Clinic';
        const provNames = providersInSeries(records).map(providerName).join(', ');
        const noteTypes = (ref.allowedNoteTypes || []).map(noteTypeName).join(', ');
        const recurStr = isRecurring ? recurrenceSummary(ref) : '';

        return el('div', {
            class: 'av-modal-backdrop',
            onclick: (e) => { if (e.target.classList.contains('av-modal-backdrop')) closeTilePopup(); },
        }, [
            el('div', { class: 'av-modal av-tile-popup' }, [
                el('div', { class: 'tp-header' }, [
                    el('button', { title: 'Edit', onclick: () => onTilePopupAction('edit') }, '✎'),
                    el('button', { title: 'Delete', onclick: () => onTilePopupAction('delete') }, '🗑'),
                    el('button', { title: 'Close', onclick: () => closeTilePopup() }, '✕'),
                ]),
                el('h2', {}, ref.title || (isAvail ? 'Available' : 'Block')),
                el('div', { class: 'tp-meta' }, fmtDateLong(occurrence.start) + ' · ' + fmtTime12(occurrence.start) + ' – ' + fmtTime12(occurrence.end)),
                recurStr ? el('div', { class: 'tp-recur' }, ['↻ ', recurStr]) : null,
                el('div', { class: 'tp-row' }, [el('strong', {}, isAvail ? 'Available' : 'Block')]),
                provNames ? el('div', { class: 'tp-row' }, [el('strong', {}, 'Providers:'), ' ' + provNames]) : null,
                isAvail && noteTypes ? el('div', { class: 'tp-row' }, [el('strong', {}, 'Visit types:'), ' ' + noteTypes]) : null,
            ]),
        ]);
    }

    function onTilePopupAction(action) {
        const { masterId, occurrence } = state.tilePopup;
        state.tilePopup = null;
        const records = seriesFor(masterId);
        const isRecurring = !!records[0]?.recurrence?.type;
        const isMultiProvider = providersInSeries(records).length > 1;
        // The scope prompt drives the edit form's pre-population (which
        // providers to show, whether recurrence is locked). Show it whenever
        // there's a meaningful choice — recurring OR multi-provider.
        if (!isRecurring && !isMultiProvider) {
            if (action === 'edit') {
                openEditModal(masterId, 'all', occurrence);
            } else {
                doScopedDelete('all', records, occurrence);
            }
            return;
        }
        state.scopePrompt = { masterId, occurrence, action };
        renderAll();
    }

    async function doScopedDelete(scope, records, occurrence) {
        const isRecurring = !!records[0]?.recurrence?.type;
        const msg = scope === 'this'
            ? 'Delete this occurrence? This cannot be undone.'
            : scope === 'following'
                ? 'Delete this occurrence and all following occurrences? This cannot be undone.'
                : (isRecurring ? 'Delete the whole series? This cannot be undone.' : 'Delete this event? This cannot be undone.');
        if (!confirm(msg)) { renderAll(); return; }
        state.saving = true; renderAll();
        const deletedIds = new Set();
        const truncations = {};
        try {
            if (scope === 'all' || !isRecurring) {
                for (const rec of records) {
                    await apiCall('/plugin-io/api/provider_availability_manager/events', {
                        method: 'DELETE',
                        body: JSON.stringify({ eventId: rec.id }),
                    });
                    deletedIds.add(String(rec.id));
                }
            } else if (scope === 'following') {
                // this-and-following: truncate the covering segment per
                // provider so it ends the day BEFORE the clicked occurrence.
                // No continuation, no replacement.
                const byProvider = {};
                for (const r of records) {
                    const key = String(r.provider || '');
                    (byProvider[key] = byProvider[key] || []).push(r);
                }
                for (const key of Object.keys(byProvider)) {
                    const target = byProvider[key].find(r => recordCovers(r, occurrence.start));
                    if (target) {
                        const t = await truncateBefore(target, occurrence.start);
                        if (t) truncations[t.id] = t.endDate;
                    }
                }
            } else {
                // this-only: only split the segment per provider that actually
                // covers the occurrence date. Previously this looped every
                // consolidated record, which clobbered the start/end bounds of
                // earlier segments and revived prior this-only deletions.
                const byProvider = {};
                for (const r of records) {
                    const key = String(r.provider || '');
                    (byProvider[key] = byProvider[key] || []).push(r);
                }
                for (const key of Object.keys(byProvider)) {
                    const target = byProvider[key].find(r => recordCovers(r, occurrence.start));
                    if (target) {
                        const t = await splitOutOccurrence(target, occurrence.start, null);
                        if (t) truncations[t.id] = t.endDate;
                    }
                }
            }
            await refreshEvents(deletedIds, truncations);
        } catch (err) {
            alert('Delete failed: ' + err.message);
        }
        state.saving = false;
        renderAll();
    }

    function renderModal() {
        if (state.scopePrompt) return renderScopePrompt();
        if (!state.modal) return null;
        const f = state.modal.form;
        const isEdit = state.modal.mode === 'edit';

        const setForm = (patch) => {
            Object.assign(state.modal.form, patch);
            renderAll();
        };
        const setRec = (patch) => {
            Object.assign(state.modal.form.recurrence, patch);
            renderAll();
        };

        const makeChips = (group) => group.map(p => {
            const sel = f.providers.includes(String(p.id));
            return el('span', {
                class: 'av-chip' + (sel ? ' active' : ''),
                onclick: () => {
                    const id = String(p.id);
                    const next = sel ? f.providers.filter(x => x !== id) : f.providers.concat(id);
                    setForm({ providers: next });
                },
            }, p.full_name || p.name);
        });
        const providerChips = makeChips(state.providers);

        const noteTypeChips = state.noteTypes.map(nt => {
            const id = String(nt.id);
            const sel = f.allowedNoteTypes.includes(id);
            return el('span', {
                class: 'av-chip' + (sel ? ' active' : ''),
                onclick: () => {
                    const next = sel ? f.allowedNoteTypes.filter(x => x !== id) : f.allowedNoteTypes.concat(id);
                    setForm({ allowedNoteTypes: next });
                },
            }, nt.name);
        });

        const recurrenceLabel = (() => {
            const date = parseLocalISO(f.date);
            const dn = date ? DAY_LABELS_LONG[date.getDay()] : '';
            return {
                none: 'Does not repeat',
                daily: 'Daily',
                weekly_day: 'Weekly on ' + dn,
                every_weekday: 'Every weekday (Mon–Fri)',
                custom: 'Custom…',
            };
        })();

        const recOptions = ['none', 'daily', 'weekly_day', 'every_weekday', 'custom'].map(m =>
            el('option', { value: m, selected: f.recurrence.mode === m }, recurrenceLabel[m])
        );

        const customSection = f.recurrence.mode === 'custom' ? renderCustomRecurrence(f.recurrence, setRec) : null;

        const isAvail = f.type === TYPE_AVAILABLE;

        const lockedInThisOnly = isEdit && state.modal.scope === 'this';
        const recurrenceRow = lockedInThisOnly
            ? el('div', { class: 'av-help' }, 'Editing a single occurrence — recurrence is fixed to "Does not repeat" for this instance.')
            : el('div', { class: 'av-form-row' }, [
                el('label', {}, 'Repeats'),
                el('select', { onchange: e => setRec({ mode: e.target.value }) }, recOptions),
                customSection,
            ]);

        const modalChildren = [
            state.modal.error ? el('div', { class: 'av-error' }, state.modal.error) : null,
            el('div', { class: 'av-form-row' }, [
                el('label', {}, 'Type'),
                // Type drives which calendar (Clinic vs Administrative) the
                // event lives on. The edit paths (editAll PATCH, splitOutOccurrence)
                // don't move events between calendars, so changing Type here
                // would be a silent no-op — the slot filter classifies windows
                // by calendar, not title, and the toggle would mislead the user
                // into thinking they marked a window Busy when slots stay
                // bookable. Lock it in edit mode; to change Type, delete and
                // recreate.
                el('div', { class: 'av-toggle' }, [
                    el('button', {
                        type: 'button',
                        class: f.type === TYPE_AVAILABLE ? 'active' : '',
                        disabled: isEdit,
                        title: isEdit ? 'Delete and recreate to change type' : '',
                        onclick: () => { if (!isEdit) setForm({ type: TYPE_AVAILABLE }); },
                    }, 'Available'),
                    el('button', {
                        type: 'button',
                        class: f.type === TYPE_BLOCK ? 'active' : '',
                        disabled: isEdit,
                        title: isEdit ? 'Delete and recreate to change type' : '',
                        onclick: () => { if (!isEdit) setForm({ type: TYPE_BLOCK }); },
                    }, 'Block'),
                ]),
            ]),
            !isAvail ? el('div', { class: 'av-form-row' }, [
                el('label', {}, 'Title'),
                el('input', {
                    type: 'text', value: f.title, placeholder: 'e.g. Lunch, Admin time',
                    oninput: e => { f.title = e.target.value; },
                }),
            ]) : null,
            el('div', { class: 'av-form-row' }, [
                el('label', {}, 'Date'),
                el('input', { type: 'date', value: f.date, oninput: e => { f.date = e.target.value; renderAll(); } }),
            ]),
            el('div', { class: 'av-time-row' }, [
                el('div', { class: 'av-form-row' }, [
                    el('label', {}, 'Start'),
                    el('input', { type: 'time', step: '300', value: f.startTime, oninput: e => { f.startTime = e.target.value; } }),
                ]),
                el('div', { class: 'av-form-row' }, [
                    el('label', {}, 'End'),
                    el('input', { type: 'time', step: '300', value: f.endTime, oninput: e => { f.endTime = e.target.value; } }),
                ]),
            ]),
            providerChips.length ? el('div', { class: 'av-form-row' }, [
                el('label', {}, 'Providers'),
                el('div', { class: 'av-multi' }, providerChips),
            ]) : null,
            isAvail ? el('div', { class: 'av-form-row' }, [
                el('label', {}, 'Allowed visit types'),
                el('div', { class: 'av-multi' }, noteTypeChips),
            ]) : null,
            recurrenceRow,
            el('div', { class: 'av-modal-actions' }, [
                isEdit ? el('button', { class: 'av-btn danger left', onclick: () => onDelete() }, 'Delete') : null,
                state.saving ? el('span', { class: 'av-saving' }, 'Saving…') : null,
                el('button', { class: 'av-btn', onclick: () => closeModal() }, 'Cancel'),
                el('button', { class: 'av-btn primary', disabled: state.saving, onclick: () => onSave() }, isEdit ? 'Save' : 'Create'),
            ]),
        ];

        return el('div', { class: 'av-modal-backdrop', onclick: (e) => { if (e.target.classList.contains('av-modal-backdrop')) closeModal(); } }, [
            el('div', { class: 'av-modal' }, modalChildren),
        ]);
    }

    function renderCustomRecurrence(rec, setRec) {
        const dayBtns = DAY_CODES.map((c, i) => el('button', {
            type: 'button',
            class: rec.customDays.includes(c) ? 'active' : '',
            onclick: () => {
                const next = rec.customDays.includes(c)
                    ? rec.customDays.filter(x => x !== c)
                    : rec.customDays.concat(c);
                setRec({ customDays: next });
            },
        }, DAY_LABELS_INITIAL[i]));

        return el('div', { style: { background: '#FAFBFC', padding: '12px', borderRadius: '8px', border: '1.5px solid #E0E4EA', marginTop: '8px' } }, [
            el('div', { style: { display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '12px' } }, [
                el('span', { style: { fontSize: '13px', color: '#5A6475' } }, 'Repeat every'),
                el('input', {
                    type: 'number', min: '1', max: '99', value: String(rec.customInterval),
                    style: { width: '60px' },
                    oninput: e => setRec({ customInterval: Math.max(1, +e.target.value || 1) }),
                }),
                el('select', {
                    onchange: e => setRec({ customRepeatFreq: e.target.value }),
                }, [
                    el('option', { value: 'DAILY', selected: rec.customRepeatFreq === 'DAILY' }, rec.customInterval === 1 ? 'day' : 'days'),
                    el('option', { value: 'WEEKLY', selected: rec.customRepeatFreq === 'WEEKLY' }, rec.customInterval === 1 ? 'week' : 'weeks'),
                ]),
            ]),
            rec.customRepeatFreq === 'WEEKLY' ? el('div', { style: { marginBottom: '12px' } }, [
                el('div', { style: { fontSize: '11.5px', fontWeight: '600', color: '#5A6475', textTransform: 'uppercase', letterSpacing: '0.04em', marginBottom: '6px' } }, 'Repeat on'),
                el('div', { class: 'av-day-pickers' }, dayBtns),
            ]) : null,
            el('div', {}, [
                el('div', { style: { fontSize: '11.5px', fontWeight: '600', color: '#5A6475', textTransform: 'uppercase', letterSpacing: '0.04em', marginBottom: '6px' } }, 'Ends'),
                el('div', { class: 'av-radio-row' }, [
                    el('input', { type: 'radio', name: 'av-ends', id: 'ends-never', checked: rec.customEnds === 'never', onchange: () => setRec({ customEnds: 'never' }) }),
                    el('label', { for: 'ends-never' }, 'Never'),
                ]),
                el('div', { class: 'av-radio-row' }, [
                    el('input', { type: 'radio', name: 'av-ends', id: 'ends-on', checked: rec.customEnds === 'on', onchange: () => setRec({ customEnds: 'on' }) }),
                    el('label', { for: 'ends-on' }, 'On'),
                    el('input', {
                        type: 'date', value: rec.customEndDate,
                        disabled: rec.customEnds !== 'on',
                        oninput: e => setRec({ customEndDate: e.target.value }),
                    }),
                ]),
                el('div', { class: 'av-radio-row' }, [
                    el('input', { type: 'radio', name: 'av-ends', id: 'ends-after', checked: rec.customEnds === 'after', onchange: () => setRec({ customEnds: 'after' }) }),
                    el('label', { for: 'ends-after' }, 'After'),
                    el('input', {
                        type: 'number', min: '1', max: '999', value: String(rec.customCount),
                        disabled: rec.customEnds !== 'after',
                        oninput: e => setRec({ customCount: Math.max(1, +e.target.value || 1) }),
                    }),
                    el('span', { style: { fontSize: '13px', color: '#5A6475', marginLeft: '4px' } }, 'occurrences'),
                ]),
            ]),
        ]);
    }

    function renderScopePrompt() {
        if (!state.scopePrompt) return null;
        const { masterId, occurrence, action } = state.scopePrompt;
        const verb = action === 'delete' ? 'Delete' : 'Edit';

        const allRecords = seriesFor(masterId);
        const clickedEvent = state.events.find(e => String(e.id) === String(masterId));
        const clickedProviderId = clickedEvent ? String(clickedEvent.provider || '') : '';
        const seriesProviderIds = providersInSeries(allRecords);
        const isMultiProvider = seriesProviderIds.length > 1;
        const isRecurring = !!allRecords[0]?.recurrence?.type;
        const clickedProviderName = clickedProviderId ? providerName(clickedProviderId) : '';

        const sel = state.scopePrompt;
        // Default to the most cautious scope on each dimension.
        sel.timeScope = sel.timeScope || 'this';
        sel.providerScope = sel.providerScope || (isMultiProvider ? 'one' : 'all');

        const provLabel = clickedProviderName || 'this provider';
        const allProvLabel = seriesProviderIds.length + ' providers';

        // Resolve the current selection into the records list and dispatch.
        // The scope prompt drives the edit modal: provider scope narrows the
        // form's provider chips; time scope decides whether recurrence is
        // locked to "Does not repeat" for this occurrence.
        const handle = () => {
            state.scopePrompt = null;
            const records = sel.providerScope === 'one' && clickedProviderId
                ? allRecords.filter(r => String(r.provider) === clickedProviderId)
                : allRecords;
            if (action === 'edit') {
                openEditModal(masterId, sel.timeScope, occurrence, records);
            } else {
                doScopedDelete(sel.timeScope, records, occurrence);
            }
        };

        const setScope = (patch) => {
            Object.assign(sel, patch);
            renderAll();
        };

        const timeLabel = !isRecurring ? 'event'
            : sel.timeScope === 'all' ? 'all events'
            : sel.timeScope === 'following' ? 'this and following events'
            : 'this event';
        const confirmCta = (action === 'delete' ? 'Delete' : 'Edit')
            + ' ' + timeLabel
            + (isMultiProvider
                ? ' for ' + (sel.providerScope === 'one' ? provLabel : allProvLabel)
                : '');

        const heading = isRecurring ? verb + ' recurring event' : verb + ' multi-provider event';

        const groups = [];
        if (isRecurring) {
            groups.push(el('div', { class: 'av-scope-group' }, [
                el('div', { class: 'av-scope-label' }, 'Dates'),
                el('div', { class: 'av-toggle' }, [
                    el('button', {
                        type: 'button',
                        class: sel.timeScope === 'this' ? 'active' : '',
                        onclick: () => setScope({ timeScope: 'this' }),
                    }, 'This event'),
                    el('button', {
                        type: 'button',
                        class: sel.timeScope === 'following' ? 'active' : '',
                        onclick: () => setScope({ timeScope: 'following' }),
                    }, 'This and following events'),
                    el('button', {
                        type: 'button',
                        class: sel.timeScope === 'all' ? 'active' : '',
                        onclick: () => setScope({ timeScope: 'all' }),
                    }, 'All events'),
                ]),
            ]));
        }
        if (isMultiProvider) {
            groups.push(el('div', { class: 'av-scope-group' }, [
                el('div', { class: 'av-scope-label' }, 'Providers'),
                el('div', { class: 'av-toggle' }, [
                    el('button', {
                        type: 'button',
                        class: sel.providerScope === 'one' ? 'active' : '',
                        onclick: () => setScope({ providerScope: 'one' }),
                    }, provLabel + ' only'),
                    el('button', {
                        type: 'button',
                        class: sel.providerScope === 'all' ? 'active' : '',
                        onclick: () => setScope({ providerScope: 'all' }),
                    }, 'All ' + allProvLabel),
                ]),
            ]));
        }

        return el('div', {
            class: 'av-modal-backdrop',
            onclick: (e) => { if (e.target.classList.contains('av-modal-backdrop')) { state.scopePrompt = null; renderAll(); } },
        }, [
            el('div', { class: 'av-modal av-scope-modal' }, [
                el('h2', {}, heading),
                el('div', { class: 'subtitle' }, 'Apply this ' + (action === 'delete' ? 'deletion' : 'edit') + ' to:'),
                ...groups,
                el('div', { class: 'av-scope-actions' }, [
                    el('button', { class: 'av-btn', onclick: () => { state.scopePrompt = null; renderAll(); } }, 'Cancel'),
                    el('button', {
                        class: 'av-btn primary',
                        onclick: handle,
                    }, confirmCta),
                ]),
            ]),
        ]);
    }

    function closeModal() {
        state.modal = null;
        state.scopePrompt = null;
        state.error = '';
        renderAll();
    }

    // ---------------- Save / Delete ----------------
    function buildRecurrencePayload(form) {
        const startDt = parseLocalISO(form.date + 'T' + form.startTime);
        const mode = form.recurrence.mode;
        if (mode === 'none') return {};
        if (mode === 'daily') return { frequency: 'DAILY', interval: 1, days: [], endsAt: null };
        if (mode === 'weekly_day') return {
            frequency: 'WEEKLY', interval: 1,
            days: [dayOfWeekCode(startDt)], endsAt: null,
        };
        if (mode === 'every_weekday') return {
            frequency: 'WEEKLY', interval: 1,
            days: ['MO', 'TU', 'WE', 'TH', 'FR'], endsAt: null,
        };
        // custom
        const r = form.recurrence;
        const days = r.customRepeatFreq === 'WEEKLY' ? r.customDays.slice() : [];
        let endsAt = null;
        if (r.customEnds === 'on') {
            endsAt = r.customEndDate + 'T23:59';
        } else if (r.customEnds === 'after') {
            const count = Math.max(1, +r.customCount || 1);
            // Approximate ends_at by computing the date of the Nth occurrence.
            endsAt = computeNthOccurrence(form, r.customRepeatFreq, r.customInterval, days, count);
        }
        return {
            frequency: r.customRepeatFreq,
            interval: Math.max(1, +r.customInterval || 1),
            days: days,
            endsAt: endsAt,
        };
    }

    function computeNthOccurrence(form, freq, interval, days, count) {
        const start = parseLocalISO(form.date + 'T' + form.startTime);
        if (!start) return null;
        let occCount = 0;
        let d = startOfDay(start);
        // safety bound
        for (let step = 0; step < 5000 && occCount < count; step++) {
            let match = false;
            if (freq === 'DAILY') {
                const daysSince = step;
                match = (daysSince % interval === 0);
            } else if (freq === 'WEEKLY') {
                const wsd = weekStartOf(d);
                const wse = weekStartOf(start);
                const weeks = Math.round((wsd - wse) / (7 * MS_DAY));
                const wantedDays = days.length ? days : [dayOfWeekCode(start)];
                match = weeks % interval === 0 && wantedDays.includes(dayOfWeekCode(d));
            }
            if (match) {
                occCount++;
                if (occCount >= count) {
                    return dateOnly(d) + 'T23:59';
                }
            }
            d = addDays(d, 1);
        }
        return null;
    }

    async function onSave() {
        const f = state.modal.form;
        // Validation
        if (!f.title || !f.title.trim()) f.title = f.type === TYPE_AVAILABLE ? 'Available' : 'Block';
        if (!f.providers.length) {
            state.modal.error = 'Pick at least one provider.';
            renderAll();
            return;
        }
        if (f.startTime >= f.endTime) {
            state.modal.error = 'End time must be after start time.';
            renderAll();
            return;
        }
        state.modal.error = '';
        state.saving = true;
        renderAll();

        try {
            let truncations = {};
            const isRecurring = !!state.modal.seriesRecords?.[0]?.recurrence?.type;
            if (state.modal.mode === 'create') {
                await createSeries(f);
            } else if (state.modal.scope === 'all' || !isRecurring) {
                // Mirror the doScopedDelete guard. Without `!isRecurring`,
                // non-recurring events fall into editThisOnly →
                // splitOutOccurrence, which PATCHes the original with its
                // OWN values (no-op for the user-visible content) and POSTs
                // a brand-new one-off — silently duplicating the event on
                // every save.
                await editAll(f, state.modal.seriesRecords);
            } else if (state.modal.scope === 'following') {
                truncations = await editThisAndFollowing(f, state.modal.seriesRecords, state.modal.occurrenceDate);
            } else {
                await editThisOnly(f, state.modal.seriesRecords, state.modal.occurrenceDate);
            }
            await refreshEvents(undefined, truncations);
            state.saving = false;
            state.modal = null;
            renderAll();
        } catch (err) {
            console.error(err);
            state.saving = false;
            state.modal.error = 'Save failed: ' + err.message;
            renderAll();
        }
    }

    async function onDelete() {
        const records = state.modal.seriesRecords;
        const isRecurring = !!records[0]?.recurrence?.type;
        const scope = state.modal.scope || 'all';
        // Confirm message must match what the code is about to do.
        // Pre-fix, 'following' had no branch here and fell through to a
        // misleading "Delete the whole series?" prompt while the code
        // only removed the clicked occurrence.
        const confirmMsg = scope === 'this'
            ? 'Delete this occurrence?'
            : scope === 'following'
                ? 'Delete this occurrence and all following occurrences?'
                : (isRecurring ? 'Delete the whole series?' : 'Delete this event?');
        if (!confirm(confirmMsg + ' This cannot be undone.')) return;
        state.saving = true;
        renderAll();
        const deletedIds = new Set();
        const truncations = {};
        try {
            if (scope === 'all' || !isRecurring) {
                for (const rec of records) {
                    await apiCall('/plugin-io/api/provider_availability_manager/events', {
                        method: 'DELETE',
                        body: JSON.stringify({ eventId: rec.id }),
                    });
                    deletedIds.add(String(rec.id));
                }
            } else if (scope === 'following') {
                // this-and-following: truncate the covering segment per
                // provider to end the day before the clicked occurrence.
                // No continuation — mirrors doScopedDelete's following
                // branch. Pre-fix this scope fell through to the else
                // branch which created a continuation series and removed
                // only the one occurrence.
                const byProvider = {};
                for (const r of records) {
                    const key = String(r.provider || '');
                    (byProvider[key] = byProvider[key] || []).push(r);
                }
                for (const key of Object.keys(byProvider)) {
                    const target = byProvider[key].find(r => recordCovers(r, state.modal.occurrenceDate));
                    if (target) {
                        const t = await truncateBefore(target, state.modal.occurrenceDate);
                        if (t) truncations[t.id] = t.endDate;
                    }
                }
            } else {
                // this-only: only split the segment per provider that covers
                // the occurrence date — looping every consolidated record
                // clobbers earlier segments' bounds.
                const byProvider = {};
                for (const r of records) {
                    const key = String(r.provider || '');
                    (byProvider[key] = byProvider[key] || []).push(r);
                }
                for (const key of Object.keys(byProvider)) {
                    const target = byProvider[key].find(r => recordCovers(r, state.modal.occurrenceDate));
                    if (target) {
                        const t = await splitOutOccurrence(target, state.modal.occurrenceDate, null);
                        if (t) truncations[t.id] = t.endDate;
                    }
                }
            }
            await refreshEvents(deletedIds, truncations);
            state.saving = false;
            state.modal = null;
            renderAll();
        } catch (err) {
            console.error(err);
            state.saving = false;
            state.modal.error = 'Delete failed: ' + err.message;
            renderAll();
        }
    }

    async function createSeries(f) {
        const recurrence = buildRecurrencePayload(f);
        for (const provId of f.providers) {
            const calendarId = await ensureCalendar(provId, f.type, state.locationId);
            await apiCall('/plugin-io/api/provider_availability_manager/events', {
                method: 'POST',
                body: JSON.stringify(eventBody(f, calendarId)),
            });
        }
    }

    async function editAll(f, records) {
        const recurrence = buildRecurrencePayload(f);
        const newProviderIds = new Set(f.providers.map(String));
        // For records whose providers are still in the list: PATCH them.
        // For records whose providers are no longer in the list: DELETE them.
        // For new providers not in any record: CREATE them.
        const existingByProvider = {};
        for (const r of records) existingByProvider[String(r.provider)] = (existingByProvider[String(r.provider)] || []).concat(r);

        for (const provId of Object.keys(existingByProvider)) {
            if (newProviderIds.has(provId)) {
                // PATCH all underlying records for this provider
                for (const rec of existingByProvider[provId]) {
                    const body = Object.assign({}, eventBodyForPatch(f, rec.calendarId), { eventId: rec.id });
                    await apiCall('/plugin-io/api/provider_availability_manager/events', {
                        method: 'PATCH',
                        body: JSON.stringify(body),
                    });
                }
            } else {
                // Delete all records for this provider
                for (const rec of existingByProvider[provId]) {
                    await apiCall('/plugin-io/api/provider_availability_manager/events', {
                        method: 'DELETE',
                        body: JSON.stringify({ eventId: rec.id }),
                    });
                }
            }
        }
        // New providers — create
        for (const provId of newProviderIds) {
            if (!existingByProvider[provId]) {
                const calendarId = await ensureCalendar(provId, f.type, state.locationId);
                await apiCall('/plugin-io/api/provider_availability_manager/events', {
                    method: 'POST',
                    body: JSON.stringify(eventBody(f, calendarId)),
                });
            }
        }
    }

    function eventBodyForPatch(f, calendarId) {
        // Same shape minus calendar (PATCH expects eventId). The server's PATCH
        // overwrites the recurrence/days/etc to whatever we pass.
        return eventBody(f, calendarId);
    }

    // "This and following events": truncate each existing provider's covering
    // segment to end the day before the occurrence, then create a new series
    // for the requested providers starting at the occurrence with the form's
    // values. Returns the truncations so refreshEvents can re-assert them
    // against any stale read replica.
    async function editThisAndFollowing(f, records, occurrenceDate) {
        const truncations = {};
        const newProviderIds = new Set(f.providers.map(String));

        const existingByProvider = {};
        for (const r of records) {
            existingByProvider[String(r.provider)] =
                (existingByProvider[String(r.provider)] || []).concat(r);
        }

        // Truncate each existing segment that covers the occurrence date.
        for (const provId of Object.keys(existingByProvider)) {
            const target = existingByProvider[provId].find(r => recordCovers(r, occurrenceDate));
            if (target) {
                const t = await truncateBefore(target, occurrenceDate);
                if (t) truncations[t.id] = t.endDate;
            }
        }

        // Create the new series for the form's providers starting at the
        // occurrence date with the form's recurrence/values.
        const newForm = Object.assign({}, f, { date: dateOnly(occurrenceDate) });
        for (const provId of newProviderIds) {
            const calendarId = await ensureCalendar(provId, f.type, state.locationId);
            await apiCall('/plugin-io/api/provider_availability_manager/events', {
                method: 'POST',
                body: JSON.stringify(eventBody(newForm, calendarId)),
            });
        }

        return truncations;
    }

    async function editThisOnly(f, records, occurrenceDate) {
        // For each underlying record, split it: truncate the original to end the
        // day before the occurrence, create a one-off non-recurring event with
        // the new values for that occurrence, then create a new recurring series
        // continuing the day after.
        const newProviderIds = new Set(f.providers.map(String));
        const existingByProvider = {};
        for (const r of records) existingByProvider[String(r.provider)] = (existingByProvider[String(r.provider)] || []).concat(r);

        for (const provId of newProviderIds) {
            const recs = existingByProvider[provId] || [];
            // Find the record whose date range covers occurrenceDate; if none, split first record.
            const target = recs.find(r => recordCovers(r, occurrenceDate)) || recs[0];
            if (target) {
                await splitOutOccurrence(target, occurrenceDate, f);
            } else {
                // No existing record for this provider: just create the one-off
                const calendarId = await ensureCalendar(provId, f.type, state.locationId);
                const oneOff = Object.assign({}, f, { recurrence: { mode: 'none' } });
                await apiCall('/plugin-io/api/provider_availability_manager/events', {
                    method: 'POST',
                    body: JSON.stringify(eventBody(oneOff, calendarId)),
                });
            }
        }
        // Providers removed: split out only the segment that covers this
        // occurrence (looping every record would clobber earlier segments'
        // bounds and revive prior overrides).
        for (const provId of Object.keys(existingByProvider)) {
            if (!newProviderIds.has(provId)) {
                const target = existingByProvider[provId].find(r => recordCovers(r, occurrenceDate));
                if (target) await splitOutOccurrence(target, occurrenceDate, null);
            }
        }
    }

    function recordCovers(record, occDate) {
        const startDt = parseLocalISO(record.startTime);
        const recEndDt = parseLocalISO(record.recurrence?.endDate);
        if (!startDt) return false;
        if (occDate < startOfDay(startDt)) return false;
        if (recEndDt && occDate > recEndDt) return false;
        return true;
    }

    // Truncate a record's recurrence to end the day BEFORE the given date.
    // Returns {id, endDate} so the caller can re-assert the change against a
    // stale read replica response (see refreshEvents).
    async function truncateBefore(record, occurrenceDate) {
        const dayBefore = addDays(startOfDay(occurrenceDate), -1);
        const truncatedEnd = dateOnly(dayBefore) + 'T23:59';
        await apiCall('/plugin-io/api/provider_availability_manager/events', {
            method: 'PATCH',
            body: JSON.stringify({
                eventId: record.id,
                timezone: state.viewTimezone || undefined,
                title: record.title,
                startTime: record.startTime,
                endTime: record.endTime,
                recurrenceFrequency: record.recurrence?.type || null,
                recurrenceInterval: record.recurrence?.interval || null,
                recurrenceDays: (record.daysOfWeek || []).slice(),
                recurrenceEndsAt: truncatedEnd,
                allowedNoteTypes: record.allowedNoteTypes || [],
            }),
        });
        return { id: String(record.id), endDate: truncatedEnd };
    }

    async function splitOutOccurrence(record, occurrenceDate, replacementForm) {
        // Truncate original to end day-before; create one-off; create new series day-after.
        const occDay = startOfDay(occurrenceDate);
        const dayBefore = addDays(occDay, -1);
        const dayAfter = addDays(occDay, 1);
        const startDt = parseLocalISO(record.startTime);
        const endDt = parseLocalISO(record.endTime);
        const duration = endDt - startDt;

        // 1) Truncate original: PATCH the original event with recurrence_ends_at = end of dayBefore
        const truncatedEnd = dateOnly(dayBefore) + 'T23:59';
        const truncatedBody = {
            eventId: record.id,
            timezone: state.viewTimezone || undefined,
            title: record.title,
            startTime: record.startTime,
            endTime: record.endTime,
            recurrenceFrequency: record.recurrence?.type || null,
            recurrenceInterval: record.recurrence?.interval || null,
            recurrenceDays: (record.daysOfWeek || []).slice(),
            recurrenceEndsAt: truncatedEnd,
            allowedNoteTypes: record.allowedNoteTypes || [],
        };
        await apiCall('/plugin-io/api/provider_availability_manager/events', {
            method: 'PATCH',
            body: JSON.stringify(truncatedBody),
        });

        // 2) Replacement one-off (only if replacementForm provided)
        if (replacementForm) {
            const calendarId = record.calendarId
                || (await ensureCalendar(record.provider, replacementForm.type, state.locationId));
            const oneOff = Object.assign({}, replacementForm, { recurrence: { mode: 'none' } });
            await apiCall('/plugin-io/api/provider_availability_manager/events', {
                method: 'POST',
                body: JSON.stringify(eventBody(oneOff, calendarId)),
            });
        }

        // 3) New continuation series from dayAfter (only if original was recurring and either
        //    no recurrence end OR end is after dayAfter)
        const recEndDt = parseLocalISO(record.recurrence?.endDate);
        const hasContinuation = record.recurrence?.type && (!recEndDt || recEndDt > dayAfter);
        if (hasContinuation) {
            // Continuation DTSTART must be a real occurrence of the original
            // rule on or after dayAfter — not just dayAfter itself. WEEKLY
            // and DAILY INTERVAL math anchors at DTSTART, so picking an
            // arbitrary date (e.g. the day right after the edited
            // occurrence) shifts the WKST anchor for any INTERVAL>1 rule
            // and inverts every future occurrence's active/skipped parity.
            // Walk forward from dayAfter using the SAME expandOccurrences
            // the UI uses, so the continuation lines up exactly with what
            // the user sees in the calendar.
            let anchorDate = dayAfter;
            for (let i = 0; i < 366; i++) {
                if (expandOccurrences(record, anchorDate, anchorDate).length > 0) break;
                anchorDate = addDays(anchorDate, 1);
            }
            const newStart = new Date(anchorDate.getFullYear(), anchorDate.getMonth(), anchorDate.getDate(),
                startDt.getHours(), startDt.getMinutes());
            const newEnd = new Date(newStart.getTime() + duration);
            const continuationBody = {
                calendar: record.calendarId,
                timezone: state.viewTimezone || undefined,
                title: record.title,
                startTime: isoLocal(newStart),
                endTime: isoLocal(newEnd),
                recurrenceFrequency: record.recurrence.type,
                recurrenceInterval: record.recurrence.interval || 1,
                recurrenceDays: (record.daysOfWeek || []).slice(),
                recurrenceEndsAt: record.recurrence.endDate || null,
                allowedNoteTypes: record.allowedNoteTypes || [],
            };
            await apiCall('/plugin-io/api/provider_availability_manager/events', {
                method: 'POST',
                body: JSON.stringify(continuationBody),
            });
        }

        // Return the truncation we applied so the caller can re-assert it
        // against any stale GET response that came back before the PATCH was
        // visible on the read path.
        return { id: String(record.id), endDate: truncatedEnd };
    }

    // ---------------- Top-level render ----------------
    function renderAll() {
        // Capture scroll positions so they survive a full DOM rebuild.
        const prevModalScroll = modalRoot.querySelector('.av-modal')?.scrollTop || 0;
        const prevGridScroll = app.querySelector('.av-grid-wrap');
        const prevGridTop = prevGridScroll ? prevGridScroll.scrollTop : (state._lastGridScroll || 0);
        const prevGridLeft = prevGridScroll ? prevGridScroll.scrollLeft : 0;

        // Active element so a typed-in input doesn't lose focus mid-stroke.
        const ae = document.activeElement;
        const aeId = ae && ae.id ? ae.id : null;
        const aeStart = ae && typeof ae.selectionStart === 'number' ? ae.selectionStart : null;
        const aeEnd = ae && typeof ae.selectionEnd === 'number' ? ae.selectionEnd : null;

        app.innerHTML = '';
        app.appendChild(renderToolbar());
        if (!state.locationId && state.locations.length > 1) {
            app.appendChild(el('div', { class: 'av-empty' }, 'Pick a specific location to view and edit availability.'));
        } else {
            app.appendChild(renderGrid());
        }
        modalRoot.innerHTML = '';
        // Priority: edit modal > scope prompt > tile popup
        const modal = renderModal() || renderTilePopup();
        if (modal) modalRoot.appendChild(modal);

        // Restore scroll positions
        const newModal = modalRoot.querySelector('.av-modal');
        if (newModal) newModal.scrollTop = prevModalScroll;
        const newGrid = app.querySelector('.av-grid-wrap');
        if (newGrid) {
            newGrid.scrollTop = prevGridTop;
            newGrid.scrollLeft = prevGridLeft;
            state._lastGridScroll = prevGridTop;
        }

        // Restore focus / caret
        if (aeId) {
            const restored = document.getElementById(aeId);
            if (restored) {
                restored.focus();
                if (aeStart != null && typeof restored.setSelectionRange === 'function') {
                    try { restored.setSelectionRange(aeStart, aeEnd); } catch (e) { /* noop */ }
                }
            }
        }
    }

    // ---------------- Boot ----------------
    renderAll();
    // Re-fetch in the user's selected timezone so naive HH:MM matches the
    // wall-clock they're working in (template-rendered events fall back to
    // the calendar's tz which is often UTC for legacy data).
    refreshEvents().then(renderAll);
})();
