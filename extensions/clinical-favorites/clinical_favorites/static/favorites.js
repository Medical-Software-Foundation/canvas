        // Boot config is injected by a small inline script in each template
        // before this shared module loads. The surface flag tells the module
        // which of the two surfaces it is running, the management page or the
        // patient chart insert pane, so it only wires the elements that exist.
        const FAVORITES_BOOT = window.FAVORITES_BOOT || {};
        const staffId = FAVORITES_BOOT.staffId || "";
        const PINNED_PATIENT_ID = FAVORITES_BOOT.patientId || "";
        const FAVORITES_SURFACE = FAVORITES_BOOT.surface === 'chart' ? 'chart' : 'manage';

        const MANAGE_COLUMNS_MEDICATION = [
            { label: 'Status',   cls: 'fav-table-cell-shrink' },
            { label: 'Name',     cls: 'fav-table-cell-shrink' },
            { label: 'Code',     cls: 'fav-table-cell-shrink' },
            { label: 'Sig',      cls: 'fav-table-cell-flex' },
            { label: 'Owner',    cls: 'fav-table-cell-owner' },
            { label: 'Created',  cls: 'fav-table-cell-owner' },
            { label: 'Days',     cls: 'fav-table-cell-num' },
            { label: 'Quantity', cls: 'fav-table-cell-num' },
            { label: 'Refills',  cls: 'fav-table-cell-num' },
            { label: '',         cls: 'fav-table-cell-actions' },
        ];

        const MANAGE_COLUMNS_CONDITION = [
            { label: 'Status',   cls: 'fav-table-cell-shrink' },
            { label: 'Name',     cls: 'fav-table-cell-flex' },
            { label: 'Code',     cls: 'fav-table-cell-shrink' },
            { label: 'Owner',    cls: 'fav-table-cell-owner' },
            { label: 'Created',  cls: 'fav-table-cell-owner' },
            { label: '',         cls: 'fav-table-cell-actions' },
        ];

        function statusBadgeHtml(fav) {
            if (fav.is_shared) {
                return `<canvas-badge size="mini" color="blue">Shared</canvas-badge>`;
            }
            return `<canvas-badge size="mini" color="orange">Private</canvas-badge>`;
        }

        function formatCreatedDate(iso) {
            if (!iso) return '';
            try {
                return new Date(iso).toLocaleDateString();
            } catch (e) {
                return '';
            }
        }

        function formatQuantity(fav) {
            if (fav.quantity_to_dispense == null) return '';
            const qty = parseFloat(fav.quantity_to_dispense) || 0;
            const qtyDisplay = qty % 1 === 0 ? qty.toFixed(0) : qty.toString();
            const unit = (fav.unit || '').toLowerCase();
            return unit ? `${qtyDisplay} ${unit}` : qtyDisplay;
        }

        let selectedPatientId = PINNED_PATIENT_ID || "";
        let selectedNoteId = "";
        let currentInsertType = 'medication';
        let currentManageType = 'medication';
        let currentMode = 'prescribe';
        let favoritesData = [];
        let editingFavoriteId = null;
        let selectedMedication = null;
        let medSearchTimeout = null;
        let pharmacySearchTimeout = null;
        let conditionSearchTimeout = null;
        let currentPrescribeFilter = 'all';
        let currentManageFilter = 'all';
        let currentManageSort = 'name';
        // Pre search snapshots of accordion open state, keyed by section
        // title text. Captured on the empty to non empty transition of the
        // search input, restored on the non empty to empty transition.
        let prescribeAccordionSnapshot = null;
        let manageAccordionSnapshot = null;

        // Maps for async search result lookup
        let medResultsMap = {};
        let conditionResultsMap = {};
        let pharmacyResultsMap = {};

        function applyTypeBodyClass(type) {
            document.body.classList.toggle('favorite-type-condition', type === 'condition');
        }

        function setInsertType(t) {
            currentInsertType = t;
            // Different favorite types can carry different group names so
            // the captured snapshot keys would not resolve cleanly on the
            // new render. Drop the snapshot to start fresh.
            prescribeAccordionSnapshot = null;
            if (currentMode !== 'manage') applyTypeBodyClass(t);
            if (typeof reloadPrescribeList === 'function') {
                reloadPrescribeList(currentPrescribeFilter);
            }
        }

        function setManageType(t) {
            currentManageType = t;
            manageAccordionSnapshot = null;
            if (currentMode === 'manage') applyTypeBodyClass(t);
            renderFavoritesList();
        }

        let openNotesCache = [];
        // Patient display name resolved from the open-notes response, used by
        // the insert confirmation modal on the chart surface where there is no
        // patient picker to read a name from.
        let chartPatientName = "";

        function formatDOS(iso) {
            if (!iso) return '';
            const d = new Date(iso);
            if (isNaN(d.getTime())) return iso;
            const m = d.getMonth() + 1;
            const day = d.getDate();
            const yy = String(d.getFullYear()).slice(-2);
            let h = d.getHours();
            const min = String(d.getMinutes()).padStart(2, '0');
            const ampm = h >= 12 ? 'PM' : 'AM';
            h = h % 12;
            if (h === 0) h = 12;
            return `${m}/${day}/${yy} ${h}:${min} ${ampm}`;
        }

        function noteOptionLabel(n) {
            const type = n.note_type || 'Note';
            const dos = formatDOS(n.datetime_of_service || n.modified);
            const lockedSuffix = n.locked ? ', locked' : '';
            return dos ? `${type}, ${dos}${lockedSuffix}` : `${type}${lockedSuffix}`;
        }

        // Replace combobox children with a single disabled placeholder option
        // so the open menu always has visible content instead of an empty
        // sharp-bottom-corner surface.
        function setComboboxPlaceholder(combobox, text) {
            if (!combobox) return;
            while (combobox.firstChild) combobox.removeChild(combobox.firstChild);
            const placeholder = document.createElement('canvas-option');
            placeholder.setAttribute('value', '__placeholder__');
            placeholder.setAttribute('disabled', '');
            placeholder.textContent = text;
            combobox.appendChild(placeholder);
            syncComboboxOptions(combobox);
        }

        // Replace the built-in substring filter with a pass-through. Used on
        // comboboxes whose options come from async server search, where every
        // loaded option is already a match and built-in filtering would hide
        // them and flash the "No results" state on each keystroke.
        function useServerFilter(combobox) {
            if (!combobox) return;
            combobox._filter = function() {
                const items = this.shadowRoot.querySelectorAll('.option');
                for (let i = 0; i < items.length; i++) items[i].classList.remove('hidden');
                const empty = this.shadowRoot.querySelector('.empty');
                if (empty) {
                    if (items.length === 0) empty.classList.add('visible');
                    else empty.classList.remove('visible');
                }
            };
        }

        // canvas-dropdown reads child <canvas-option> once at connect time.
        // Call this after appending or replacing option children so the
        // component's internal state and rendered menu reflect the new set.
        function syncDropdownOptions(dropdown, preserveValue) {
            if (!dropdown || !dropdown.shadowRoot || typeof dropdown._readOptions !== 'function') return;
            const previousValue = preserveValue !== undefined ? preserveValue : dropdown._selectedValue;
            dropdown._readOptions();
            if (previousValue != null && dropdown._options.some(o => o.value === previousValue)) {
                dropdown._selectByValue(previousValue);
            } else {
                dropdown._selectedValue = null;
                dropdown._selectedText = '';
            }
            if (typeof dropdown._render === 'function') dropdown._render();
            if (typeof dropdown._bindEvents === 'function') dropdown._bindEvents();
        }

        function syncComboboxOptions(combobox) {
            if (!combobox || !combobox.shadowRoot || typeof combobox._readOptions !== 'function') return;
            combobox._readOptions();
            const menu = combobox.shadowRoot.querySelector('.menu');
            if (!menu) return;
            menu.querySelectorAll('.option').forEach(el => el.remove());
            const empty = menu.querySelector('.empty');
            (combobox._options || []).forEach((o, i) => {
                const li = document.createElement('li');
                let cls = 'option';
                if (o.value === combobox._selectedValue) cls += ' selected';
                li.className = cls;
                li.setAttribute('role', 'option');
                li.dataset.value = o.value;
                li.dataset.index = String(i);
                if (o.disabled) li.setAttribute('aria-disabled', 'true');
                if (o.value === combobox._selectedValue) li.setAttribute('aria-selected', 'true');
                li.innerHTML = o.html;
                if (empty) menu.insertBefore(li, empty); else menu.appendChild(li);
            });
            // Async searches are server filtered. Show all returned options
            // rather than re filtering by the typed query, which can hide
            // results whose labels do not contain the query text.
            if (typeof combobox._showAll === 'function') combobox._showAll();
            if (typeof combobox._checkEmpty === 'function') combobox._checkEmpty();
        }

        function renderNotePickerOptions(notes, previouslySelectedId) {
            const combobox = document.getElementById('note-picker');
            if (!combobox) return;
            if (!notes || notes.length === 0) {
                selectedNoteId = null;
                setComboboxPlaceholder(combobox, 'No open notes for this patient');
                showNoNotesState(true);
                updateInsertButton();
                return;
            }
            showNoNotesState(false);
            while (combobox.firstChild) combobox.removeChild(combobox.firstChild);
            let restored = false;
            notes.forEach(n => {
                const o = document.createElement('canvas-option');
                o.value = n.id;
                o.textContent = noteOptionLabel(n);
                if (n.locked) {
                    o.setAttribute('disabled', '');
                    o.title = 'Unlock the note in the chart to make it available';
                }
                if (previouslySelectedId && n.id === previouslySelectedId && !n.locked) {
                    o.setAttribute('selected', '');
                    restored = true;
                }
                combobox.appendChild(o);
            });
            combobox.removeAttribute('disabled');
            selectedNoteId = restored ? previouslySelectedId : null;
            if (restored) combobox.value = previouslySelectedId;
            syncComboboxOptions(combobox);
            updateInsertButton();
        }

        async function fetchOpenNotes(patientId, preserveSelection) {
            const combobox = document.getElementById('note-picker');
            if (!combobox) return;
            if (!patientId) {
                selectedNoteId = null;
                openNotesCache = [];
                setComboboxPlaceholder(combobox, 'Select a patient first');
                updateInsertButton();
                return;
            }
            const previouslySelectedId = preserveSelection ? selectedNoteId : null;
            try {
                const r = await fetch(
                    `/plugin-io/api/clinical_favorites/routes/open-notes?patient_id=${encodeURIComponent(patientId)}`,
                    { credentials: 'include' }
                );
                const j = await r.json();
                openNotesCache = j.notes || [];
                if (j.patient_name) chartPatientName = j.patient_name;
                renderNotePickerOptions(openNotesCache, previouslySelectedId);
            } catch (e) {
                selectedNoteId = null;
                openNotesCache = [];
                setComboboxPlaceholder(combobox, 'Could not load notes');
                updateInsertButton();
            }
        }

        const selectedFavoriteIds = new Set();
        // Mirror of selectedFavoriteIds keyed by id with the favorite type as
        // value. Lets the footer popup count medications vs conditions across
        // both insert tabs, since the insert lists do not stay in the DOM
        // when the user switches tabs.
        const selectedFavoriteTypes = new Map();
        // Parallel map of id to display name so the insert confirmation modal
        // can list selected meds and conditions even when the other tab's rows
        // are not in the DOM.
        const selectedFavoriteNames = new Map();

        document.addEventListener('DOMContentLoaded', () => {
            const notePicker = document.getElementById('note-picker');
            if (notePicker) {
                notePicker.addEventListener('change', (e) => {
                    selectedNoteId = e.target.value || null;
                    updateInsertButton();
                });
            }

            window.addEventListener('focus', () => {
                if (currentMode !== 'manage' && selectedPatientId) {
                    fetchOpenNotes(selectedPatientId, true);
                }
            });

            // Defer one tick so the combobox connectedCallback has rendered
            // its shadow DOM before we patch the filter and seed placeholders.
            setTimeout(() => {
                const np = document.getElementById('note-picker');
                if (np) {
                    useServerFilter(np);
                    setComboboxPlaceholder(np, 'Select a patient first');
                }
                ['med-combobox', 'condition-combobox', 'pharmacy-combobox'].forEach(id => {
                    const cb = document.getElementById(id);
                    if (cb) {
                        useServerFilter(cb);
                        setComboboxPlaceholder(cb, 'Type at least 2 characters to search');
                    }
                });
            }, 0);

            // Surface aware initial load. The management page loads the full
            // favorites list, the chart insert pane scopes notes to the pinned
            // patient and loads the prescribe list.
            if (FAVORITES_SURFACE === 'manage') {
                currentMode = 'manage';
                applyTypeBodyClass(currentManageType);
                if (typeof loadFavorites === 'function') loadFavorites();
            } else {
                currentMode = 'prescribe';
                applyTypeBodyClass(currentInsertType);
                // Defer the notes fetch one tick so it lands after the
                // placeholder seeding and the useServerFilter patch above,
                // which both run on their own setTimeout. Otherwise a fast
                // resolving fetch could be clobbered by the placeholder.
                if (PINNED_PATIENT_ID) {
                    setTimeout(() => fetchOpenNotes(PINNED_PATIENT_ID), 0);
                }
                if (typeof reloadPrescribeList === 'function') {
                    reloadPrescribeList(currentPrescribeFilter);
                }
            }
        });

        // Filter functions
        function setPrescribeFilter(filter) {
            currentPrescribeFilter = filter;
            reloadPrescribeList(filter);
        }

        function reloadPrescribeList(filter) {
            const listEl = document.getElementById('medication-list');
            if (!listEl) return;
            listEl.innerHTML = '<canvas-loader centered role="status" aria-label="Loading favorites"></canvas-loader>';

            fetch(`/plugin-io/api/clinical_favorites/routes/favorites?filter=${filter}`, { credentials: 'include' })
                .then(r => r.json())
                .then(data => {
                    if (!data.success) {
                        listEl.innerHTML = '';
                        showBanner('insert-banner', 'error', 'Failed to load favorites.', {
                            retry: () => reloadPrescribeList(currentPrescribeFilter)
                        });
                        return;
                    }
                    document.getElementById('insert-banner').innerHTML = '';
                    const searchEl = document.getElementById('prescribe-search-input');
                    const searchTerm = (searchEl && searchEl.value || '').toLowerCase().trim();
                    const rows = (data.favorites || []).filter(f => f.favorite_type === currentInsertType);

                    const renderInsertRow = (fav) => {
                        const terms = (fav.search_terms || []).join(' ');
                        const isChecked = selectedFavoriteIds.has(String(fav.id));
                        const nameLower = (fav.display_name || '').toLowerCase();
                        const sigLower = (fav.sig || '').toLowerCase();
                        const favType = fav.favorite_type === 'condition' ? 'condition' : 'medication';
                        const idStr = String(fav.id);
                        const detailId = `fav-detail-${escapeHtml(idStr)}`;
                        const name = escapeHtml(fav.display_name || '');

                        const rowAttrs = [
                            `data-favorite-id="${escapeHtml(idStr)}"`,
                            `data-search-terms="${escapeHtml(terms.toLowerCase())}"`,
                            `data-name="${escapeHtml(nameLower)}"`,
                            `data-sig="${escapeHtml(sigLower)}"`,
                            `data-is-custom="${fav.is_custom ? 'true' : 'false'}"`,
                            `data-is-mine="${fav.is_mine ? 'true' : 'false'}"`,
                            `data-is-shared="${fav.is_shared !== false ? 'true' : 'false'}"`,
                            `data-favorite-type="${favType}"`,
                        ].join(' ');

                        let detailHtml;
                        if (favType === 'condition') {
                            const code = escapeHtml(fav.code || '') || '—';
                            const desc = name || '—';
                            detailHtml = `
                                <dl class="fav-crow-detail-grid">
                                    <div class="fav-crow-detail-item"><dt>Code</dt><dd>${code}</dd></div>
                                    <div class="fav-crow-detail-item fav-crow-detail-wide"><dt>Description</dt><dd>${desc}</dd></div>
                                </dl>`;
                        } else {
                            const sig = escapeHtml(fav.sig || '') || '—';
                            const days = fav.days_supply != null ? escapeHtml(String(fav.days_supply)) : '—';
                            const qty = escapeHtml(formatQuantity(fav)) || '—';
                            const refills = escapeHtml(String(fav.refills || 0));
                            detailHtml = `
                                <dl class="fav-crow-detail-grid">
                                    <div class="fav-crow-detail-item fav-crow-detail-wide"><dt>Sig</dt><dd>${sig}</dd></div>
                                    <div class="fav-crow-detail-item"><dt>Days supply</dt><dd>${days}</dd></div>
                                    <div class="fav-crow-detail-item"><dt>Quantity</dt><dd>${qty}</dd></div>
                                    <div class="fav-crow-detail-item"><dt>Refills</dt><dd>${refills}</dd></div>
                                </dl>`;
                        }

                        return `
                            <div class="fav-crow" ${rowAttrs}>
                                <div class="fav-crow-summary">
                                    <span class="fav-crow-check"><canvas-checkbox value="${fav.id}" data-favorite-type="${favType}" data-favorite-name="${name}" aria-label="Select ${name}" ${isChecked ? 'checked' : ''}></canvas-checkbox></span>
                                    <div class="fav-crow-select">
                                        <span class="fav-crow-name">${name}</span>
                                        ${statusBadgeHtml(fav)}
                                    </div>
                                    <button type="button" class="fav-crow-toggle" aria-expanded="false" aria-controls="${detailId}" aria-label="Show details for ${name}">
                                        <span class="fav-crow-chevron material-icons-round" aria-hidden="true">expand_more</span>
                                    </button>
                                </div>
                                <div class="fav-crow-detail" id="${detailId}" hidden>
                                    ${detailHtml}
                                </div>
                            </div>`;
                    };
                    listEl.innerHTML = renderWithGroups(rows, renderInsertRow, {});

                    listEl.addEventListener('change', function handleCheckbox(e) {
                        if (e.target.tagName !== 'CANVAS-CHECKBOX') return;
                        if (e.target.checked) {
                            selectedFavoriteIds.add(e.target.value);
                            selectedFavoriteTypes.set(e.target.value, e.target.dataset.favoriteType || 'medication');
                            selectedFavoriteNames.set(e.target.value, e.target.dataset.favoriteName || '');
                        } else {
                            selectedFavoriteIds.delete(e.target.value);
                            selectedFavoriteTypes.delete(e.target.value);
                            selectedFavoriteNames.delete(e.target.value);
                        }
                        updateInsertButton();
                    });
                    updateInsertButton();
                    if (searchTerm) {
                        filterPrescribeList();
                    } else {
                        // No active search but the user may have just cleared
                        // a search via the empty state Clear filters button,
                        // which empties the input and reloads. Restore the
                        // captured baseline onto the freshly built DOM.
                        if (prescribeAccordionSnapshot) {
                            applyAccordionSnapshot(listEl, prescribeAccordionSnapshot);
                            prescribeAccordionSnapshot = null;
                        }
                        updateInsertEmptyState(rows.length === 0, currentPrescribeFilter === 'all' && !searchTerm);
                    }
                    syncToggleAllLabel('medication-list', 'prescribe-toggle-all-btn');
                })
                .catch(() => {
                    listEl.innerHTML = '';
                    showBanner('insert-banner', 'error', 'Failed to load favorites.', {
                        retry: () => reloadPrescribeList(currentPrescribeFilter)
                    });
                });
        }

        function setManageFilter(filter) {
            currentManageFilter = filter;
            renderFavoritesList();
        }

        function setManageSort(sort) {
            currentManageSort = sort;
            renderFavoritesList();
        }

        function filterPrescribeList() {
            const searchTerm = (document.getElementById('prescribe-search-input').value || '').toLowerCase().trim();
            const listEl = document.getElementById('medication-list');
            const hasSearch = !!searchTerm;

            // Capture the baseline before mutating display or open state.
            // Only on the empty to non empty edge so further keystrokes
            // never clobber the original snapshot.
            if (hasSearch && !prescribeAccordionSnapshot) {
                prescribeAccordionSnapshot = captureAccordionSnapshot(listEl);
            }

            const items = listEl ? listEl.querySelectorAll('.fav-crow[data-favorite-id]') : [];
            let visibleCount = 0;

            items.forEach(item => {
                const name = item.dataset.name || '';
                const sig = item.dataset.sig || '';
                const terms = item.dataset.searchTerms || '';
                const isCustom = item.dataset.isCustom === 'true';
                const isMine = item.dataset.isMine === 'true';
                const isShared = item.dataset.isShared === 'true';

                const matchesSearch = !searchTerm
                    || name.includes(searchTerm)
                    || sig.includes(searchTerm)
                    || terms.includes(searchTerm);

                let matchesFilter = true;
                if (currentPrescribeFilter === 'mine') {
                    matchesFilter = isMine;
                } else if (currentPrescribeFilter === 'shared') {
                    matchesFilter = isShared || !isCustom;
                }

                const visible = matchesSearch && matchesFilter;
                item.style.display = visible ? '' : 'none';
                if (visible) visibleCount++;
            });

            if (listEl) {
                listEl.querySelectorAll('canvas-accordion-item').forEach(item => {
                    const rows = item.querySelectorAll('.fav-crow[data-favorite-id]');
                    const visibleRows = Array.from(rows).filter(r => r.style.display !== 'none');
                    item.style.display = rows.length > 0 && visibleRows.length === 0 ? 'none' : '';
                    const badge = item.querySelector('canvas-accordion-title canvas-badge');
                    if (badge) badge.textContent = String(visibleRows.length);
                });

                // After visibility resolves, expand the visible matching
                // sections during a search, or restore the captured baseline
                // when the search just emptied.
                if (hasSearch) {
                    expandVisibleAccordions(listEl);
                } else if (prescribeAccordionSnapshot) {
                    applyAccordionSnapshot(listEl, prescribeAccordionSnapshot);
                    prescribeAccordionSnapshot = null;
                }
            }
            updateInsertEmptyState(visibleCount === 0, false);
            syncToggleAllLabel('medication-list', 'prescribe-toggle-all-btn');
        }

        // Toggle a compact insert row's detail open or shut. Driven by a
        // native button so Enter and Space activate it, keeping the expand
        // keyboard reachable. The selection checkbox sits outside the button,
        // so checking a favorite never expands its detail and vice versa.
        function toggleCompactRow(toggleBtn) {
            const expanded = toggleBtn.getAttribute('aria-expanded') === 'true';
            toggleBtn.setAttribute('aria-expanded', expanded ? 'false' : 'true');
            const crow = toggleBtn.closest('.fav-crow');
            if (!crow) return;
            crow.classList.toggle('is-expanded', !expanded);
            const detail = crow.querySelector('.fav-crow-detail');
            if (detail) detail.toggleAttribute('hidden', expanded);
        }

        // Tab switch. canvas-tabs dispatches tab-change with bubbles and composed,
        // so a nested tabs component can reach an outer listener. Each listener
        // below ignores events not originating from its own tabs element. The
        // two surfaces are now separate pages, so the legacy main tabs handler
        // only binds if the element is present, which it no longer is.
        const mainTabsEl = document.getElementById('main-tabs');
        if (mainTabsEl) {
            mainTabsEl.addEventListener('tab-change', function(e) {
                if (e.target.id !== 'main-tabs') return;
                selectedFavoriteIds.clear();
                selectedFavoriteTypes.clear();
                selectedFavoriteNames.clear();
                prescribeAccordionSnapshot = null;
                manageAccordionSnapshot = null;
                if (e.detail.panel === 'panel-manage') {
                    currentMode = 'manage';
                    applyTypeBodyClass(currentManageType);
                    loadFavorites();
                } else {
                    currentMode = 'prescribe';
                    applyTypeBodyClass(currentInsertType);
                    reloadPrescribeList(currentPrescribeFilter);
                }
            });
        }

        const typeTabsInsertEl = document.getElementById('type-tabs-insert');
        if (typeTabsInsertEl) {
            typeTabsInsertEl.addEventListener('tab-change', function(e) {
                if (e.target.id !== 'type-tabs-insert') return;
                setInsertType(e.detail.panel === 'type-insert-condition' ? 'condition' : 'medication');
            });
        }
        const typeTabsManageEl = document.getElementById('type-tabs-manage');
        if (typeTabsManageEl) {
            typeTabsManageEl.addEventListener('tab-change', function(e) {
                if (e.target.id !== 'type-tabs-manage') return;
                setManageType(e.detail.panel === 'type-manage-condition' ? 'condition' : 'medication');
            });
        }

        // Load favorites
        function loadFavorites() {
            const listEl = document.getElementById('favorites-list');
            listEl.innerHTML = '<canvas-loader centered role="status" aria-label="Loading favorites"></canvas-loader>';

            fetch('/plugin-io/api/clinical_favorites/routes/favorites?include_hidden=true', { credentials: 'include' })
                .then(r => r.json())
                .then(data => {
                    if (data.success) {
                        favoritesData = data.favorites;
                        renderFavoritesList();
                    } else {
                        listEl.innerHTML = '';
                        showBanner('manage-banner', 'error', 'Failed to load favorites.', {
                            retry: loadFavorites
                        });
                    }
                })
                .catch(() => {
                    listEl.innerHTML = '';
                    showBanner('manage-banner', 'error', 'Failed to load favorites.', {
                        retry: loadFavorites
                    });
                });
        }

        // Render list
        function renderFavoritesList() {
            const listEl = document.getElementById('favorites-list');

            // Read the search term up front so we can capture the pre search
            // baseline from the existing DOM before innerHTML is rewritten.
            const searchInput = document.getElementById('manage-search-input');
            const searchTerm = (searchInput && searchInput.value || '').toLowerCase().trim();
            const hasSearch = !!searchTerm;

            if (hasSearch && !manageAccordionSnapshot) {
                manageAccordionSnapshot = captureAccordionSnapshot(listEl);
            }

            if (favoritesData.length === 0) {
                listEl.innerHTML = `<div style="padding: 0; text-align: left;">
                    <div style="color: var(--text-tertiary); font-size: 14px;">No favorites yet. Click Add favorite for a single entry, or Bulk import to load a JSON file.</div>
                </div>`;
                if (!hasSearch) manageAccordionSnapshot = null;
                return;
            }

            let filtered = [...favoritesData];
            filtered = filtered.filter(f => f.favorite_type === currentManageType);

            if (currentManageFilter === 'mine') {
                filtered = filtered.filter(f => f.is_mine);
            } else if (currentManageFilter === 'shared') {
                filtered = filtered.filter(f => f.is_shared || !f.is_custom);
            }

            if (searchTerm) {
                filtered = filtered.filter(f => {
                    const name = (f.display_name || '').toLowerCase();
                    const code = (f.code || '').toLowerCase();
                    const sig = (f.sig || '').toLowerCase();
                    return name.includes(searchTerm) || code.includes(searchTerm) || sig.includes(searchTerm);
                });
            }

            const sorted = filtered.sort((a, b) => {
                if (currentManageSort === 'newest') {
                    const aDate = a.created_at || '0';
                    const bDate = b.created_at || '0';
                    return bDate.localeCompare(aDate);
                }
                if (currentManageSort === 'oldest') {
                    const aDate = a.created_at || '9';
                    const bDate = b.created_at || '9';
                    return aDate.localeCompare(bDate);
                }
                if (a.is_custom && !b.is_custom) return -1;
                if (!a.is_custom && b.is_custom) return 1;
                return a.display_name.localeCompare(b.display_name);
            });

            if (sorted.length === 0) {
                listEl.innerHTML = `<div style="padding: 48px 24px; text-align: center;">
                    <div style="color: var(--text-tertiary); font-size: 15px; margin-bottom: 12px;">No favorites match your filters.</div>
                    <canvas-button variant="ghost" id="manage-empty-clear-btn">Clear filters</canvas-button>
                </div>`;
                const btn = listEl.querySelector('#manage-empty-clear-btn');
                if (btn) btn.addEventListener('click', clearManageFilters);
                // Hold the snapshot while a search is producing zero rows so
                // the next clear can still restore. Drop it only when there
                // is no active search and nothing to restore against.
                if (!hasSearch) manageAccordionSnapshot = null;
                return;
            }

            const renderManageCard = (fav) => {
                const actionsHtml = fav.is_custom
                    ? `<canvas-button size="sm" variant="ghost" onclick="editFavorite('${fav.id}')">Edit</canvas-button>
                       <canvas-button size="sm" variant="danger" onclick="deleteFavorite('${fav.id}')">Delete</canvas-button>`
                    : (fav.is_hidden
                        ? `<canvas-button size="sm" variant="ghost" onclick="unhideDefault('${fav.id}')">Show</canvas-button>`
                        : `<canvas-button size="sm" variant="ghost" onclick="hideDefault('${fav.id}')">Hide</canvas-button>`);

                const rowAttrs = [
                    `data-favorite-id="${escapeHtml(String(fav.id))}"`,
                    `data-hidden="${fav.is_hidden ? 'true' : 'false'}"`,
                ].join(' ');

                const created = formatCreatedDate(fav.created_at);
                const owner = escapeHtml(fav.created_by_name || '');

                if (fav.favorite_type === 'condition') {
                    return `
                        <canvas-table-row ${rowAttrs}>
                            <canvas-table-cell class="fav-table-cell-shrink">${statusBadgeHtml(fav)}</canvas-table-cell>
                            <canvas-table-cell class="fav-table-cell-flex fav-table-name">${escapeHtml(fav.display_name)}</canvas-table-cell>
                            <canvas-table-cell class="fav-table-cell-shrink">${escapeHtml(fav.code || '')}</canvas-table-cell>
                            <canvas-table-cell class="fav-table-cell-owner">${owner}</canvas-table-cell>
                            <canvas-table-cell class="fav-table-cell-owner">${created}</canvas-table-cell>
                            <canvas-table-cell class="fav-table-cell-actions">${actionsHtml}</canvas-table-cell>
                        </canvas-table-row>`;
                }

                const qty = formatQuantity(fav);
                const days = fav.days_supply != null ? String(fav.days_supply) : '';
                const refills = fav.refills || 0;

                return `
                    <canvas-table-row ${rowAttrs}>
                        <canvas-table-cell class="fav-table-cell-shrink">${statusBadgeHtml(fav)}</canvas-table-cell>
                        <canvas-table-cell class="fav-table-cell-shrink fav-table-name">${escapeHtml(fav.display_name)}</canvas-table-cell>
                        <canvas-table-cell class="fav-table-cell-shrink">${escapeHtml(fav.code || '')}</canvas-table-cell>
                        <canvas-table-cell class="fav-table-cell-flex">${escapeHtml(fav.sig || '')}</canvas-table-cell>
                        <canvas-table-cell class="fav-table-cell-owner">${owner}</canvas-table-cell>
                        <canvas-table-cell class="fav-table-cell-owner">${created}</canvas-table-cell>
                        <canvas-table-cell class="fav-table-cell-num">${days}</canvas-table-cell>
                        <canvas-table-cell class="fav-table-cell-num">${escapeHtml(qty)}</canvas-table-cell>
                        <canvas-table-cell class="fav-table-cell-num">${refills}</canvas-table-cell>
                        <canvas-table-cell class="fav-table-cell-actions">${actionsHtml}</canvas-table-cell>
                    </canvas-table-row>`;
            };
            const manageColumns = currentManageType === 'condition' ? MANAGE_COLUMNS_CONDITION : MANAGE_COLUMNS_MEDICATION;
            listEl.innerHTML = renderWithGroups(sorted, renderManageCard, { columns: manageColumns });

            // Search just emptied. Restore the captured baseline onto the
            // freshly built DOM, then drop the snapshot so the next search
            // captures fresh.
            if (!hasSearch && manageAccordionSnapshot) {
                applyAccordionSnapshot(listEl, manageAccordionSnapshot);
                manageAccordionSnapshot = null;
            }
            syncToggleAllLabel('favorites-list', 'manage-toggle-all-btn');
        }

        // Add favorite button
        const addFavoriteBtn = document.getElementById('add-favorite-btn');
        if (addFavoriteBtn) {
            addFavoriteBtn.addEventListener('click', () => showForm(null));
        }

        function applyFormType(favoriteType) {
            document.getElementById('form-favorite-type').value = favoriteType;
            document.body.classList.toggle('favorite-type-condition', favoriteType === 'condition');
        }

        function seedGroupCombobox() {
            const combobox = document.getElementById('group-combobox');
            if (!combobox) return;
            while (combobox.firstChild) combobox.removeChild(combobox.firstChild);
            const groups = [...new Set(favoritesData.map(f => f.group_name).filter(Boolean))].sort();
            groups.forEach(g => {
                const o = document.createElement('canvas-option');
                o.value = g;
                o.textContent = g;
                combobox.appendChild(o);
            });
            syncComboboxOptions(combobox);
        }

        function showForm(favoriteId) {
            editingFavoriteId = favoriteId;
            resetForm();
            seedGroupCombobox();

            let favoriteType = currentMode === 'manage' ? currentManageType : currentInsertType;
            let fav = null;
            if (favoriteId) {
                fav = favoritesData.find(f => f.id === favoriteId);
                if (fav) favoriteType = fav.favorite_type;
            }
            applyFormType(favoriteType);

            const titleEl = document.getElementById('modal-title-header');
            if (titleEl) {
                if (favoriteId) {
                    titleEl.textContent = favoriteType === 'condition' ? 'Edit condition favorite' : 'Edit favorite';
                } else {
                    titleEl.textContent = favoriteType === 'condition' ? 'Add condition favorite' : 'Add favorite';
                }
            }

            if (favoriteId && fav) populateForm(fav);
            document.getElementById('favorite-modal').open();
        }

        function hideForm() {
            document.getElementById('favorite-modal').dismiss();
        }

        // Clean up state when modal closes (via Escape, backdrop, or hideForm)
        const favoriteModalEl = document.getElementById('favorite-modal');
        if (favoriteModalEl) {
            favoriteModalEl.addEventListener('dismiss', () => {
                editingFavoriteId = null;
                resetForm();
            });
        }

        const modalCancelBtn = document.getElementById('modal-cancel-btn');
        if (modalCancelBtn) {
            modalCancelBtn.addEventListener('click', () => hideForm());
        }

        // Bulk import
        let bulkSelectedIndices = new Set();
        let bulkImportPreviewTimer = null;

        function hideBulkImport() {
            document.getElementById('bulk-import-modal').dismiss();
        }

        function resetBulkImport() {
            bulkSelectedIndices = new Set();
            if (bulkImportPreviewTimer) {
                clearTimeout(bulkImportPreviewTimer);
                bulkImportPreviewTimer = null;
            }
            const input = document.getElementById('bulk-import-input');
            if (input) input.value = '';
            const preview = document.getElementById('bulk-import-preview');
            if (preview) {
                preview.style.display = 'none';
                preview.dataset.rows = '';
            }
            const grid = document.getElementById('bulk-import-preview-grid');
            if (grid) grid.innerHTML = '';
            const summary = document.getElementById('bulk-import-preview-summary');
            if (summary) summary.textContent = '';
            const banner = document.getElementById('bulk-import-banner');
            if (banner) banner.innerHTML = '';
        }

        function renderBulkImportPreview(rows, results) {
            const summary = document.getElementById('bulk-import-preview-summary');
            const grid = document.getElementById('bulk-import-preview-grid');
            const container = document.getElementById('bulk-import-preview');
            if (!summary || !grid || !container) return;

            const safeResults = Array.isArray(results) ? results : [];
            const validCount = safeResults.filter(r => r && r.valid).length;
            const invalidCount = rows.length - validCount;
            summary.textContent =
                `${validCount} valid, ${invalidCount} invalid. Uncheck any to skip before importing.`;

            bulkSelectedIndices = new Set();
            grid.innerHTML = rows.map((r, i) => {
                const result = safeResults[i] || { valid: false, reason: 'Unknown' };
                const type = (r && r.favorite_type) || '';
                const name = (r && r.display_name) || '(missing display_name)';
                const codeOrFdb = type === 'condition' ? (r && r.code) : (r && r.fdb_code);
                const metaBits = [type || 'unknown type', codeOrFdb || ''].filter(Boolean);
                if (result.valid) bulkSelectedIndices.add(i);
                return `
                    <div style="display: flex; align-items: flex-start; gap: 10px; padding: 6px 2px;">
                        <canvas-checkbox value="${i}" ${result.valid ? 'checked' : 'disabled'}></canvas-checkbox>
                        <div style="flex: 1; min-width: 0; display: flex; flex-direction: column; gap: 4px;">
                            <div style="display: flex; align-items: center; gap: 10px;">
                                <span style="flex: 1; font-weight: 500; font-size: 13px;">${escapeHtml(name)}</span>
                                <span style="color: var(--text-secondary); font-size: 12px;">${escapeHtml(metaBits.join(', '))}</span>
                            </div>
                            ${!result.valid
                                ? `<span style="color: var(--error, #ef4444); font-size: 12px; white-space: normal; overflow-wrap: anywhere; word-break: break-word;">Invalid, ${escapeHtml(result.reason || 'unknown reason')}</span>`
                                : ''}
                        </div>
                    </div>`;
            }).join('');
            container.style.display = 'block';
            container.dataset.rows = JSON.stringify(rows);
        }

        async function runBulkImportPreview() {
            const input = document.getElementById('bulk-import-input');
            const raw = (input && input.value || '').trim();
            if (!raw) {
                showBanner('bulk-import-banner', 'error', 'Paste a JSON array of favorites first.');
                return;
            }
            let parsed;
            try {
                parsed = JSON.parse(raw);
            } catch (e) {
                showBanner('bulk-import-banner', 'error', 'Invalid JSON, ' + (e && e.message ? e.message : 'parse error'));
                return;
            }
            if (!Array.isArray(parsed)) {
                showBanner('bulk-import-banner', 'error', 'Expected a JSON array at the top level.');
                return;
            }
            if (parsed.length === 0) {
                showBanner('bulk-import-banner', 'error', 'Array is empty.');
                return;
            }
            document.getElementById('bulk-import-banner').innerHTML = '';

            try {
                const res = await fetch('/plugin-io/api/clinical_favorites/routes/favorites/bulk-import', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    credentials: 'include',
                    body: JSON.stringify({ favorites: parsed, dry_run: true }),
                });
                const data = await res.json();
                if (!data.success) {
                    showBanner('bulk-import-banner', 'error', data.error || 'Validation failed.');
                    return;
                }
                renderBulkImportPreview(parsed, data.results || []);
            } catch (e) {
                showBanner('bulk-import-banner', 'error', 'Network error during validation.');
            }
        }

        (function wireBulkImport() {
            const openBtn = document.getElementById('bulk-import-btn');
            const submitBtn = document.getElementById('bulk-import-submit-btn');
            if (!openBtn || !submitBtn) return;

            document.getElementById('bulk-import-preview-grid').addEventListener('change', function(e) {
                if (e.target.tagName !== 'CANVAS-CHECKBOX') return;
                const idx = parseInt(e.target.getAttribute('value'), 10);
                if (e.target.checked) {
                    bulkSelectedIndices.add(idx);
                } else {
                    bulkSelectedIndices.delete(idx);
                }
            });

            openBtn.addEventListener('click', () => {
                document.getElementById('bulk-import-modal').open();
                resetBulkImport();
            });

            submitBtn.addEventListener('click', () => {
                const container = document.getElementById('bulk-import-preview');
                const raw = container && container.dataset && container.dataset.rows;
                if (!raw) {
                    showBanner('bulk-import-banner', 'error', 'Preview first, then import.');
                    return;
                }
                let rows;
                try {
                    rows = JSON.parse(raw);
                } catch (e) {
                    showBanner('bulk-import-banner', 'error', 'Internal error, preview data corrupted.');
                    return;
                }
                const toImport = rows.filter((_, i) => bulkSelectedIndices.has(i));
                if (toImport.length === 0) {
                    showBanner('bulk-import-banner', 'error', 'Select at least one row to import.');
                    return;
                }

                submitBtn.setAttribute('disabled', '');
                submitBtn.textContent = 'Importing...';

                fetch('/plugin-io/api/clinical_favorites/routes/favorites/bulk-import', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    credentials: 'include',
                    body: JSON.stringify({ favorites: toImport }),
                })
                .then(r => r.json())
                .then(data => {
                    if (data.success) {
                        hideBulkImport();
                        loadFavorites();
                    } else {
                        showBanner('bulk-import-banner', 'error', data.error || 'Bulk import failed.');
                    }
                })
                .catch(() => showBanner('bulk-import-banner', 'error', 'Network error during bulk import.'))
                .finally(() => {
                    submitBtn.removeAttribute('disabled');
                    submitBtn.textContent = 'Import selected';
                });
            });
            document.getElementById('bulk-import-modal').addEventListener('dismiss', resetBulkImport);
            document.getElementById('bulk-import-cancel-btn').addEventListener('click', hideBulkImport);

            const inputEl = document.getElementById('bulk-import-input');
            if (inputEl) {
                inputEl.addEventListener('input', function() {
                    if (bulkImportPreviewTimer) clearTimeout(bulkImportPreviewTimer);
                    bulkImportPreviewTimer = setTimeout(function() {
                        bulkImportPreviewTimer = null;
                        if (!(inputEl.value || '').trim()) return;
                        runBulkImportPreview();
                    }, 500);
                });
            }
        })();

        function resetForm() {
            // Hidden inputs
            document.getElementById('form-favorite-id').value = '';
            document.getElementById('form-favorite-type').value = 'medication';
            document.getElementById('form-fdb-code').value = '';
            document.getElementById('form-representative-ndc').value = '';
            document.getElementById('form-ncpdp-qualifier').value = '';
            document.getElementById('form-condition-code').value = '';
            document.getElementById('form-pharmacy-ncpdp').value = '';
            document.getElementById('form-pharmacy-name').value = '';
            document.getElementById('form-is-shared').value = 'true';

            // Canvas comboboxes — reset value and seed the empty state prompt
            const medCb = document.getElementById('med-combobox');
            if (medCb) { medCb.value = ''; setComboboxPlaceholder(medCb, 'Type at least 2 characters to search'); }
            const condCb = document.getElementById('condition-combobox');
            if (condCb) { condCb.value = ''; setComboboxPlaceholder(condCb, 'Type at least 2 characters to search'); }
            const pharmCb = document.getElementById('pharmacy-combobox');
            if (pharmCb) { pharmCb.value = ''; setComboboxPlaceholder(pharmCb, 'Type at least 2 characters to search'); }
            const groupCb = document.getElementById('group-combobox');
            if (groupCb) groupCb.value = '';
            medResultsMap = {};
            conditionResultsMap = {};
            pharmacyResultsMap = {};
            selectedMedication = null;

            // Canvas inputs / textarea
            const displayName = document.getElementById('form-display-name');
            if (displayName) displayName.value = '';
            const labelIn = document.getElementById('form-label');
            if (labelIn) labelIn.value = '';
            const sigIn = document.getElementById('form-sig');
            if (sigIn) sigIn.value = '';
            const daysSupply = document.getElementById('form-days-supply');
            if (daysSupply) daysSupply.value = '';
            const quantity = document.getElementById('form-quantity');
            if (quantity) quantity.value = '';
            const refills = document.getElementById('form-refills');
            if (refills) refills.value = '0';

            // Canvas dropdown
            const labelColor = document.getElementById('form-label-color');
            if (labelColor) labelColor.value = 'gray';
            document.getElementById('form-label-color').style.display = 'none';

            // Unit dropdown — clear options, rely on placeholder attribute
            const unitDd = document.getElementById('form-unit');
            if (unitDd) {
                while (unitDd.firstChild) unitDd.removeChild(unitDd.firstChild);
                syncDropdownOptions(unitDd, '');
            }

            // Visibility radio — reset to Shared
            document.querySelectorAll('canvas-radio[name="form-visibility"]').forEach(r => {
                r.checked = r.value === 'true';
            });

            // Banner
            document.getElementById('form-banner').innerHTML = '';

            // Body class
            document.body.classList.remove('favorite-type-condition');
        }

        function populateForm(fav) {
            document.getElementById('form-favorite-id').value = fav.id;
            document.getElementById('form-favorite-type').value = fav.favorite_type;
            document.getElementById('form-display-name').value = fav.display_name;

            // Group combobox — creatable mode accepts any string
            const groupCb = document.getElementById('group-combobox');
            if (groupCb) groupCb.value = fav.group_name || '';

            // Label and color
            document.getElementById('form-label').value = fav.label || '';
            document.getElementById('form-label-color').value = fav.label_color || 'gray';
            document.getElementById('form-label-color').style.display = fav.label ? '' : 'none';

            // Visibility
            const isShared = fav.is_shared !== false;
            document.getElementById('form-is-shared').value = isShared ? 'true' : 'false';
            document.querySelectorAll('canvas-radio[name="form-visibility"]').forEach(r => {
                r.checked = (r.value === (isShared ? 'true' : 'false'));
            });

            if (fav.favorite_type === 'condition') {
                document.getElementById('form-condition-code').value = fav.code || '';
                const condCb = document.getElementById('condition-combobox');
                if (condCb) {
                    while (condCb.firstChild) condCb.removeChild(condCb.firstChild);
                    const o = document.createElement('canvas-option');
                    o.value = fav.code || '';
                    o.textContent = fav.display_name;
                    o.setAttribute('selected', '');
                    condCb.appendChild(o);
                    syncComboboxOptions(condCb);
                    condCb.value = fav.code || '';
                    conditionResultsMap[fav.code] = { code: fav.code, display: fav.display_name };
                }
                return;
            }

            // Medication fields
            document.getElementById('form-fdb-code').value = fav.fdb_code;
            document.getElementById('form-representative-ndc').value = fav.representative_ndc;
            document.getElementById('form-ncpdp-qualifier').value = fav.ncpdp_quantity_qualifier_code;
            document.getElementById('form-sig').value = fav.sig;
            document.getElementById('form-days-supply').value = fav.days_supply;
            document.getElementById('form-quantity').value = fav.quantity_to_dispense;
            document.getElementById('form-refills').value = fav.refills || 0;

            selectedMedication = {
                fdb_code: fav.fdb_code,
                representative_ndc: fav.representative_ndc,
                ncpdp_quantity_qualifier_code: fav.ncpdp_quantity_qualifier_code
            };

            // Medication combobox
            const medCb = document.getElementById('med-combobox');
            if (medCb) {
                while (medCb.firstChild) medCb.removeChild(medCb.firstChild);
                const o = document.createElement('canvas-option');
                o.value = fav.fdb_code;
                o.textContent = fav.medication_name || fav.display_name;
                o.setAttribute('selected', '');
                medCb.appendChild(o);
                syncComboboxOptions(medCb);
                medCb.value = fav.fdb_code;
            }

            // Unit dropdown — seed with existing unit
            const unitDd = document.getElementById('form-unit');
            if (unitDd) {
                while (unitDd.firstChild) unitDd.removeChild(unitDd.firstChild);
                const unitValue = JSON.stringify({
                    representative_ndc: fav.representative_ndc,
                    ncpdp_quantity_qualifier_code: fav.ncpdp_quantity_qualifier_code,
                    quantity_description: fav.unit
                });
                const o = document.createElement('canvas-option');
                o.value = unitValue;
                o.textContent = fav.unit;
                o.setAttribute('selected', '');
                unitDd.appendChild(o);
                syncDropdownOptions(unitDd, unitValue);
            }

            // Pharmacy combobox
            if (fav.default_pharmacy_ncpdp_id) {
                document.getElementById('form-pharmacy-ncpdp').value = fav.default_pharmacy_ncpdp_id;
                document.getElementById('form-pharmacy-name').value = fav.default_pharmacy_name || '';
                const pharmCb = document.getElementById('pharmacy-combobox');
                if (pharmCb) {
                    while (pharmCb.firstChild) pharmCb.removeChild(pharmCb.firstChild);
                    const o = document.createElement('canvas-option');
                    o.value = fav.default_pharmacy_ncpdp_id;
                    o.textContent = fav.default_pharmacy_name || fav.default_pharmacy_ncpdp_id;
                    o.setAttribute('selected', '');
                    pharmCb.appendChild(o);
                    syncComboboxOptions(pharmCb);
                    pharmCb.value = fav.default_pharmacy_ncpdp_id;
                    pharmacyResultsMap[fav.default_pharmacy_ncpdp_id] = {
                        ncpdp_id: fav.default_pharmacy_ncpdp_id,
                        organization_name: fav.default_pharmacy_name || '',
                        address: ''
                    };
                }
            }
        }

        // Medication combobox — async search
        (function wireMedCombobox() {
            const combobox = document.getElementById('med-combobox');
            if (!combobox) return;

            combobox.addEventListener('input', (e) => {
                const query = (((e.composedPath && e.composedPath()[0]) || e.target).value || '').trim();
                // Clear selection when user starts typing
                if (selectedMedication) {
                    selectedMedication = null;
                    document.getElementById('form-fdb-code').value = '';
                    document.getElementById('form-representative-ndc').value = '';
                    document.getElementById('form-ncpdp-qualifier').value = '';
                }
                clearTimeout(medSearchTimeout);
                if (query.length < 2) {
                    setComboboxPlaceholder(combobox, 'Type at least 2 characters to search');
                    return;
                }
                medSearchTimeout = setTimeout(() => {
                    fetch(`/plugin-io/api/clinical_favorites/routes/search/medication?q=${encodeURIComponent(query)}`, { credentials: 'include' })
                        .then(r => r.json())
                        .then(data => {
                            const meds = data.results || [];
                            medResultsMap = {};
                            while (combobox.firstChild) combobox.removeChild(combobox.firstChild);
                            meds.forEach(med => {
                                medResultsMap[med.fdb_code] = med;
                                const o = document.createElement('canvas-option');
                                o.value = med.fdb_code;
                                o.textContent = med.display_name;
                                combobox.appendChild(o);
                            });
                            syncComboboxOptions(combobox);
                        })
                        .catch(() => {});
                }, 300);
            });

            combobox.addEventListener('change', (e) => {
                const fdbCode = e.target.value;
                if (fdbCode && medResultsMap[fdbCode]) {
                    selectMedication(medResultsMap[fdbCode]);
                }
            });
        })();

        function selectMedication(med) {
            selectedMedication = med;
            document.getElementById('form-fdb-code').value = med.fdb_code;

            const unitDd = document.getElementById('form-unit');
            while (unitDd.firstChild) unitDd.removeChild(unitDd.firstChild);

            let preselectedValue = '';
            if (med.clinical_quantities && med.clinical_quantities.length > 0) {
                med.clinical_quantities.forEach((cq, index) => {
                    const opt = document.createElement('canvas-option');
                    opt.value = JSON.stringify({
                        representative_ndc: cq.representative_ndc,
                        ncpdp_quantity_qualifier_code: cq.ncpdp_quantity_qualifier_code,
                        quantity_description: cq.quantity_description
                    });
                    opt.textContent = cq.quantity_description || `Unit ${index + 1}`;
                    unitDd.appendChild(opt);
                });
                if (med.clinical_quantities.length === 1) {
                    const firstOpt = unitDd.querySelector('canvas-option');
                    if (firstOpt) preselectedValue = firstOpt.value;
                }
            }
            syncDropdownOptions(unitDd, preselectedValue);
            if (preselectedValue) updateUnitHiddenFields();

            // Always overwrite display name on selection so switching medications
            // updates the visible name on Add and Edit. Manage table renders by
            // display_name, leaving the previous value would show the wrong row label.
            const displayNameEl = document.getElementById('form-display-name');
            if (displayNameEl) {
                displayNameEl.value = med.display_name;
            }
        }

        function updateUnitHiddenFields() {
            const unitDd = document.getElementById('form-unit');
            if (unitDd && unitDd.value) {
                try {
                    const unitData = JSON.parse(unitDd.value);
                    document.getElementById('form-representative-ndc').value = unitData.representative_ndc;
                    document.getElementById('form-ncpdp-qualifier').value = unitData.ncpdp_quantity_qualifier_code;
                } catch (e) {}
            }
        }

        const formUnitEl = document.getElementById('form-unit');
        if (formUnitEl) {
            formUnitEl.addEventListener('change', updateUnitHiddenFields);
        }

        // Condition combobox — async search
        (function wireConditionCombobox() {
            const combobox = document.getElementById('condition-combobox');
            if (!combobox) return;

            combobox.addEventListener('input', (e) => {
                const query = (((e.composedPath && e.composedPath()[0]) || e.target).value || '').trim();
                clearTimeout(conditionSearchTimeout);
                if (query.length < 2) {
                    setComboboxPlaceholder(combobox, 'Type at least 2 characters to search');
                    return;
                }
                conditionSearchTimeout = setTimeout(() => {
                    fetch(`/plugin-io/api/clinical_favorites/routes/search/condition?q=${encodeURIComponent(query)}`, { credentials: 'include' })
                        .then(r => r.json())
                        .then(data => {
                            const rows = data.results || [];
                            conditionResultsMap = {};
                            while (combobox.firstChild) combobox.removeChild(combobox.firstChild);
                            rows.forEach(c => {
                                conditionResultsMap[c.code] = c;
                                const o = document.createElement('canvas-option');
                                o.value = c.code;
                                o.textContent = `${c.display} (${c.code})`;
                                combobox.appendChild(o);
                            });
                            syncComboboxOptions(combobox);
                        })
                        .catch(() => {});
                }, 300);
            });

            combobox.addEventListener('change', (e) => {
                const code = e.target.value;
                if (code && conditionResultsMap[code]) {
                    selectCondition(conditionResultsMap[code]);
                }
            });
        })();

        function selectCondition(cond) {
            document.getElementById('form-condition-code').value = cond.code;
            const displayNameEl = document.getElementById('form-display-name');
            if (displayNameEl && !displayNameEl.value.trim()) {
                displayNameEl.value = cond.display;
            }
        }

        // Pharmacy combobox — async search
        (function wirePharmacyCombobox() {
            const combobox = document.getElementById('pharmacy-combobox');
            if (!combobox) return;

            combobox.addEventListener('input', (e) => {
                const query = (((e.composedPath && e.composedPath()[0]) || e.target).value || '').trim();
                clearTimeout(pharmacySearchTimeout);
                if (query.length < 2) {
                    setComboboxPlaceholder(combobox, 'Type at least 2 characters to search');
                    return;
                }
                pharmacySearchTimeout = setTimeout(() => {
                    fetch(`/plugin-io/api/clinical_favorites/routes/search/pharmacy?q=${encodeURIComponent(query)}`, { credentials: 'include' })
                        .then(r => r.json())
                        .then(data => {
                            const phs = data.results || [];
                            pharmacyResultsMap = {};
                            while (combobox.firstChild) combobox.removeChild(combobox.firstChild);
                            phs.forEach(ph => {
                                pharmacyResultsMap[ph.ncpdp_id] = ph;
                                const o = document.createElement('canvas-option');
                                o.value = ph.ncpdp_id;
                                const name = ph.organization_name || '';
                                if (ph.address) {
                                    o.setAttribute('label', `${name}, ${ph.address}`);
                                    o.innerHTML = `<span style="font-weight: 600;">${name}</span><span style="color: #6b6b6b; font-size: 0.875em; margin-left: 8px;">${ph.address}</span>`;
                                } else {
                                    o.textContent = name;
                                }
                                combobox.appendChild(o);
                            });
                            syncComboboxOptions(combobox);
                        })
                        .catch(() => {});
                }, 300);
            });

            combobox.addEventListener('change', (e) => {
                const ncpdpId = e.target.value;
                if (ncpdpId && pharmacyResultsMap[ncpdpId]) {
                    const ph = pharmacyResultsMap[ncpdpId];
                    document.getElementById('form-pharmacy-ncpdp').value = ph.ncpdp_id;
                    document.getElementById('form-pharmacy-name').value = ph.organization_name;
                }
            });
        })();

        // Visibility radio — update hidden input
        document.querySelectorAll('canvas-radio[name="form-visibility"]').forEach(r => {
            r.addEventListener('change', (e) => {
                if (e.target.checked || e.target.tagName === 'CANVAS-RADIO') {
                    document.getElementById('form-is-shared').value = e.target.value;
                }
            });
        });

        // Label input — show/hide color picker
        const formLabelEl = document.getElementById('form-label');
        if (formLabelEl) {
            formLabelEl.addEventListener('input', function() {
                const colorGroup = document.getElementById('form-label-color');
                colorGroup.style.display = formLabelEl.value.trim() ? '' : 'none';
            });
        }

        // Form Submit Handler
        function handleFormSubmit(e) {
            if (e) e.preventDefault();

            const favoriteType = document.getElementById('form-favorite-type').value || 'medication';
            const displayName = (document.getElementById('form-display-name').value || '').trim();
            const groupName = (document.getElementById('group-combobox').value || '').trim();
            const labelText = (document.getElementById('form-label').value || '').trim();
            const labelColor = document.getElementById('form-label-color').value || 'gray';
            const isShared = document.getElementById('form-is-shared').value === 'true';

            if (!displayName) {
                showBanner('form-banner', 'error', 'Display name is required.');
                return;
            }

            let payload;
            if (favoriteType === 'condition') {
                const code = document.getElementById('form-condition-code').value.trim();
                if (!code) {
                    showBanner('form-banner', 'error', 'Select a condition from the ICD 10 search.');
                    return;
                }
                payload = {
                    favorite_type: 'condition',
                    display_name: displayName,
                    code: code,
                    group_name: groupName,
                    label: labelText || null,
                    label_color: labelText ? (labelColor || 'gray') : null,
                    is_shared: isShared,
                };
            } else {
                const fdbCode = document.getElementById('form-fdb-code').value;
                const sig = (document.getElementById('form-sig').value || '').trim();
                const daysSupply = document.getElementById('form-days-supply').value;
                const quantity = document.getElementById('form-quantity').value;
                const unitDdValue = document.getElementById('form-unit').value;
                const refills = document.getElementById('form-refills').value || 0;
                const representativeNdc = document.getElementById('form-representative-ndc').value;
                const ncpdpQualifier = document.getElementById('form-ncpdp-qualifier').value;
                const pharmacyNcpdp = document.getElementById('form-pharmacy-ncpdp').value;
                const pharmacyName = document.getElementById('form-pharmacy-name').value;

                let unitDescription = '';
                if (unitDdValue) {
                    try {
                        const unitData = JSON.parse(unitDdValue);
                        unitDescription = unitData.quantity_description || 'Each';
                    } catch (err) {
                        unitDescription = unitDdValue;
                    }
                }

                if (!fdbCode) {
                    showBanner('form-banner', 'error', 'Select a medication.');
                    return;
                }
                if (!sig || !daysSupply || !quantity || !unitDdValue) {
                    showBanner('form-banner', 'error', 'Fill in all required fields.');
                    return;
                }
                if (!representativeNdc || !ncpdpQualifier) {
                    showBanner('form-banner', 'error', 'Medication data incomplete. Select a unit.');
                    return;
                }

                // Read the medication name from the combobox display text
                const medCb = document.getElementById('med-combobox');
                const medName = medCb
                    ? (medCb.querySelector('canvas-option[selected]') || {}).textContent || displayName
                    : displayName;

                payload = {
                    favorite_type: 'medication',
                    display_name: displayName,
                    medication_name: medName,
                    fdb_code: fdbCode,
                    sig: sig,
                    days_supply: parseInt(daysSupply),
                    quantity_to_dispense: parseFloat(quantity),
                    unit: unitDescription,
                    refills: parseInt(refills),
                    representative_ndc: representativeNdc,
                    ncpdp_quantity_qualifier_code: ncpdpQualifier,
                    generic_substitution_allowed: true,
                    search_terms: [],
                    default_pharmacy_ncpdp_id: pharmacyNcpdp || null,
                    default_pharmacy_name: pharmacyName || null,
                    group_name: groupName,
                    label: labelText || null,
                    label_color: labelText ? (labelColor || 'gray') : null,
                    is_shared: isShared,
                };
            }

            const submitBtn = document.getElementById('form-submit-btn');
            submitBtn.setAttribute('disabled', '');

            const isEdit = !!editingFavoriteId;
            const url = '/plugin-io/api/clinical_favorites/routes/favorites';
            const method = isEdit ? 'PUT' : 'POST';

            if (isEdit) {
                payload.id = editingFavoriteId;
            }

            fetch(url, {
                method: method,
                headers: { 'Content-Type': 'application/json' },
                credentials: 'include',
                body: JSON.stringify(payload)
            })
            .then(r => r.json())
            .then(data => {
                if (data.success) {
                    hideForm();
                    loadFavorites();
                } else {
                    showBanner('form-banner', 'error', data.error || 'Failed to save favorite.');
                }
            })
            .catch((err) => {
                showBanner('form-banner', 'error', 'Error saving favorite, ' + (err.message || err));
            })
            .finally(() => {
                submitBtn.removeAttribute('disabled');
            });
        }

        const favoriteFormEl = document.getElementById('favorite-form');
        if (favoriteFormEl) {
            favoriteFormEl.addEventListener('submit', handleFormSubmit);
        }
        const formSubmitBtnEl = document.getElementById('form-submit-btn');
        if (formSubmitBtnEl) {
            formSubmitBtnEl.addEventListener('click', handleFormSubmit);
        }

        function editFavorite(id) {
            showForm(id);
        }

        let pendingDeleteFavorite = null;

        function deleteFavorite(id) {
            const fav = favoritesData.find(f => f.id === id);
            if (!fav) return;
            pendingDeleteFavorite = fav;

            const nameEl = document.getElementById('delete-confirm-name');
            if (nameEl) nameEl.textContent = fav.display_name || '';

            const input = document.getElementById('delete-confirm-input');
            if (input) input.value = '';

            const submitBtn = document.getElementById('delete-confirm-submit-btn');
            if (submitBtn) {
                submitBtn.setAttribute('disabled', '');
                submitBtn.textContent = 'Delete';
            }

            const banner = document.getElementById('delete-confirm-banner');
            if (banner) banner.innerHTML = '';

            document.getElementById('delete-confirm-modal').open();
            requestAnimationFrame(() => {
                const inp = document.getElementById('delete-confirm-input');
                if (inp && typeof inp.focus === 'function') inp.focus();
            });
        }

        (function wireDeleteConfirm() {
            const modal = document.getElementById('delete-confirm-modal');
            const input = document.getElementById('delete-confirm-input');
            const submitBtn = document.getElementById('delete-confirm-submit-btn');
            const cancelBtn = document.getElementById('delete-confirm-cancel-btn');
            if (!modal || !input || !submitBtn || !cancelBtn) return;

            input.addEventListener('input', () => {
                if (!pendingDeleteFavorite) {
                    submitBtn.setAttribute('disabled', '');
                    return;
                }
                if (input.value === pendingDeleteFavorite.display_name) {
                    submitBtn.removeAttribute('disabled');
                } else {
                    submitBtn.setAttribute('disabled', '');
                }
            });

            submitBtn.addEventListener('click', () => {
                if (!pendingDeleteFavorite) return;
                const id = pendingDeleteFavorite.id;
                submitBtn.setAttribute('disabled', '');
                submitBtn.textContent = 'Deleting...';

                fetch(`/plugin-io/api/clinical_favorites/routes/favorites?id=${encodeURIComponent(id)}`, {
                    method: 'DELETE',
                    credentials: 'include'
                })
                .then(r => r.json())
                .then(data => {
                    if (data.success) {
                        modal.dismiss();
                        loadFavorites();
                    } else {
                        showBanner('delete-confirm-banner', 'error', data.error || 'Failed to delete favorite.');
                    }
                })
                .catch(() => showBanner('delete-confirm-banner', 'error', 'Error deleting favorite.'))
                .finally(() => {
                    submitBtn.textContent = 'Delete';
                    submitBtn.setAttribute('disabled', '');
                });
            });

            cancelBtn.addEventListener('click', () => modal.dismiss());

            modal.addEventListener('dismiss', () => {
                pendingDeleteFavorite = null;
                const inp = document.getElementById('delete-confirm-input');
                if (inp) inp.value = '';
                const banner = document.getElementById('delete-confirm-banner');
                if (banner) banner.innerHTML = '';
            });

            document.addEventListener('keydown', (e) => {
                if (e.key === 'Escape' && modal.isOpen) {
                    modal.dismiss();
                }
            });
        })();

        function hideDefault(defaultId, opts) {
            const silent = !!(opts && opts.silent);
            fetch('/plugin-io/api/clinical_favorites/routes/favorites/hide-default', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                credentials: 'include',
                body: JSON.stringify({ default_id: defaultId })
            })
            .then(r => r.json())
            .then(data => {
                if (data.success) {
                    if (!silent) {
                        showUndoBanner('Default hidden.', () => unhideDefault(defaultId, { silent: true }));
                    }
                    loadFavorites();
                } else {
                    showBanner('manage-banner', 'error', data.error || 'Failed to hide default.');
                }
            })
            .catch(() => showBanner('manage-banner', 'error', 'Error hiding default.'));
        }

        function unhideDefault(defaultId, opts) {
            const silent = !!(opts && opts.silent);
            fetch(`/plugin-io/api/clinical_favorites/routes/favorites/hide-default?default_id=${encodeURIComponent(defaultId)}`, {
                method: 'DELETE',
                credentials: 'include'
            })
            .then(r => r.json())
            .then(data => {
                if (data.success) {
                    if (!silent) {
                        showUndoBanner('Default restored.', () => hideDefault(defaultId, { silent: true }));
                    }
                    loadFavorites();
                    if (typeof reloadPrescribeList === 'function') {
                        reloadPrescribeList(currentPrescribeFilter);
                    }
                } else {
                    showBanner('manage-banner', 'error', data.error || 'Failed to restore default.');
                }
            })
            .catch(() => showBanner('manage-banner', 'error', 'Error restoring default.'));
        }

        function escapeHtml(text) {
            const div = document.createElement('div');
            div.textContent = text;
            return div.innerHTML;
        }

        function formatQuantityUnit(quantity, unit) {
            if (!unit) return '';
            const unitLower = unit.toLowerCase();
            const prefix = /^\d/.test(unit) ? 'x ' : '';
            return `${Math.floor(quantity || 0)} ${prefix}${unitLower}s`;
        }

        function renderWithGroups(rows, renderRow, options) {
            if (!rows || rows.length === 0) return '';
            options = options || {};
            const columns = options.columns || null;   // if null, legacy card mode

            const groups = [];
            const groupIndex = new Map();
            rows.forEach(fav => {
                const gn = (fav.group_name || '').trim();
                if (!groupIndex.has(gn)) {
                    groupIndex.set(gn, groups.length);
                    groups.push({ name: gn, rows: [] });
                }
                groups[groupIndex.get(gn)].rows.push(fav);
            });

            const ungrouped = groups.find(g => !g.name);
            const grouped = groups.filter(g => g.name);

            const wrapRows = (rows) => {
                if (columns) {
                    return buildTable(rows, renderRow, columns);
                }
                return `<div style="display: flex; flex-direction: column; gap: 8px; padding: 4px 0;">
                    ${rows.map(renderRow).join('')}
                </div>`;
            };

            // Always render through the accordion shell so every section
            // has a header with its row counter, including the Ungrouped
            // bucket. Pinned to the top before any named group. The
            // system flag drives the italic muted treatment on the title
            // so it reads as a bucket label rather than a user-named group,
            // and survives even if a user names a real group "Ungrouped".
            const sections = [];
            if (ungrouped) {
                sections.push({ name: 'Ungrouped', rows: ungrouped.rows, system: true });
            }
            grouped.forEach(g => sections.push(g));

            if (sections.length === 0) return '';

            return `<canvas-accordion>${sections.map(g => {
                const escaped = escapeHtml(g.name);
                const titleClass = g.system ? ' class="fav-section-title-system"' : '';
                return `
                    <canvas-accordion-item open>
                        <canvas-accordion-title>
                            <span${titleClass}>${escaped}</span>
                            <canvas-badge basic size="mini">${g.rows.length}</canvas-badge>
                        </canvas-accordion-title>
                        <canvas-accordion-content>
                            ${wrapRows(g.rows)}
                        </canvas-accordion-content>
                    </canvas-accordion-item>`;
            }).join('')}</canvas-accordion>`;
        }

        function buildTable(rows, renderRow, columns) {
            const headCells = columns.map(col => {
                const cls = col.cls ? ` class="${col.cls}"` : '';
                return `<canvas-table-cell${cls}>${col.label}</canvas-table-cell>`;
            }).join('');

            return `
                <canvas-table compact>
                    <canvas-table-head>
                        <canvas-table-row>${headCells}</canvas-table-row>
                    </canvas-table-head>
                    <canvas-table-body>
                        ${rows.map(renderRow).join('')}
                    </canvas-table-body>
                </canvas-table>`;
        }

        function updateInsertButton() {
            const btn = document.getElementById('add-button');
            const bar = document.getElementById('insert-footer-bar');
            const wrap = document.getElementById('add-button-wrap');
            if (!btn || !bar || !wrap) return;
            const count = selectedFavoriteIds.size;
            const hasPatient = !!selectedPatientId && selectedPatientId !== '__placeholder__';
            const hasNote = !!selectedNoteId && selectedNoteId !== '__placeholder__';
            const ready = count > 0 && hasPatient && hasNote;
            btn.textContent = count === 0
                ? 'Insert favorites'
                : count === 1
                    ? 'Insert 1 favorite'
                    : `Insert ${count} favorites`;
            // canvas-button has no disabled property setter, so write the
            // attribute directly. Otherwise the styling and click guard drift.
            btn.toggleAttribute('disabled', !ready);
            wrap.classList.toggle('is-disabled', !ready);
            renderFooterPopup();
            updateFooterShadow();
        }

        function getSelectedPatientName() {
            if (!selectedPatientId) return '';
            return chartPatientName || '';
        }

        function getSelectedNoteName() {
            if (!selectedNoteId) return '';
            const picker = document.getElementById('note-picker');
            if (!picker) return '';
            const opt = picker.querySelector(`canvas-option[value="${selectedNoteId}"]`);
            return opt ? opt.textContent.trim() : '';
        }

        function getFavoritesBreakdown() {
            let med = 0;
            let cond = 0;
            for (const t of selectedFavoriteTypes.values()) {
                if (t === 'condition') cond++;
                else med++;
            }
            const parts = [];
            if (med) parts.push(med === 1 ? '1 medication' : `${med} medications`);
            if (cond) parts.push(cond === 1 ? '1 condition' : `${cond} conditions`);
            if (parts.length === 2) return `${parts[0]} and ${parts[1]}`;
            return parts[0] || '';
        }

        let footerPopupHideTimer = null;
        function renderFooterPopup() {
            const popup = document.getElementById('insert-footer-popup');
            if (!popup) return;
            const requiredSection = popup.querySelector('[data-popup-section="required"]');
            const selectedSection = popup.querySelector('[data-popup-section="selected"]');
            const requiredList = popup.querySelector('[data-popup-list="required"]');
            const selectedList = popup.querySelector('[data-popup-list="selected"]');
            if (!requiredSection || !selectedSection || !requiredList || !selectedList) return;

            const hasPatient = !!selectedPatientId && selectedPatientId !== '__placeholder__';
            const hasNote = !!selectedNoteId && selectedNoteId !== '__placeholder__';
            const hasFavorites = selectedFavoriteIds.size > 0;

            const requiredItems = [];
            if (!hasPatient) requiredItems.push('Patient');
            if (!hasNote) requiredItems.push('Target note');
            if (!hasFavorites) requiredItems.push('Favorites');

            const selectedItems = [];
            if (hasPatient) selectedItems.push(getSelectedPatientName() || 'Patient');
            if (hasNote) selectedItems.push(getSelectedNoteName() || 'Target note');
            if (hasFavorites) {
                const breakdown = getFavoritesBreakdown();
                if (breakdown) selectedItems.push(breakdown);
            }

            requiredList.innerHTML = requiredItems.map(t => `<li>${escapeHtml(t)}</li>`).join('');
            selectedList.innerHTML = selectedItems.map(t => `<li>${escapeHtml(t)}</li>`).join('');
            requiredSection.toggleAttribute('hidden', requiredItems.length === 0);
            selectedSection.toggleAttribute('hidden', selectedItems.length === 0);

            if (!popup.hasAttribute('hidden')) positionFooterPopup();
        }

        function positionFooterPopup() {
            const popup = document.getElementById('insert-footer-popup');
            const wrap = document.getElementById('add-button-wrap');
            if (!popup || !wrap || popup.hasAttribute('hidden')) return;
            const wrapRect = wrap.getBoundingClientRect();
            const popupRect = popup.getBoundingClientRect();
            const margin = 12;
            const desiredLeft = wrapRect.left;
            const maxLeft = window.innerWidth - popupRect.width - margin;
            const left = Math.max(margin, Math.min(desiredLeft, maxLeft));
            const top = Math.max(margin, wrapRect.top - popupRect.height - 14);
            popup.style.left = `${left}px`;
            popup.style.top = `${top}px`;
            const arrow = popup.querySelector('.fav-footer-popup-arrow');
            if (arrow) {
                const wrapCenter = wrapRect.left + (wrapRect.width / 2);
                const arrowLeft = Math.max(12, Math.min(wrapCenter - left - 6, popupRect.width - 24));
                arrow.style.left = `${arrowLeft}px`;
            }
        }

        function showFooterPopup() {
            const popup = document.getElementById('insert-footer-popup');
            if (!popup) return;
            if (footerPopupHideTimer) {
                clearTimeout(footerPopupHideTimer);
                footerPopupHideTimer = null;
            }
            popup.removeAttribute('hidden');
            positionFooterPopup();
        }

        function scheduleHideFooterPopup() {
            if (footerPopupHideTimer) clearTimeout(footerPopupHideTimer);
            footerPopupHideTimer = setTimeout(() => {
                const popup = document.getElementById('insert-footer-popup');
                if (popup) popup.setAttribute('hidden', '');
                footerPopupHideTimer = null;
            }, 120);
        }

        function hideFooterPopup() {
            if (footerPopupHideTimer) {
                clearTimeout(footerPopupHideTimer);
                footerPopupHideTimer = null;
            }
            const popup = document.getElementById('insert-footer-popup');
            if (popup) popup.setAttribute('hidden', '');
        }

        function updateFooterShadow() {
            const bar = document.getElementById('insert-footer-bar');
            if (!bar) return;
            if (bar.hasAttribute('hidden')) {
                bar.classList.remove('is-elevated');
                return;
            }
            const atBottom = window.innerHeight + window.scrollY >= document.documentElement.scrollHeight - 2;
            bar.classList.toggle('is-elevated', !atBottom);
        }
        window.addEventListener('scroll', updateFooterShadow, { passive: true });
        window.addEventListener('resize', updateFooterShadow, { passive: true });
        if (typeof ResizeObserver !== 'undefined') {
            new ResizeObserver(updateFooterShadow).observe(document.body);
        }

        function updateButtonState() { updateInsertButton(); }

        // Snapshot helpers for the search aware accordion expansion.
        // The section title span is the natural key, every group is unique
        // within one rendered list and the system Ungrouped row carries the
        // literal "Ungrouped" title.
        function captureAccordionSnapshot(listEl) {
            const snapshot = new Map();
            if (!listEl) return snapshot;
            listEl.querySelectorAll('canvas-accordion-item').forEach(item => {
                const titleEl = item.querySelector('canvas-accordion-title span');
                const key = titleEl ? titleEl.textContent : '';
                snapshot.set(key, item.hasAttribute('open'));
            });
            return snapshot;
        }

        function applyAccordionSnapshot(listEl, snapshot) {
            if (!listEl || !snapshot) return;
            listEl.querySelectorAll('canvas-accordion-item').forEach(item => {
                const titleEl = item.querySelector('canvas-accordion-title span');
                const key = titleEl ? titleEl.textContent : '';
                if (snapshot.has(key)) {
                    item.open = snapshot.get(key);
                }
            });
        }

        function expandVisibleAccordions(listEl) {
            if (!listEl) return;
            listEl.querySelectorAll('canvas-accordion-item').forEach(item => {
                if (item.style.display !== 'none') {
                    item.open = true;
                }
            });
        }

        // Expand all / Collapse all toggle for the favorites lists. Label
        // reflects the next action: "Expand all" when every item is closed,
        // "Collapse all" when at least one is open. Click flips them all to
        // the opposite of the current "any open" state.
        function syncToggleAllLabel(listId, btnId) {
            const listEl = document.getElementById(listId);
            const btn = document.getElementById(btnId);
            if (!listEl || !btn) return;
            const items = listEl.querySelectorAll('canvas-accordion-item');
            const visible = Array.from(items).filter(i => i.style.display !== 'none');
            if (visible.length === 0) {
                btn.toggleAttribute('disabled', true);
                btn.textContent = 'Expand all';
                return;
            }
            btn.toggleAttribute('disabled', false);
            const anyOpen = visible.some(i => i.hasAttribute('open'));
            btn.textContent = anyOpen ? 'Collapse all' : 'Expand all';
        }

        function bindToggleAllButton(listId, btnId) {
            const btn = document.getElementById(btnId);
            const listEl = document.getElementById(listId);
            if (!btn || !listEl) return;
            btn.addEventListener('click', () => {
                const items = listEl.querySelectorAll('canvas-accordion-item');
                const visible = Array.from(items).filter(i => i.style.display !== 'none');
                if (visible.length === 0) return;
                const anyOpen = visible.some(i => i.hasAttribute('open'));
                const target = !anyOpen;
                visible.forEach(i => { i.open = target; });
                syncToggleAllLabel(listId, btnId);
            });
            // The accordion item dispatches a bubbling toggle event, so any
            // single-item expand or collapse keeps the label in sync.
            listEl.addEventListener('toggle', () => syncToggleAllLabel(listId, btnId));
        }

        bindToggleAllButton('medication-list', 'prescribe-toggle-all-btn');
        bindToggleAllButton('favorites-list', 'manage-toggle-all-btn');

        // One delegated listener on the persistent insert list catches clicks
        // on the per-row expand toggles, which are rebuilt on every reload.
        const prescribeListEl = document.getElementById('medication-list');
        if (prescribeListEl) {
            prescribeListEl.addEventListener('click', (e) => {
                if (!e.target.closest) return;
                const toggle = e.target.closest('.fav-crow-toggle');
                if (toggle && prescribeListEl.contains(toggle)) {
                    toggleCompactRow(toggle);
                    return;
                }
                // The row body acts as the checkbox label. Clicking the name
                // or badge toggles selection, the primary action on this list,
                // by forwarding to the checkbox, which emits its own change.
                const selectRegion = e.target.closest('.fav-crow-select');
                if (selectRegion && prescribeListEl.contains(selectRegion)) {
                    const crow = selectRegion.closest('.fav-crow');
                    const checkbox = crow && crow.querySelector('canvas-checkbox');
                    if (checkbox && !checkbox.hasAttribute('disabled')) checkbox.click();
                }
            });
        }

        const prescribeSearchInput = document.getElementById('prescribe-search-input');
        if (prescribeSearchInput) {
            prescribeSearchInput.addEventListener('input', () => filterPrescribeList());
        }

        const manageSearchInput = document.getElementById('manage-search-input');
        if (manageSearchInput) {
            manageSearchInput.addEventListener('input', () => renderFavoritesList());
        }

        const scopeTabsInsertEl = document.getElementById('scope-tabs-insert');
        if (scopeTabsInsertEl) {
            scopeTabsInsertEl.addEventListener('tab-change', function(e) {
                if (e.target.id !== 'scope-tabs-insert') return;
                const panel = e.detail && e.detail.panel;
                const value = panel === 'scope-insert-mine' ? 'mine'
                    : panel === 'scope-insert-shared' ? 'shared'
                    : 'all';
                setPrescribeFilter(value);
            });
        }

        const scopeTabsManageEl = document.getElementById('scope-tabs-manage');
        if (scopeTabsManageEl) {
            scopeTabsManageEl.addEventListener('tab-change', function(e) {
                if (e.target.id !== 'scope-tabs-manage') return;
                const panel = e.detail && e.detail.panel;
                const value = panel === 'scope-manage-mine' ? 'mine'
                    : panel === 'scope-manage-shared' ? 'shared'
                    : 'all';
                setManageFilter(value);
            });
        }

        const manageSortEl = document.getElementById('manage-sort');
        if (manageSortEl) {
            manageSortEl.addEventListener('change', function(e) {
                setManageSort(e.target.value);
            });
        }

        const addButton = document.getElementById('add-button');
        if (addButton) {
            addButton.addEventListener('click', requestInsert);
        }

        (function wireFooterPopup() {
            const wrap = document.getElementById('add-button-wrap');
            const popup = document.getElementById('insert-footer-popup');
            if (!wrap || !popup) return;

            wrap.addEventListener('mouseenter', showFooterPopup);
            wrap.addEventListener('mouseleave', scheduleHideFooterPopup);
            wrap.addEventListener('focusin', showFooterPopup);
            wrap.addEventListener('focusout', scheduleHideFooterPopup);

            popup.addEventListener('mouseenter', () => {
                if (footerPopupHideTimer) {
                    clearTimeout(footerPopupHideTimer);
                    footerPopupHideTimer = null;
                }
            });
            popup.addEventListener('mouseleave', scheduleHideFooterPopup);

            document.addEventListener('keydown', (e) => {
                if (e.key === 'Escape' && !popup.hasAttribute('hidden')) {
                    hideFooterPopup();
                }
            });

            window.addEventListener('blur', hideFooterPopup);
            document.addEventListener('visibilitychange', () => {
                if (document.hidden) hideFooterPopup();
            });

            const repositionIfShown = () => {
                if (!popup.hasAttribute('hidden')) positionFooterPopup();
            };
            window.addEventListener('scroll', repositionIfShown, { passive: true });
            window.addEventListener('resize', repositionIfShown, { passive: true });
        })();

        function requestInsert() {
            if (addButton.hasAttribute('disabled')) return;
            const selected = Array.from(selectedFavoriteIds);
            if (selected.length === 0) {
                showBanner('insert-banner', 'error', 'Select at least one favorite.');
                return;
            }
            if (!selectedPatientId) {
                showBanner('insert-banner', 'error', 'Choose a patient before inserting.');
                return;
            }
            const notePicker = document.getElementById('note-picker');
            const noteId = notePicker ? notePicker.value : '';
            if (!noteId) {
                showBanner('insert-banner', 'error', 'Choose a target note before inserting.');
                return;
            }

            const patientText = chartPatientName || 'this patient';
            const noteOption = notePicker.querySelector(`canvas-option[value="${noteId}"]`);
            const noteText = noteOption ? noteOption.textContent.trim() : 'the selected note';

            const meds = [];
            const conds = [];
            selected.forEach(id => {
                const type = selectedFavoriteTypes.get(id) || 'medication';
                const name = selectedFavoriteNames.get(id) || '';
                if (!name) return;
                if (type === 'condition') conds.push(name);
                else meds.push(name);
            });
            const collator = new Intl.Collator(undefined, { sensitivity: 'base' });
            meds.sort(collator.compare);
            conds.sort(collator.compare);

            document.getElementById('insert-confirm-note').textContent = noteText;
            document.getElementById('insert-confirm-patient').textContent = patientText;

            const medsSection = document.getElementById('insert-confirm-meds-section');
            const medsList = document.getElementById('insert-confirm-meds-list');
            medsList.innerHTML = meds.map(n => `<li>${escapeHtml(n)}</li>`).join('');
            medsSection.toggleAttribute('hidden', meds.length === 0);

            const condsSection = document.getElementById('insert-confirm-conds-section');
            const condsList = document.getElementById('insert-confirm-conds-list');
            condsList.innerHTML = conds.map(n => `<li>${escapeHtml(n)}</li>`).join('');
            condsSection.toggleAttribute('hidden', conds.length === 0);

            document.getElementById('insert-confirm-modal').open();
        }

        function performInsert() {
            const selected = Array.from(selectedFavoriteIds);
            const notePicker = document.getElementById('note-picker');
            const noteId = notePicker ? notePicker.value : '';

            addButton.setAttribute('disabled', '');
            addButton.textContent = 'Inserting...';

            fetch('/plugin-io/api/clinical_favorites/routes/insert', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                credentials: 'include',
                body: JSON.stringify({
                    patient_id: selectedPatientId,
                    note_id: noteId,
                    favorite_ids: selected,
                }),
            })
            .then(r => r.json())
            .then(data => {
                if (data.success) {
                    const skipped = (data.skipped || []).length;
                    selectedFavoriteIds.clear();
                    selectedFavoriteTypes.clear();
                    selectedFavoriteNames.clear();
                    if (typeof reloadPrescribeList === 'function') {
                        reloadPrescribeList(currentPrescribeFilter);
                    }
                    if (skipped) {
                        showBanner('insert-banner', 'error',
                            skipped === 1
                                ? '1 favorite was skipped server side.'
                                : `${skipped} favorites were skipped server side.`);
                    }
                } else {
                    showBanner('insert-banner', 'error', data.error || 'Failed to insert favorites.');
                }
            })
            .catch(() => showBanner('insert-banner', 'error', 'An error occurred.'))
            .finally(() => {
                addButton.textContent = 'Insert favorites';
                updateInsertButton();
            });
        }

        (function wireInsertConfirm() {
            const modal = document.getElementById('insert-confirm-modal');
            const cancelBtn = document.getElementById('insert-confirm-cancel-btn');
            const submitBtn = document.getElementById('insert-confirm-submit-btn');
            if (!modal || !cancelBtn || !submitBtn) return;

            cancelBtn.addEventListener('click', () => modal.dismiss());
            submitBtn.addEventListener('click', () => {
                modal.dismiss();
                performInsert();
            });

            document.addEventListener('keydown', (e) => {
                if (e.key === 'Escape' && modal.isOpen) {
                    modal.dismiss();
                }
            });
        })();

        // When the pinned patient has no open notes there is nothing to insert
        // into, so swap the whole insert surface for a clear notice rather than
        // leaving a dead disabled Insert button under an empty note picker.
        function showNoNotesState(noNotes) {
            const notice = document.getElementById('no-notes-notice');
            const main = document.getElementById('insert-main');
            if (notice) notice.toggleAttribute('hidden', !noNotes);
            if (main) main.toggleAttribute('hidden', noNotes);
        }

        function updateInsertEmptyState(isEmpty, isFirstUse) {
            const el = document.getElementById('insert-empty-state');
            if (!el) return;
            if (!isEmpty) {
                el.style.display = 'none';
                el.innerHTML = '';
                return;
            }
            el.style.display = '';
            if (isFirstUse) {
                el.innerHTML = `<div style="padding: 0; text-align: left;">
                    <div style="color: var(--text-tertiary); font-size: 14px;">No favorites yet. Add them under Manage to start using them in notes.</div>
                </div>`;
            } else {
                el.innerHTML = `<div style="padding: 48px 24px; text-align: center;">
                    <div style="color: var(--text-tertiary); font-size: 15px; margin-bottom: 12px;">No favorites match your filters.</div>
                    <canvas-button variant="ghost" id="empty-clear-insert-filters-btn">Clear filters</canvas-button>
                </div>`;
                const btn = el.querySelector('#empty-clear-insert-filters-btn');
                if (btn) btn.addEventListener('click', clearInsertFilters);
            }
        }

        function clearInsertFilters() {
            currentPrescribeFilter = 'all';
            const allTab = document.querySelector('#scope-tabs-insert canvas-tab[for="scope-insert-all"]');
            if (allTab && typeof allTab.click === 'function') allTab.click();
            const searchInput = document.getElementById('prescribe-search-input');
            if (searchInput) searchInput.value = '';
            reloadPrescribeList('all');
        }

        function clearManageFilters() {
            currentManageFilter = 'all';
            const allTab = document.querySelector('#scope-tabs-manage canvas-tab[for="scope-manage-all"]');
            if (allTab && typeof allTab.click === 'function') allTab.click();
            const searchInput = document.getElementById('manage-search-input');
            if (searchInput) searchInput.value = '';
            renderFavoritesList();
        }

        function showBanner(containerId, variant, text, opts) {
            const container = document.getElementById(containerId);
            if (!container) return;
            container.innerHTML = '';
            const banner = document.createElement('canvas-banner');
            banner.setAttribute('variant', variant);
            if (opts && opts.retry) {
                const msg = document.createTextNode(text + ' ');
                banner.appendChild(msg);
                const retryBtn = document.createElement('canvas-button');
                retryBtn.setAttribute('size', 'sm');
                retryBtn.setAttribute('variant', 'ghost');
                retryBtn.textContent = 'Retry';
                retryBtn.addEventListener('click', opts.retry);
                banner.appendChild(retryBtn);
            } else {
                banner.textContent = text;
            }
            container.appendChild(banner);
            if (opts && opts.autoDismiss) {
                setTimeout(() => {
                    if (container.contains(banner)) banner.remove();
                }, opts.autoDismiss);
            }
            container.addEventListener('dismiss', function onDismiss(e) {
                if (e.target === banner) {
                    banner.remove();
                    container.removeEventListener('dismiss', onDismiss);
                }
            });
        }

        function showUndoBanner(text, onUndo) {
            const container = document.getElementById('manage-banner');
            if (!container) return;
            container.innerHTML = '';
            const banner = document.createElement('canvas-banner');
            banner.setAttribute('variant', 'info');
            banner.appendChild(document.createTextNode(text + ' '));
            const undoBtn = document.createElement('canvas-button');
            undoBtn.setAttribute('size', 'sm');
            undoBtn.setAttribute('variant', 'ghost');
            undoBtn.textContent = 'Undo';
            banner.appendChild(undoBtn);
            container.appendChild(banner);

            const timerId = setTimeout(() => {
                if (container.contains(banner)) banner.remove();
            }, 5000);
            banner._undoTimer = timerId;

            undoBtn.addEventListener('click', () => {
                clearTimeout(banner._undoTimer);
                if (container.contains(banner)) banner.remove();
                onUndo();
            });

            container.addEventListener('dismiss', function onDismiss(e) {
                if (e.target === banner) {
                    clearTimeout(banner._undoTimer);
                    banner.remove();
                    container.removeEventListener('dismiss', onDismiss);
                }
            });
        }
