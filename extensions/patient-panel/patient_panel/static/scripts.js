// Inline metadata edit. POSTs a single key/value upsert to the cheap
// per-patient endpoint and does NOT reload the table — the control's own value
// is the new display, so the optimized spine query is never re-run. On failure
// we revert the control to its previous value rather than pretend it saved.
// Note: if the table is currently sorted by this column, the edited row stays
// in place until the next navigation/refresh (intentional — no re-query).
function updateMetadata(el, patientId, key) {
  const newValue = el.value;
  const prevValue = el.dataset.prevValue || '';
  if (newValue === prevValue) return;

  el.disabled = true;
  const formData = new FormData();
  formData.append('value', newValue);

  fetch('/plugin-io/api/patient_panel/app/' + encodeURIComponent(patientId) +
        '/metadata/' + encodeURIComponent(key), {
    method: 'POST',
    body: formData,
  }).then(function(response) {
    if (!response.ok) throw new Error('update failed: ' + response.status);
    el.dataset.prevValue = newValue;
  }).catch(function() {
    el.value = prevValue;
    window.alert('Could not update value. Please try again.');
  }).finally(function() {
    el.disabled = false;
  });
}

function toggleAccordion(patientId, contentType, url, event) {
  event.preventDefault(); // Prevent default link behavior

  const content = document.getElementById(`accordion-${patientId}`);
  const isCurrentlyOpen = content.style.display === "table-row";
  const currentType = content.getAttribute("data-content-type");
  const clickedLink = event.currentTarget;

  // If clicking the same type that's already open, just close it
  if (isCurrentlyOpen && currentType === contentType) {
    hideAccordions();
    return;
  }

  // Close other accordions and remove active states
  hideAccordions();

  // Open this accordion and track what type of content it's showing
  content.style.display = "table-row";
  content.setAttribute("data-content-type", contentType);

  // Add active class to clicked link
  clickedLink.classList.add("active");

  // Load the content via HTMX
  htmx.ajax('GET', url, {target: `#accordion-${patientId}`, swap: 'innerHTML'});
}

function hideAccordions() {
  const allAccordions = document.querySelectorAll(".accordion-content");
  allAccordions.forEach((accordion) => {
    accordion.style.display = "none";
  });
  // Remove active class from all fraction links
  document.querySelectorAll(".fraction a.active").forEach((link) => {
    link.classList.remove("active");
  });
}

// Pin the accordion content to the visible portion of the table scroll
// container so the expansion is reachable even when scrolled far right.
// Without this, the expansion renders inside a full-table-width `<td>`
// anchored at the table's left edge — invisible on horizontal scroll.
function sizeAccordionDetailsToViewport(row) {
  const details = row.querySelector(".accordion-details");
  if (!details) return;
  const container = document.querySelector(".table-scroll-container");
  if (!container) return;
  const width = container.clientWidth;
  if (width > 0) {
    details.style.width = (width - 23) + "px";
    details.style.maxWidth = (width - 23) + "px";
  }
}

function resizeAllOpenAccordionDetails() {
  document
    .querySelectorAll('.accordion-content[style*="table-row"]')
    .forEach(sizeAccordionDetailsToViewport);
}

window.addEventListener("resize", function () {
  resizeAllOpenAccordionDetails();
});

// Inject a sticky panel header (patient name + close button) as the first child
// of the accordion details panel after HTMX swap. The panel scrolls internally
// (CSS max-height/overflow-y), so this header stays pinned at the panel top
// while the user scrolls the content — keeping the patient context without
// touching the table scroll. Close is wired to hideAccordions().
function addAccordionPanelHeader(row) {
  const details = row.querySelector(".accordion-details");
  if (!details || details.querySelector(".accordion-panel-header")) return;

  const patientId = row.id.replace("accordion-", "");
  const nameEl = document.querySelector(
    `.patient-row[data-patient-id="${patientId}"] .patient-name`
  );

  const header = document.createElement("div");
  header.className = "accordion-panel-header";

  const label = document.createElement("span");
  label.className = "accordion-panel-patient";
  label.textContent = nameEl ? nameEl.textContent.trim() : "";
  header.appendChild(label);

  const btn = document.createElement("button");
  btn.type = "button";
  btn.className = "accordion-close-btn";
  btn.setAttribute("aria-label", "Close");
  btn.textContent = "×";
  btn.addEventListener("click", function (e) {
    e.stopPropagation();
    hideAccordions();
  });
  header.appendChild(btn);

  details.insertBefore(header, details.firstChild);
}

document.addEventListener("htmx:afterSwap", function (e) {
  if (e.target && e.target.classList && e.target.classList.contains("accordion-content")) {
    addAccordionPanelHeader(e.target);
    sizeAccordionDetailsToViewport(e.target);
  }
});

// Click-outside-to-close for accordions — mirrors the column picker pattern.
document.addEventListener("click", function (e) {
  // Don't interfere with the fraction link toggle (it manages its own state).
  if (e.target.closest(".fraction a")) return;
  // Clicks inside the open accordion stay open.
  if (e.target.closest(".accordion-content")) return;
  // Only close if at least one accordion is currently visible.
  const open = document.querySelector('.accordion-content[style*="table-row"]');
  if (open) {
    hideAccordions();
  }
});

// Task comments accordion with single-open behavior
function toggleTaskComments(taskId) {
  // Collapse every OTHER task by walking each .task-item, so each task's
  // section and icon are resolved from the SAME element. (Previously two
  // parallel NodeLists were zipped by index, which misaligns/throws when
  // the counts or DOM order differ.)
  document.querySelectorAll(".task-item").forEach((item) => {
    if (item.getAttribute("data-task-id") === taskId) return;
    const section = item.querySelector(".task-comments-section");
    const icon = item.querySelector(".task-accordion-icon");
    if (section) section.style.display = "none";
    if (icon) {
      icon.textContent = "\u25B2";
      icon.style.transform = "rotate(0deg)";
    }
  });

  // Toggle the clicked task's comments
  const targetSection = document.getElementById(`task-comments-${taskId}`);
  const targetIcon = document.querySelector(
    `[data-task-id="${taskId}"] .task-accordion-icon`
  );
  if (!targetSection) return;

  const isHidden =
    targetSection.style.display === "none" ||
    targetSection.style.display === "";
  if (isHidden) {
    targetSection.style.display = "block";
    if (targetIcon) targetIcon.style.transform = "rotate(180deg)";
  } else {
    targetSection.style.display = "none";
    if (targetIcon) {
      targetIcon.textContent = "\u25B2";
      targetIcon.style.transform = "rotate(0deg)";
    }
  }
}

// Clear comment form function
function clearCommentForm(taskId) {
  const commentInput = document.getElementById(`comment-input-${taskId}`);
  if (commentInput) {
    commentInput.value = "";
    commentInput.blur();
  }
}

// Auto-resize textarea as user types
document.addEventListener("input", function (e) {
  if (e.target.classList.contains("comment-input")) {
    e.target.style.height = "auto";
    e.target.style.height = `${e.target.scrollHeight}px`;
  }
});

// Focus management for comment forms
document.addEventListener("click", function (e) {
  if (e.target.classList.contains("comment-input")) {
    e.target.style.minHeight = "80px";
  }
});

// Clinical note Escape key handler — cancel edit without saving
document.addEventListener('keydown', function(e) {
  if (e.key === 'Escape' && e.target.classList.contains('clinical-note-input')) {
    e.preventDefault();
    // Remove hx-trigger to prevent blur from auto-saving
    e.target.removeAttribute('hx-trigger');
    // Find the patient ID from the target attribute
    const hxTarget = e.target.closest('[hx-target]') || e.target;
    const targetSelector = hxTarget.getAttribute('hx-target') || '';
    const match = targetSelector.match(/clinical-note-(.+)/);
    if (match) {
      const patientId = match[1];
      // Load the view (cancel)
      htmx.ajax('GET', `/plugin-io/api/patient_panel/app/${patientId}/clinical-note/view`, {
        target: `#clinical-note-${patientId}`,
        swap: 'innerHTML'
      });
    }
  }
});

// Auto-resize sticky note textarea
function autoResizeTextarea(textarea) {
  textarea.style.height = 'auto';
  textarea.style.height = Math.min(textarea.scrollHeight, 200) + 'px';
}

// Handle sticky note textarea auto-resize on input
document.addEventListener('input', function(e) {
  if (e.target.classList.contains('clinical-note-input')) {
    autoResizeTextarea(e.target);
  }
});

// Auto-resize on initial load (when edit mode is shown)
document.addEventListener('htmx:afterSwap', function(e) {
  const textarea = e.detail.target.querySelector('.clinical-note-input');
  if (textarea) {
    autoResizeTextarea(textarea);
  }
  // Re-initialize truncation when clinical note view is restored after save
  const clinicalNoteText = e.detail.target.querySelector('.clinical-note-text');
  if (clinicalNoteText) {
    requestAnimationFrame(() => initClinicalNoteTruncation());
  }
});

// Flag Color Picker Functions
// Stays in the DOM — uses position:absolute with upward flip when near scroll container bottom.

function _closeFlagDropdown(opt) {
  opt.classList.remove('open', 'open-up');
  const td = opt.closest('td');
  if (td) td.style.zIndex = '';
}

function toggleFlagOptions(patientId) {
  const container = document.getElementById(`flag-picker-${patientId}`);
  const options = container.querySelector('.flag-options');

  // Close all other open flag dropdowns first
  document.querySelectorAll('.flag-options.open').forEach(opt => {
    if (opt !== options) _closeFlagDropdown(opt);
  });

  // Toggle current one
  if (options.classList.contains('open')) {
    _closeFlagDropdown(options);
  } else {
    // Raise td z-index above other sticky cells
    const td = options.closest('td');
    if (td) td.style.zIndex = '50';

    // Check if there is room below within the scroll container
    const scrollContainer = container.closest('.table-scroll-container');
    const avatarRect = container.getBoundingClientRect();
    const scrollRect = scrollContainer ? scrollContainer.getBoundingClientRect() : { bottom: window.innerHeight };
    const spaceBelow = scrollRect.bottom - avatarRect.bottom;

    // Dropdown is ~140px; flip upward if not enough space below
    if (spaceBelow < 160) {
      options.classList.add('open', 'open-up');
    } else {
      options.classList.add('open');
    }
  }
}

function selectFlag(patientId, color) {
  const container = document.getElementById(`flag-picker-${patientId}`);
  const avatar = container.querySelector('.patient-avatar');
  const options = container.querySelector('.flag-options');

  // Update avatar ring class
  avatar.classList.remove('flag-green', 'flag-yellow', 'flag-red');
  if (color) {
    avatar.classList.add(`flag-${color}`);
  }

  // Mark active option
  options.querySelectorAll('.flag-option-btn').forEach(btn => {
    btn.classList.remove('active');
  });
  const activeBtn = options.querySelector(`[data-color="${color}"]`);
  if (activeBtn) activeBtn.classList.add('active');

  // Close dropdown
  _closeFlagDropdown(options);
}

// Close flag options when clicking outside
document.addEventListener('click', function(e) {
  if (!e.target.closest('.flag-picker-container')) {
    document.querySelectorAll('.flag-options.open').forEach(opt => {
      _closeFlagDropdown(opt);
    });
  }
});

// Care Team Popup Functions
function toggleCareTeamPopup(patientId) {
  const popup = document.getElementById(`care-team-popup-${patientId}`);
  const wasOpen = popup.classList.contains('open');

  // Close all other open care team popups first
  document.querySelectorAll('.care-team-popup.open').forEach(p => {
    p.classList.remove('open');
  });

  // Toggle current one
  if (!wasOpen) {
    popup.classList.add('open');
  }
}

// Close care team popups when clicking outside
document.addEventListener('click', function(e) {
  if (!e.target.closest('.care-team-container')) {
    document.querySelectorAll('.care-team-popup.open').forEach(popup => {
      popup.classList.remove('open');
    });
  }
});

// Filter Dropdown Functions
function toggleFilterDropdown(dropdownId) {
  const dropdown = document.getElementById(dropdownId);
  const wasOpen = dropdown.classList.contains('open');

  // Close all other dropdowns
  document.querySelectorAll('.filter-dropdown.open').forEach(dd => {
    dd.classList.remove('open');
    // Clear search when closing
    const searchInput = dd.querySelector('.dropdown-search input');
    if (searchInput) {
      searchInput.value = '';
      filterDropdownOptions(dd.id, '');
    }
  });

  // Toggle current one
  if (!wasOpen) {
    dropdown.classList.add('open');
    // Focus search input if present
    const searchInput = dropdown.querySelector('.dropdown-search input');
    if (searchInput) {
      setTimeout(() => searchInput.focus(), 100);
    }
  }
}

// Debounced dropdown search to avoid filtering on every keystroke
const _dropdownSearchTimers = {};
function filterDropdownOptionsDebounced(dropdownId, searchText) {
  clearTimeout(_dropdownSearchTimers[dropdownId]);
  _dropdownSearchTimers[dropdownId] = setTimeout(() => {
    filterDropdownOptions(dropdownId, searchText);
  }, 150);
}

function filterDropdownOptions(dropdownId, searchText) {
  const dropdown = document.getElementById(dropdownId);
  const options = dropdown.querySelectorAll('.dropdown-option[data-search]');
  const searchLower = searchText.toLowerCase().trim();

  options.forEach(option => {
    const searchValue = option.getAttribute('data-search').toLowerCase();
    if (searchLower === '' || searchValue.includes(searchLower)) {
      option.classList.remove('hidden');
    } else {
      option.classList.add('hidden');
    }
  });
}

function initFilterDropdowns() {
  // Add event listeners to all filter checkboxes
  document.querySelectorAll('.filter-dropdown').forEach(dropdown => {
    const allCheckbox = dropdown.querySelector('input[id$="-all"]');
    const optionCheckboxes = dropdown.querySelectorAll('.dropdown-option[data-value] input[type="checkbox"]');

    // Initialize checkboxes from data-values attribute
    const selectedValues = dropdown.getAttribute('data-values');
    if (selectedValues) {
      const values = selectedValues.split(',').filter(v => v.trim());
      if (values.length > 0) {
        if (allCheckbox) allCheckbox.checked = false;
        optionCheckboxes.forEach(cb => {
          cb.checked = values.includes(cb.value);
        });
      }
    }

    // Handle "All" checkbox
    if (allCheckbox) {
      allCheckbox.addEventListener('change', function() {
        if (this.checked) {
          optionCheckboxes.forEach(cb => cb.checked = false);
          updateDropdownDisplay(dropdown);
          applyFilters();
        }
      });
    }

    // Handle individual option checkboxes
    optionCheckboxes.forEach(checkbox => {
      checkbox.addEventListener('change', function() {
        if (this.checked && allCheckbox) {
          allCheckbox.checked = false;
        }
        // If no options selected, check "All"
        const anyChecked = Array.from(optionCheckboxes).some(cb => cb.checked);
        if (!anyChecked && allCheckbox) {
          allCheckbox.checked = true;
        }
        updateDropdownDisplay(dropdown);
        applyFilters();
      });
    });

    // Update display based on initial state
    updateDropdownDisplay(dropdown);
  });
}

function updateDropdownDisplay(dropdown) {
  const optionCheckboxes = dropdown.querySelectorAll('.dropdown-option[data-value] input[type="checkbox"]:checked');
  const placeholderText = dropdown.querySelector('.placeholder-text');
  const label = placeholderText.textContent.split(':')[0];
  const count = optionCheckboxes.length;

  if (count === 0) {
    placeholderText.textContent = `${label}: Any`;
  } else {
    placeholderText.textContent = `${label}: ${count} selected`;
  }

  // Update data-values attribute
  const values = Array.from(optionCheckboxes).map(cb => cb.value).join(',');
  dropdown.setAttribute('data-values', values);
}

// Debounced patient search — auto-applies filters after typing stops
let _patientSearchTimer = null;
function debouncedPatientSearch() {
  clearTimeout(_patientSearchTimer);
  _patientSearchTimer = setTimeout(function() {
    applyFilters();
  }, 400);
}

function applyFilters() {
  const filtersDiv = document.querySelector('.filters');
  const patientSearch = document.getElementById('patient-search-input')?.value || '';

  // Get comma-separated values from each dropdown
  const staffIds = document.getElementById('staff-dropdown')?.getAttribute('data-values') || '';
  const insurances = document.getElementById('insurance-dropdown')?.getAttribute('data-values') || '';
  const facilityIds = document.getElementById('facility-dropdown')?.getAttribute('data-values') || '';
  const protocols = document.getElementById('protocol-dropdown')?.getAttribute('data-values') || '';

  // Get current sort params
  const sortBy = filtersDiv?.getAttribute('data-sort-by') || '';
  const sortDir = filtersDiv?.getAttribute('data-sort-dir') || '';

  // Flagged only toggle
  const flaggedOnly = filtersDiv?.getAttribute('data-flagged-only') === '1';

  // Current page size
  const pageSize = filtersDiv?.getAttribute('data-page-size') || '';

  // Build query string
  const params = new URLSearchParams();
  if (patientSearch) params.append('patient_search', patientSearch);
  if (staffIds) params.append('staff_ids', staffIds);
  if (insurances) params.append('insurances', insurances);
  // Disable auto-filter since user is explicitly applying filters
  params.append('no_auto_filter', '1');
  if (facilityIds) params.append('facility_ids', facilityIds);
  if (protocols) params.append('protocols', protocols);
  if (sortBy) params.append('sort_by', sortBy);
  if (sortDir) params.append('sort_dir', sortDir);
  if (flaggedOnly) params.append('flagged_only', '1');
  if (pageSize) params.append('page_size', pageSize);

  // Metadata-column filters: collect every <metadata-*-dropdown> and emit
  // `metadata_<key>=v1,v2` only for those with a non-empty selection.
  document.querySelectorAll('.metadata-filter-dropdown').forEach(dd => {
    const key = dd.getAttribute('data-metadata-key');
    const values = dd.getAttribute('data-values') || '';
    if (key && values) {
      params.append(`metadata_${key}`, values);
    }
  });

  // Close all dropdowns
  document.querySelectorAll('.filter-dropdown.open').forEach(dd => {
    dd.classList.remove('open');
  });

  // Trigger HTMX request
  const url = `/plugin-io/api/patient_panel/app/table?${params.toString()}`;
  htmx.ajax('GET', url, {target: '#table', swap: 'innerHTML'});
}

function clearFilters() {
  // Clear patient search
  const searchInput = document.getElementById('patient-search-input');
  if (searchInput) searchInput.value = '';

  // Reset all dropdowns to "All"
  document.querySelectorAll('.filter-dropdown').forEach(dropdown => {
    // Uncheck all option checkboxes
    dropdown.querySelectorAll('.dropdown-option[data-value] input[type="checkbox"]').forEach(cb => {
      cb.checked = false;
    });
    // Check the "All" checkbox
    const allCheckbox = dropdown.querySelector('.dropdown-option:not([data-value]) input[type="checkbox"]');
    if (allCheckbox) allCheckbox.checked = true;
    // Clear data-values
    dropdown.setAttribute('data-values', '');
    // Update display
    updateDropdownDisplay(dropdown);
  });

  // Close all dropdowns
  document.querySelectorAll('.filter-dropdown.open').forEach(dd => {
    dd.classList.remove('open');
  });

  // Trigger HTMX request with no_auto_filter flag
  const params = new URLSearchParams();
  params.append('no_auto_filter', '1');
  const url = `/plugin-io/api/patient_panel/app/table?${params.toString()}`;
  htmx.ajax('GET', url, {target: '#table', swap: 'innerHTML'});
}

// Close filter dropdowns when clicking outside
document.addEventListener('click', function(e) {
  if (!e.target.closest('.filter-dropdown') && !e.target.closest('.filter-apply-btn') && !e.target.closest('.filter-clear-btn')) {
    document.querySelectorAll('.filter-dropdown.open').forEach(dd => {
      dd.classList.remove('open');
    });
  }
});

// Sort column handling
function sortByColumn(column) {
  const filtersDiv = document.querySelector('.filters');
  const currentSortBy = filtersDiv?.getAttribute('data-sort-by') || '';
  const currentSortDir = filtersDiv?.getAttribute('data-sort-dir') || 'asc';

  // Toggle direction if same column, otherwise default to asc
  let newSortDir = 'asc';
  if (column === currentSortBy) {
    newSortDir = currentSortDir === 'asc' ? 'desc' : 'asc';
  }

  // Update data attributes
  filtersDiv?.setAttribute('data-sort-by', column);
  filtersDiv?.setAttribute('data-sort-dir', newSortDir);

  // Apply filters with new sort
  applyFiltersWithSort(column, newSortDir);
}

function applyFiltersWithSort(sortBy, sortDir) {
  const filtersDiv = document.querySelector('.filters');
  const patientSearch = document.getElementById('patient-search-input')?.value || '';

  // Get comma-separated values from each dropdown
  const staffIds = document.getElementById('staff-dropdown')?.getAttribute('data-values') || '';
  const insurances = document.getElementById('insurance-dropdown')?.getAttribute('data-values') || '';
  const facilityIds = document.getElementById('facility-dropdown')?.getAttribute('data-values') || '';
  const protocols = document.getElementById('protocol-dropdown')?.getAttribute('data-values') || '';
  const flaggedOnly = filtersDiv?.getAttribute('data-flagged-only') === '1';

  // Current page size
  const pageSize = filtersDiv?.getAttribute('data-page-size') || '';

  // Build query string
  const params = new URLSearchParams();
  if (patientSearch) params.append('patient_search', patientSearch);
  if (staffIds) params.append('staff_ids', staffIds);
  if (insurances) params.append('insurances', insurances);
  // Disable auto-filter since user is explicitly sorting/filtering
  params.append('no_auto_filter', '1');
  if (facilityIds) params.append('facility_ids', facilityIds);
  if (protocols) params.append('protocols', protocols);
  if (sortBy) params.append('sort_by', sortBy);
  if (sortDir) params.append('sort_dir', sortDir);
  if (flaggedOnly) params.append('flagged_only', '1');
  if (pageSize) params.append('page_size', pageSize);

  document.querySelectorAll('.metadata-filter-dropdown').forEach(dd => {
    const key = dd.getAttribute('data-metadata-key');
    const values = dd.getAttribute('data-values') || '';
    if (key && values) {
      params.append(`metadata_${key}`, values);
    }
  });

  // Trigger HTMX request
  const url = `/plugin-io/api/patient_panel/app/table?${params.toString()}`;
  htmx.ajax('GET', url, {target: '#table', swap: 'innerHTML'});
}

function changePageSize(newSize) {
  const filtersDiv = document.querySelector('.filters');
  if (filtersDiv) filtersDiv.setAttribute('data-page-size', newSize);
  applyFilters();
}

function initSortableHeaders() {
  document.querySelectorAll('.patient-table th.sortable').forEach(th => {
    th.addEventListener('click', function() {
      const sortColumn = this.getAttribute('data-sort');
      if (sortColumn) {
        sortByColumn(sortColumn);
      }
    });
  });
}

// Enter-key shortcut for patient search (auto-search on input is handled by debouncedPatientSearch)
function initAutoSearch() {
  const searchInput = document.getElementById('patient-search-input');
  if (!searchInput || searchInput.dataset.autoSearchBound) return;
  searchInput.dataset.autoSearchBound = 'true';

  searchInput.addEventListener('keyup', function(e) {
    if (e.key === 'Enter') {
      clearTimeout(_patientSearchTimer);
      applyFilters();
    }
  });
}

// The .table-scroll-container lives inside #table, so an innerHTML swap
// (sort/filter/pagination) recreates it and resets horizontal scroll to 0.
// Capture scrollLeft before the swap and restore it after so the user stays
// where they were (e.g. sorting by Risk doesn't yank them back to the left).
let _savedTableScrollLeft = 0;
document.addEventListener('htmx:beforeSwap', function(e) {
  if (e.detail.target && e.detail.target.id === 'table') {
    const sc = document.querySelector('.table-scroll-container');
    _savedTableScrollLeft = sc ? sc.scrollLeft : 0;
  }
});

// Initialize dropdowns after HTMX swaps
document.addEventListener('htmx:afterSwap', function(e) {
  if (e.detail.target.id === 'table' || e.detail.target.closest('.filters')) {
    initFilterDropdowns();
    initSortableHeaders();
    initAutoSearch();
    initAvatarSkeletons();
    requestAnimationFrame(() => {
      initClinicalNoteTruncation();
      initCellTruncationTooltips();
    });
  }
  // Persist the full view state after each table render (init above has
  // reconciled the dropdown data-values) so it survives a full page reload.
  if (e.detail.target.id === 'table') {
    const sc = document.querySelector('.table-scroll-container');
    if (sc) sc.scrollLeft = _savedTableScrollLeft;
    persistTableState();
  }
});


function initAvatarSkeletons() {
  const MIN_SKELETON_MS = 200;
  const selectors = [
    '.patient-avatar img',
    '.care-team-bubble img',
    '.care-team-popup-avatar img',
  ];
  document.querySelectorAll(selectors.join(',')).forEach(img => {
    if (img.dataset.skeletonBound === '1') return;
    img.dataset.skeletonBound = '1';

    const wrapper = img.parentElement;
    if (!wrapper) return;

    wrapper.classList.add('avatar-skeleton');
    const start = performance.now();

    const finish = () => {
      const remaining = Math.max(0, MIN_SKELETON_MS - (performance.now() - start));
      setTimeout(() => {
        wrapper.classList.remove('avatar-skeleton');
        img.classList.add('loaded');
      }, remaining);
    };

    const errored = () => {
      wrapper.classList.remove('avatar-skeleton');
    };

    if (img.complete && img.naturalWidth > 0) {
      finish();
    } else {
      img.addEventListener('load', finish, { once: true });
      img.addEventListener('error', errored, { once: true });
    }
  });
}

// Clinical Note Truncation Functions
function toggleClinicalNote(patientId) {
  const textEl = document.getElementById(`clinical-note-text-${patientId}`);
  const toggleBtn = document.getElementById(`clinical-note-toggle-${patientId}`);

  if (textEl.classList.contains('expanded')) {
    textEl.classList.remove('expanded');
    toggleBtn.textContent = 'more';
  } else {
    textEl.classList.add('expanded');
    toggleBtn.textContent = 'less';
  }
}

function initClinicalNoteTruncation() {
  const notes = document.querySelectorAll('.clinical-note-text');
  if (notes.length === 0) return;

  // Batch: collect all notes that need measurement
  const measureContainer = document.createElement('div');
  measureContainer.style.cssText = 'position:absolute;visibility:hidden;pointer-events:none;top:-9999px;left:-9999px;';
  const clones = [];
  const noteData = [];

  notes.forEach(textEl => {
    const toggleBtn = textEl.nextElementSibling;
    if (!toggleBtn || !toggleBtn.classList.contains('clinical-note-toggle')) return;

    if (!textEl.textContent.trim()) {
      toggleBtn.classList.remove('visible');
      return;
    }

    textEl.classList.remove('expanded');
    toggleBtn.textContent = 'more';

    const computedStyle = window.getComputedStyle(textEl);
    const clone = textEl.cloneNode(true);
    clone.style.cssText = `
      display:block;
      -webkit-line-clamp:unset;
      -webkit-box-orient:unset;
      overflow:visible;
      max-height:none;
      width:${textEl.offsetWidth}px;
      white-space:pre-wrap;
      font-size:${computedStyle.fontSize};
      line-height:${computedStyle.lineHeight};
      font-family:${computedStyle.fontFamily};
    `;
    measureContainer.appendChild(clone);
    clones.push(clone);
    noteData.push({ textEl, toggleBtn });
  });

  if (clones.length === 0) return;

  // Single DOM insert triggers one reflow when heights are read
  document.body.appendChild(measureContainer);

  // Read all heights in one batch
  clones.forEach((clone, i) => {
    const fullHeight = clone.offsetHeight;
    const clampedHeight = noteData[i].textEl.clientHeight;
    if (fullHeight > clampedHeight + 2) {
      noteData[i].toggleBtn.classList.add('visible');
    } else {
      noteData[i].toggleBtn.classList.remove('visible');
    }
  });

  document.body.removeChild(measureContainer);
}

// Floating tooltip for truncated .cell-truncate elements
let _cellTooltip = null;

function _getCellTooltip() {
  if (!_cellTooltip) {
    _cellTooltip = document.createElement('div');
    _cellTooltip.className = 'cell-tooltip';
    _cellTooltip.style.display = 'none';
    document.body.appendChild(_cellTooltip);
  }
  return _cellTooltip;
}

function _showCellTooltip(e) {
  const el = e.currentTarget;
  const text = el.getAttribute('data-full-text');
  if (!text) return;
  const tip = _getCellTooltip();
  tip.textContent = text;
  tip.style.display = 'block';
  const rect = el.getBoundingClientRect();
  tip.style.left = rect.left + 'px';
  tip.style.top = (rect.bottom + 4) + 'px';
}

function _hideCellTooltip() {
  const tip = _getCellTooltip();
  tip.style.display = 'none';
}

function initCellTruncationTooltips() {
  document.querySelectorAll('.cell-truncate').forEach(el => {
    // Remove old listeners to avoid duplicates
    el.removeEventListener('mouseenter', _showCellTooltip);
    el.removeEventListener('mouseleave', _hideCellTooltip);

    if (el.scrollHeight > el.clientHeight + 1) {
      el.classList.add('is-truncated');
      // Store full text and remove native title to avoid double tooltip
      if (!el.getAttribute('data-full-text')) {
        el.setAttribute('data-full-text', el.getAttribute('title') || el.textContent.trim());
      }
      el.removeAttribute('title');
      el.addEventListener('mouseenter', _showCellTooltip);
      el.addEventListener('mouseleave', _hideCellTooltip);
    } else {
      el.classList.remove('is-truncated');
      el.removeAttribute('title');
    }
  });
}

// Initialize on page load
document.addEventListener('DOMContentLoaded', function() {
  initFilterDropdowns();
  initSortableHeaders();
  initClinicalNoteTruncation();
  initAutoSearch();
  initAvatarSkeletons();
  requestAnimationFrame(() => initCellTruncationTooltips());
  // Drive the initial table load (replaces the old hx-trigger="load") so we
  // replay any persisted filter/sort/page state for this staff member.
  loadInitialTable();
});

// Column Picker Functions
function toggleColumnPicker() {
  const picker = document.getElementById('column-picker');
  if (!picker) return;
  if (picker.style.display === 'none' || picker.style.display === '') {
    loadColumnPreferences();
    picker.style.display = 'block';
  } else {
    picker.style.display = 'none';
  }
}

function loadColumnPreferences() {
  const container = document.getElementById('column-picker-options');
  fetch('/plugin-io/api/patient_panel/app/preferences')
    .then(function(response) {
      if (!response.ok) throw new Error('preferences load failed: ' + response.status);
      return response.json();
    })
    .then(function(columns) {
      if (!container) return;
      container.innerHTML = '';
      columns.forEach(function(col) {
        const disabled = col.key === 'patient' ? ' disabled' : '';
        const checked = col.visible ? ' checked' : '';
        const div = document.createElement('div');
        div.className = 'column-picker-option';
        // Build via DOM APIs (not string concat) so a column key/label
        // containing quotes, spaces or angle brackets can't break the
        // attribute or inject markup, and the label-for linkage stays valid.
        const input = document.createElement('input');
        input.type = 'checkbox';
        input.id = 'col-pref-' + col.key;
        input.value = col.key;
        input.checked = !!col.visible;
        if (col.key === 'patient') input.disabled = true;
        const label = document.createElement('label');
        label.htmlFor = 'col-pref-' + col.key;
        label.textContent = col.label || col.key;
        div.appendChild(input);
        div.appendChild(label);
        container.appendChild(div);
      });
    })
    .catch(function() {
      if (container) {
        container.textContent = 'Could not load columns. Please close and reopen this menu.';
      }
    });
}

// Read all active filter/sort/search/page/page-size state from the DOM and
// return a URLSearchParams capturing it. Used after column-preference save/
// reset so the table reload doesn't blow away the user's current view.
function buildCurrentStateParams() {
  const params = new URLSearchParams();
  params.set('no_auto_filter', '1');

  const filters = document.querySelector('.filters');
  if (filters) {
    if (filters.dataset.sortBy) params.set('sort_by', filters.dataset.sortBy);
    if (filters.dataset.sortDir) params.set('sort_dir', filters.dataset.sortDir);
    if (filters.dataset.pageSize) params.set('page_size', filters.dataset.pageSize);
    if (filters.dataset.flaggedOnly === '1') params.set('flagged_only', '1');
  }

  const search = document.getElementById('patient-search-input');
  if (search && search.value && search.value.trim()) {
    params.set('patient_search', search.value.trim());
  }

  const dropdownMap = [
    ['staff-dropdown', 'staff_ids'],
    ['insurance-dropdown', 'insurances'],
    ['facility-dropdown', 'facility_ids'],
    ['protocol-dropdown', 'protocols'],
  ];
  dropdownMap.forEach(function (pair) {
    const el = document.getElementById(pair[0]);
    if (el && el.dataset.values && el.dataset.values.trim()) {
      params.set(pair[1], el.dataset.values.trim());
    }
  });

  // Metadata-column filters (metadata_<key>=v1,v2) — same shape applyFilters sends.
  document.querySelectorAll('.metadata-filter-dropdown').forEach(function (dd) {
    const key = dd.getAttribute('data-metadata-key');
    const values = dd.getAttribute('data-values') || '';
    if (key && values.trim()) {
      params.set('metadata_' + key, values.trim());
    }
  });

  const activePage = document.querySelector('.pagination-number.active');
  if (activePage && activePage.textContent.trim()) {
    params.set('page', activePage.textContent.trim());
  }

  return params;
}

// ── Filter/view persistence across full page reloads ──────────────────────
// Filter/sort/search/page state lives only in the rendered table DOM, so a
// browser reload would reset it. Persist the full current view (the same
// params applyFilters builds) to localStorage after every table render and
// replay it on initial load. Scoped per logged-in staff so a shared
// workstation never shows one user's filters to another.
function _filtersStorageKey() {
  const staffId = (document.body && document.body.getAttribute('data-staff-id')) || 'anon';
  return 'patient_panel:filters:' + staffId;
}

function persistTableState() {
  try {
    localStorage.setItem(_filtersStorageKey(), buildCurrentStateParams().toString());
  } catch (e) {
    // localStorage may be unavailable (private mode / disabled) — best-effort.
  }
}

function loadInitialTable() {
  let saved = '';
  try {
    saved = localStorage.getItem(_filtersStorageKey()) || '';
  } catch (e) {
    saved = '';
  }
  const base = '/plugin-io/api/patient_panel/app/table';
  const url = saved ? base + '?' + saved : base;
  htmx.ajax('GET', url, { target: '#table', swap: 'innerHTML' });
}

function reloadTablePreservingState() {
  const params = buildCurrentStateParams();
  htmx.ajax('GET', '/plugin-io/api/patient_panel/app/table?' + params.toString(), {
    target: '#table',
    swap: 'innerHTML'
  });
}

function saveColumnPreferences() {
  const checkboxes = document.querySelectorAll('#column-picker-options input[type="checkbox"]');
  const prefs = {};
  checkboxes.forEach(function(cb) {
    if (!cb.disabled) {
      prefs[cb.value] = cb.checked;
    }
  });

  const formData = new FormData();
  formData.append('columns', JSON.stringify(prefs));

  fetch('/plugin-io/api/patient_panel/app/preferences', {
    method: 'POST',
    body: formData,
  }).then(function(response) {
    if (!response.ok) throw new Error('save failed: ' + response.status);
    document.getElementById('column-picker').style.display = 'none';
    reloadTablePreservingState();
  }).catch(function() {
    // Keep the picker open so the user can retry; do not pretend it saved.
    window.alert('Could not save column preferences. Please try again.');
  });
}

function resetColumnPreferences() {
  fetch('/plugin-io/api/patient_panel/app/preferences/reset', {
    method: 'POST',
  }).then(function(response) {
    if (!response.ok) throw new Error('reset failed: ' + response.status);
    document.getElementById('column-picker').style.display = 'none';
    reloadTablePreservingState();
  }).catch(function() {
    window.alert('Could not reset column preferences. Please try again.');
  });
}

// Close column picker when clicking outside
document.addEventListener('click', function(e) {
  if (!e.target.closest('.column-settings-container')) {
    const picker = document.getElementById('column-picker');
    if (picker) picker.style.display = 'none';
  }
});

// Re-check truncation on window resize (debounced)
let resizeTimeout;
window.addEventListener('resize', function() {
  clearTimeout(resizeTimeout);
  resizeTimeout = setTimeout(function() {
    initClinicalNoteTruncation();
    initCellTruncationTooltips();
  }, 300);
});