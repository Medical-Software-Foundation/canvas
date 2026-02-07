/**
 * Observation Visualizer JavaScript
 *
 * Handles data fetching, table rendering, chart rendering, and filter management
 * for the observation visualizer UI with backend pagination.
 */

// State
let observations = [];
let chart1 = null;
let chart2 = null;
let expandedRows = new Set();
let currentFilters = {
    names: [],
    categories: []
};
let paginationData = {
    current_page: 1,
    total_pages: 1,
    total_count: 0,
    page_size: 25,
    has_previous: false,
    has_next: false
};
// Sorting state
let currentSort = {
    column: 'date',
    order: 'desc'
};
// Grouping state
let isUngrouped = false;
// Available filter options from backend
let availableNames = [];
let availableCategories = [];
// Chart Review state (stores all observations for summary)
let chartReviewData = {
    observations: [],
    totalCount: 0
};

// DOM Elements
const loadingOverlay = document.getElementById('loadingOverlay');
const tableView = document.getElementById('tableView');
const graphView = document.getElementById('graphView');
const tableViewBtn = document.getElementById('tableViewBtn');
const graphViewBtn = document.getElementById('graphViewBtn');
const tableBody = document.getElementById('tableBody');
const noDataMessage = document.getElementById('noDataMessage');
const noGraphDataMessage = document.getElementById('noGraphDataMessage');
const nameFilter = document.getElementById('nameFilter');
const nameOptions = document.getElementById('name-options');
const categoryFilter = document.getElementById('categoryFilter');
const categoryOptions = document.getElementById('category-options');
const startDateInput = document.getElementById('startDate');
const endDateInput = document.getElementById('endDate');
const applyFiltersBtn = document.getElementById('applyFiltersBtn');
const clearFiltersBtn = document.getElementById('clearFiltersBtn');
const metricSelect1 = document.getElementById('metricSelect1');
const metricSelect2 = document.getElementById('metricSelect2');
const addGraphBtn = document.getElementById('addGraphBtn');
const removeGraphBtn = document.getElementById('removeGraphBtn');
const graph2Ctrl = document.getElementById('graph2Ctrl');
const chart2Wrapper = document.getElementById('chart2Wrapper');
const paginationInfo = document.getElementById('paginationInfo');
const pageNumbers = document.getElementById('pageNumbers');
const prevButton = document.getElementById('prevButton');
const nextButton = document.getElementById('nextButton');
const pageSizeSelect = document.getElementById('pageSizeSelect');
const ungroupedCheckbox = document.getElementById('ungroupedCheckbox');

// Modal elements
const chartReviewModal = document.getElementById('chartReviewModal');
const closeModalBtn = document.getElementById('closeModalBtn');
const cancelModalBtn = document.getElementById('cancelModalBtn');
const createChartReviewBtn = document.getElementById('createChartReviewBtn');
const summaryPreview = document.getElementById('summaryPreview');
const summaryComment = document.getElementById('summaryComment');
const successMessage = document.getElementById('successMessage');
const errorMessage = document.getElementById('errorMessage');
const addToNoteBtn = document.getElementById('addToNoteBtn');

/**
 * Fetch observations from the API with pagination
 */
async function fetchObservations(page = 1) {
    showLoading(true);

    const params = new URLSearchParams();
    if (PATIENT_ID) params.append('patient_id', PATIENT_ID);

    // Add filter parameters (use || delimiter since names/categories may contain commas)
    if (currentFilters.names.length > 0) {
        params.append('name', currentFilters.names.join('||'));
    }
    if (currentFilters.categories.length > 0) {
        params.append('category', currentFilters.categories.join('||'));
    }
    if (startDateInput.value) {
        params.append('effective_datetime_start', startDateInput.value + 'T00:00:00Z');
    }
    if (endDateInput.value) {
        params.append('effective_datetime_end', endDateInput.value + 'T23:59:59Z');
    }

    // Sorting parameters
    params.append('sort_by', currentSort.column);
    params.append('sort_order', currentSort.order);

    // Grouping parameter
    if (isUngrouped) {
        params.append('ungrouped', 'true');
    }

    // Pagination parameters
    params.append('page', page);
    params.append('page_size', pageSizeSelect.value);

    try {
        const response = await fetch(
            `/plugin-io/api/custom_observation_management/visualizer/observations?${params.toString()}`
        );

        if (!response.ok) {
            throw new Error(`HTTP error! status: ${response.status}`);
        }

        const data = await response.json();
        observations = data.observations || [];
        paginationData = data.pagination || {
            current_page: 1,
            total_pages: 1,
            total_count: 0,
            page_size: 25,
            has_previous: false,
            has_next: false
        };

        return data;
    } catch (error) {
        console.error('Error fetching observations:', error);
        observations = [];
        return { observations: [], pagination: paginationData };
    } finally {
        showLoading(false);
    }
}

/**
 * Fetch available observation filter options (names and categories) from the API
 */
async function fetchObservationFilters() {
    const params = new URLSearchParams();
    if (PATIENT_ID) params.append('patient_id', PATIENT_ID);

    try {
        const response = await fetch(
            `/plugin-io/api/custom_observation_management/visualizer/observation-filters?${params.toString()}`
        );
        if (response.ok) {
            const data = await response.json();
            availableNames = data.names || [];
            availableCategories = data.categories || [];
        }
    } catch (error) {
        console.error('Error fetching observation filters:', error);
        availableNames = [];
        availableCategories = [];
    }
}

/**
 * Show/hide loading overlay
 */
function showLoading(show) {
    if (show) {
        loadingOverlay.classList.remove('hidden');
    } else {
        loadingOverlay.classList.add('hidden');
    }
}

/**
 * Check if an observation has members (child observations)
 */
function hasMembers(obs) {
    return obs.members && obs.members.length > 0;
}

/**
 * Close all open dropdowns
 */
function closeAllDropdowns() {
    const openDropdowns = document.querySelectorAll('.filter-dropdown.open');
    openDropdowns.forEach(dropdown => {
        dropdown.classList.remove('open');
        const options = dropdown.querySelector('.dropdown-options');
        if (options) {
            options.classList.remove('show');
        }
    });
}

/**
 * Populate a dropdown with options
 */
function populateDropdown(optionsContainer, dataArray, filterKey, displayName) {
    const searchHtml = `
        <div class="dropdown-search">
            <input type="text" id="${filterKey}-search" placeholder="Search ${displayName.toLowerCase()}..." class="search-input">
        </div>
    `;

    optionsContainer.innerHTML = searchHtml;

    // Add "All" option
    const allOption = document.createElement('div');
    allOption.className = 'dropdown-option';
    allOption.setAttribute('data-value', '');
    const isAllSelected = currentFilters[filterKey].length === 0;
    allOption.innerHTML = `
        <input type="checkbox" id="${filterKey}-all" ${isAllSelected ? 'checked' : ''}>
        <label for="${filterKey}-all">All ${displayName}</label>
    `;
    optionsContainer.appendChild(allOption);

    // Add data options
    dataArray.forEach(item => {
        const isSelected = currentFilters[filterKey].includes(item);
        const option = document.createElement('div');
        option.className = 'dropdown-option';
        option.setAttribute('data-value', item);
        const safeId = item.replace(/[^a-zA-Z0-9]/g, '-');
        option.innerHTML = `
            <input type="checkbox" id="${filterKey}-${safeId}" value="${escapeHtml(item)}" ${isSelected ? 'checked' : ''}>
            <label for="${filterKey}-${safeId}">${escapeHtml(item)}</label>
        `;
        optionsContainer.appendChild(option);
    });

    setupSearchFunctionality(filterKey, optionsContainer);
}

/**
 * Setup search functionality for a dropdown
 */
function setupSearchFunctionality(filterKey, optionsContainer) {
    const searchInput = document.getElementById(`${filterKey}-search`);
    if (searchInput) {
        searchInput.addEventListener('input', (e) => {
            const searchTerm = e.target.value.toLowerCase();
            const options = optionsContainer.querySelectorAll('.dropdown-option');

            options.forEach(option => {
                const label = option.querySelector('label');
                const text = label ? label.textContent.toLowerCase() : '';
                option.style.display = text.includes(searchTerm) ? 'flex' : 'none';
            });
        });

        searchInput.addEventListener('click', (e) => {
            e.stopPropagation();
        });
    }
}

/**
 * Setup dropdown event handlers
 */
function setupDropdown(dropdownEl, optionsEl, filterKey) {
    dropdownEl.addEventListener('click', (e) => {
        if (!e.target.closest('.dropdown-option') && !e.target.closest('.dropdown-search')) {
            closeAllDropdowns();
            dropdownEl.classList.toggle('open');
            optionsEl.classList.toggle('show');
        }
    });

    optionsEl.addEventListener('click', (e) => {
        e.stopPropagation();
        const option = e.target.closest('.dropdown-option');
        if (!option) return;

        const input = option.querySelector('input[type="checkbox"]');
        if (!input) return;

        const value = option.getAttribute('data-value');
        input.checked = !input.checked;

        if (value === '') {
            if (input.checked) {
                currentFilters[filterKey] = [];
                optionsEl.querySelectorAll(`input[type="checkbox"]:not([id="${filterKey}-all"])`).forEach(cb => cb.checked = false);
            }
        } else {
            if (input.checked) {
                const allCheckbox = document.getElementById(`${filterKey}-all`);
                if (allCheckbox) allCheckbox.checked = false;
                if (!currentFilters[filterKey].includes(value)) {
                    currentFilters[filterKey].push(value);
                }
            } else {
                currentFilters[filterKey] = currentFilters[filterKey].filter(item => item !== value);
                if (currentFilters[filterKey].length === 0) {
                    const allCheckbox = document.getElementById(`${filterKey}-all`);
                    if (allCheckbox) allCheckbox.checked = true;
                }
            }
        }

        updateDropdownDisplay(dropdownEl, filterKey);
    });
}

/**
 * Update dropdown display to show selected items
 */
function updateDropdownDisplay(dropdownEl, filterKey) {
    const selectedValue = dropdownEl.querySelector('.selected-value');
    const selectedItems = currentFilters[filterKey];

    const displayName = filterKey === 'names' ? 'Observations' : 'Categories';

    if (selectedItems.length === 0) {
        selectedValue.innerHTML = `<span class="placeholder-text">All ${displayName}</span>`;
    } else {
        const tags = selectedItems.map(item =>
            `<span class="selected-tag">${escapeHtml(item)}<span class="remove-tag" data-filter="${filterKey}" data-value="${escapeHtml(item)}">×</span></span>`
        ).join('');
        selectedValue.innerHTML = tags;

        selectedValue.querySelectorAll('.remove-tag').forEach(removeBtn => {
            removeBtn.addEventListener('click', (e) => {
                e.stopPropagation();
                const fKey = e.target.getAttribute('data-filter');
                const itemToRemove = e.target.getAttribute('data-value');
                currentFilters[fKey] = currentFilters[fKey].filter(item => item !== itemToRemove);

                const optionsEl = fKey === 'names' ? nameOptions : categoryOptions;
                const safeId = itemToRemove.replace(/[^a-zA-Z0-9]/g, '-');
                const checkbox = document.getElementById(`${fKey}-${safeId}`);
                if (checkbox) {
                    checkbox.checked = false;
                }

                if (currentFilters[fKey].length === 0) {
                    const allCheckbox = document.getElementById(`${fKey}-all`);
                    if (allCheckbox) allCheckbox.checked = true;
                }

                const dropdownElement = fKey === 'names' ? nameFilter : categoryFilter;
                updateDropdownDisplay(dropdownElement, fKey);
            });
        });
    }
}

/**
 * Build filter dropdowns from backend data
 */
function buildFilterDropdowns() {
    populateDropdown(nameOptions, availableNames, 'names', 'Observations');
    populateDropdown(categoryOptions, availableCategories, 'categories', 'Categories');

    setupDropdown(nameFilter, nameOptions, 'names');
    setupDropdown(categoryFilter, categoryOptions, 'categories');

    updateDropdownDisplay(nameFilter, 'names');
    updateDropdownDisplay(categoryFilter, 'categories');

    document.addEventListener('click', (e) => {
        if (!e.target.closest('.filter-dropdown')) {
            closeAllDropdowns();
        }
    });
}

/**
 * Apply filters - fetch from backend with new filters
 */
async function applyFilters() {
    // Update ungrouped state from checkbox
    isUngrouped = ungroupedCheckbox.checked;

    await fetchObservations(1);
    renderTable();
    updatePaginationControls();
    updateGraphSelectors();
    if (chart1) updateChart(chart1, metricSelect1.value);
    if (chart2) updateChart(chart2, metricSelect2.value);
}

/**
 * Clear all filters
 */
async function clearFilters() {
    currentFilters.names = [];
    currentFilters.categories = [];

    [nameOptions, categoryOptions].forEach((optionsEl, index) => {
        const filterKey = index === 0 ? 'names' : 'categories';
        optionsEl.querySelectorAll('input[type="checkbox"]').forEach(checkbox => {
            if (checkbox.id === `${filterKey}-all`) {
                checkbox.checked = true;
            } else {
                checkbox.checked = false;
            }
        });
    });

    updateDropdownDisplay(nameFilter, 'names');
    updateDropdownDisplay(categoryFilter, 'categories');

    startDateInput.value = '';
    endDateInput.value = '';

    // Reset ungrouped checkbox
    isUngrouped = false;
    ungroupedCheckbox.checked = false;

    await fetchObservations(1);
    renderTable();
    updatePaginationControls();
    updateGraphSelectors();
    if (chart1) updateChart(chart1, metricSelect1.value);
}

/**
 * Update pagination controls
 */
function updatePaginationControls() {
    prevButton.disabled = !paginationData.has_previous;
    nextButton.disabled = !paginationData.has_next;

    pageNumbers.textContent = `Page ${paginationData.current_page} of ${paginationData.total_pages}`;

    if (paginationData.total_count === 0) {
        paginationInfo.textContent = 'No observations found';
    } else {
        const start = (paginationData.current_page - 1) * paginationData.page_size + 1;
        const end = Math.min(start + observations.length - 1, paginationData.total_count);
        paginationInfo.textContent = `Showing ${start}-${end} of ${paginationData.total_count} observations`;
    }
}

/**
 * Go to a specific page
 */
async function goToPage(page) {
    if (page < 1 || page > paginationData.total_pages) return;

    await fetchObservations(page);
    renderTable();
    updatePaginationControls();
}

/**
 * Escape HTML to prevent XSS
 */
function escapeHtml(text) {
    if (text === null || text === undefined) return '';
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

/**
 * Format date for display
 * Accepts Date object, ISO string, or null
 */
function formatDate(dateInput) {
    if (!dateInput) return '-';
    const date = dateInput instanceof Date ? dateInput : new Date(dateInput);
    if (isNaN(date.getTime())) return '-';
    return date.toLocaleDateString('en-US', {
        year: 'numeric',
        month: 'short',
        day: 'numeric',
        hour: '2-digit',
        minute: '2-digit'
    });
}

/**
 * Get category badge HTML
 */
function getCategoryBadge(category) {
    if (!category) return '-';
    const categoryClass = category.toLowerCase().replace(/[^a-z-]/g, '-');
    return `<span class="category-badge ${categoryClass}">${escapeHtml(category)}</span>`;
}

/**
 * Get sort indicator for column header
 */
function getSortIndicator(column) {
    if (currentSort.column !== column) {
        return '<span class="sort-indicator">⇅</span>';
    }
    return currentSort.order === 'asc'
        ? '<span class="sort-indicator active">▲</span>'
        : '<span class="sort-indicator active">▼</span>';
}

/**
 * Handle column sort click
 */
async function handleSort(column) {
    if (currentSort.column === column) {
        // Toggle order if same column
        currentSort.order = currentSort.order === 'asc' ? 'desc' : 'asc';
    } else {
        // New column, default to descending for date, ascending for others
        currentSort.column = column;
        currentSort.order = column === 'date' ? 'desc' : 'asc';
    }

    // Fetch with new sort, reset to page 1
    await fetchObservations(1);
    renderTable();
    updatePaginationControls();
}

// Expose handleSort to global scope for onclick handlers
window.handleSort = handleSort;

/**
 * Render the table header with sortable columns
 */
function renderTableHeader() {
    const thead = document.querySelector('#observationsTable thead tr');
    thead.innerHTML = `
        <th class="sortable" onclick="handleSort('date')">Date ${getSortIndicator('date')}</th>
        <th class="sortable" onclick="handleSort('name')">Name ${getSortIndicator('name')}</th>
        <th class="sortable" onclick="handleSort('value')">Value ${getSortIndicator('value')}</th>
        <th class="sortable" onclick="handleSort('units')">Units ${getSortIndicator('units')}</th>
        <th class="sortable" onclick="handleSort('category')">Category ${getSortIndicator('category')}</th>
    `;
}

/**
 * Render the observations table
 * Observations from the API are already grouped - members are nested under parent's "members" field
 */
function renderTable() {
    // Update header with sort indicators
    renderTableHeader();
    if (observations.length === 0) {
        tableBody.innerHTML = '';
        noDataMessage.style.display = 'flex';
        document.querySelector('.table-wrapper').style.display = 'none';
        return;
    }

    noDataMessage.style.display = 'none';
    document.querySelector('.table-wrapper').style.display = 'block';

    let html = '';
    observations.forEach(obs => {
        const hasComponents = obs.components && obs.components.length > 0;
        const obsHasMembers = hasMembers(obs);
        const isExpandable = hasComponents || obsHasMembers;
        const isExpanded = expandedRows.has(obs.id);
        const expandIcon = isExpandable ? (isExpanded ? '&#9660;' : '&#9654;') : '';
        const rowClass = isExpandable ? 'expandable' : '';

        html += `
            <tr class="${rowClass}" data-id="${obs.id}" ${isExpandable ? 'onclick="toggleRow(this)"' : ''}>
                <td>${isExpandable ? `<span class="expand-icon">${expandIcon}</span>` : ''}${formatDate(getObservationDate(obs))}</td>
                <td>${escapeHtml(obs.name)}</td>
                <td>${escapeHtml(obs.value) || '-'}</td>
                <td>${escapeHtml(obs.units) || '-'}</td>
                <td>${getCategoryBadge(obs.category)}</td>
            </tr>
        `;

        if (isExpanded) {
            // Show components of the parent observation
            if (hasComponents) {
                obs.components.forEach(comp => {
                    html += `
                        <tr class="component-row">
                            <td></td>
                            <td>${escapeHtml(comp.name)}</td>
                            <td>${escapeHtml(comp.value) || '-'}</td>
                            <td>${escapeHtml(comp.unit) || '-'}</td>
                            <td></td>
                        </tr>
                    `;
                });
            }

            // Show member observations (already nested in the API response)
            if (obsHasMembers) {
                obs.members.forEach(member => {
                    html += `
                        <tr class="member-row">
                            <td>${formatDate(getObservationDate(member))}</td>
                            <td>${escapeHtml(member.name)}</td>
                            <td>${escapeHtml(member.value) || '-'}</td>
                            <td>${escapeHtml(member.units) || '-'}</td>
                            <td>${getCategoryBadge(member.category)}</td>
                        </tr>
                    `;

                    // Show components of member observations
                    if (member.components && member.components.length > 0) {
                        member.components.forEach(comp => {
                            html += `
                                <tr class="component-row nested">
                                    <td></td>
                                    <td>${escapeHtml(comp.name)}</td>
                                    <td>${escapeHtml(comp.value) || '-'}</td>
                                    <td>${escapeHtml(comp.unit) || '-'}</td>
                                    <td></td>
                                </tr>
                            `;
                        });
                    }
                });
            }
        }
    });

    tableBody.innerHTML = html;
}

/**
 * Toggle expansion of a row with components or members
 */
function toggleRow(row) {
    const id = row.dataset.id;
    if (expandedRows.has(id)) {
        expandedRows.delete(id);
    } else {
        expandedRows.add(id);
    }
    renderTable();
}

window.toggleRow = toggleRow;

/**
 * Switch between table and graph views
 */
function switchView(view) {
    if (view === 'table') {
        tableView.style.display = 'block';
        graphView.style.display = 'none';
        tableViewBtn.classList.add('btn-active');
        graphViewBtn.classList.remove('btn-active');
    } else {
        tableView.style.display = 'none';
        graphView.style.display = 'block';
        tableViewBtn.classList.remove('btn-active');
        graphViewBtn.classList.add('btn-active');
        initializeGraph();
    }
}

/**
 * Check if a value can be cleanly converted to a number (int or float)
 * Returns the numeric value if valid, or null if not
 */
function parseNumericValue(value) {
    if (value === null || value === undefined || value === '') {
        return null;
    }

    // Convert to string and trim whitespace
    const strValue = String(value).trim();

    // Check if it's a valid number format (allows integers, decimals, negative numbers, scientific notation)
    // This is stricter than parseFloat which would parse "120/80" as 120
    if (!/^-?\d+\.?\d*$/.test(strValue) && !/^-?\d*\.?\d+$/.test(strValue) && !/^-?\d+\.?\d*e[+-]?\d+$/i.test(strValue)) {
        return null;
    }

    const numValue = parseFloat(strValue);
    return isNaN(numValue) || !isFinite(numValue) ? null : numValue;
}

/**
 * Get the date for an observation, using fallbacks
 * Priority: effective_datetime > note.datetime_of_service
 */
function getObservationDate(obs) {
    if (obs.effective_datetime) {
        return new Date(obs.effective_datetime);
    }
    if (obs.note && obs.note.datetime_of_service) {
        return new Date(obs.note.datetime_of_service);
    }
    return null;
}

/**
 * Get numeric observations suitable for graphing
 * Includes parent observations, their components, and member observations
 * Only includes values that can be cleanly converted to int/float
 */
function getNumericObservations() {
    const metrics = {};

    function addObservationMetrics(obs, parentName = null) {
        const numValue = parseNumericValue(obs.value);
        const obsDate = getObservationDate(obs);
        if (numValue !== null && obsDate) {
            const metricName = parentName ? `${parentName} - ${obs.name}` : obs.name;
            if (!metrics[metricName]) {
                metrics[metricName] = [];
            }
            metrics[metricName].push({
                date: obsDate,
                value: numValue,
                units: obs.units
            });
        }

        // Add component metrics
        if (obs.components && obs.components.length > 0) {
            obs.components.forEach(comp => {
                const compValue = parseNumericValue(comp.value);
                if (compValue !== null && obsDate) {
                    const compMetricName = parentName
                        ? `${parentName} - ${obs.name} - ${comp.name}`
                        : `${obs.name} - ${comp.name}`;
                    if (!metrics[compMetricName]) {
                        metrics[compMetricName] = [];
                    }
                    metrics[compMetricName].push({
                        date: obsDate,
                        value: compValue,
                        units: comp.unit
                    });
                }
            });
        }
    }

    observations.forEach(obs => {
        // Add parent observation metrics
        addObservationMetrics(obs);

        // Add member observation metrics
        if (obs.members && obs.members.length > 0) {
            obs.members.forEach(member => {
                addObservationMetrics(member, obs.name);
            });
        }
    });

    Object.keys(metrics).forEach(key => {
        metrics[key].sort((a, b) => a.date - b.date);
    });

    return metrics;
}

/**
 * Update the metric selectors
 */
function updateGraphSelectors() {
    const metrics = getNumericObservations();
    const metricNames = Object.keys(metrics).sort();

    const options = metricNames.map(name =>
        `<option value="${escapeHtml(name)}">${escapeHtml(name)}</option>`
    ).join('');

    metricSelect1.innerHTML = options;
    metricSelect2.innerHTML = options;

    if (metricNames.length === 0) {
        noGraphDataMessage.style.display = 'flex';
        document.querySelector('.graph-controls').style.display = 'none';
        document.querySelector('.chart-container').style.display = 'none';
    } else {
        noGraphDataMessage.style.display = 'none';
        document.querySelector('.graph-controls').style.display = 'flex';
        document.querySelector('.chart-container').style.display = 'flex';
    }
}

/**
 * Create a Chart.js chart
 */
function createChart(ctx, color = 'rgba(0, 140, 255, 1)') {
    return new Chart(ctx, {
        type: 'line',
        data: {
            labels: [],
            datasets: [{
                label: '',
                data: [],
                tension: 0.3,
                pointRadius: 6,
                pointHoverRadius: 8,
                borderWidth: 3,
                borderColor: color,
                backgroundColor: color.replace('1)', '0.1)'),
                fill: true,
                spanGaps: true
            }]
        },
        options: {
            maintainAspectRatio: false,
            animation: {
                duration: 800,
                easing: 'easeOutQuad'
            },
            plugins: {
                tooltip: {
                    mode: 'index',
                    intersect: false
                },
                legend: {
                    display: true,
                    position: 'top'
                }
            },
            scales: {
                x: {
                    title: {
                        display: true,
                        text: 'Date'
                    }
                },
                y: {
                    title: {
                        display: true,
                        text: ''
                    },
                    beginAtZero: false
                }
            }
        }
    });
}

/**
 * Update chart with data for a metric
 */
function updateChart(chart, metricName) {
    const metrics = getNumericObservations();
    const data = metrics[metricName] || [];

    const labels = data.map(d =>
        d.date.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' })
    );
    const values = data.map(d => d.value);
    const units = data.length > 0 ? data[0].units : '';

    chart.data.labels = labels;
    chart.data.datasets[0].data = values;
    chart.data.datasets[0].label = metricName;
    chart.options.scales.y.title.text = units || metricName;
    chart.update();
}

/**
 * Initialize the graph view
 */
function initializeGraph() {
    updateGraphSelectors();

    const metrics = getNumericObservations();
    const metricNames = Object.keys(metrics);

    if (metricNames.length === 0) {
        return;
    }

    if (!chart1) {
        chart1 = createChart(document.getElementById('observationChart1').getContext('2d'));
    }

    if (metricSelect1.value) {
        updateChart(chart1, metricSelect1.value);
    } else if (metricNames.length > 0) {
        metricSelect1.value = metricNames[0];
        updateChart(chart1, metricNames[0]);
    }
}

/**
 * Filter the second metric selector to exclude the first metric
 */
function filterMetricSelect2() {
    const metrics = getNumericObservations();
    const metricNames = Object.keys(metrics).sort();
    const selected1 = metricSelect1.value;

    const options = metricNames
        .filter(name => name !== selected1)
        .map(name => `<option value="${escapeHtml(name)}">${escapeHtml(name)}</option>`)
        .join('');

    metricSelect2.innerHTML = options;
}

/**
 * Generate an HTML table summary of observations for the Chart Review Note
 * @param {Array} observationsList - The observations to include in the summary
 * @param {number} totalCount - The total count of observations
 */
function generateSummary(observationsList, totalCount) {
    const styles = `
        <style>
            .obs-summary-table {
                width: 100%;
                border-collapse: collapse;
                font-size: 12px;
                margin-top: 8px;
            }
            .obs-summary-table th,
            .obs-summary-table td {
                border: 1px solid #ddd;
                padding: 6px 8px;
                text-align: left;
            }
            .obs-summary-table th {
                background-color: #f5f5f5;
                font-weight: 600;
            }
            .obs-summary-table tr:nth-child(even) {
                background-color: #fafafa;
            }
            .obs-summary-member {
                background-color: #f0f7ff !important;
                font-size: 11px;
            }
            .obs-summary-component {
                background-color: #fff8e6 !important;
                font-size: 11px;
                font-style: italic;
            }
            .obs-summary-header {
                margin-bottom: 12px;
            }
            .obs-summary-filters {
                font-size: 11px;
                color: #666;
                margin-bottom: 8px;
            }
        </style>
    `;

    // Build filter summary
    let filterParts = [];
    if (currentFilters.names.length > 0) {
        filterParts.push(`Names: ${currentFilters.names.join(', ')}`);
    }
    if (currentFilters.categories.length > 0) {
        filterParts.push(`Categories: ${currentFilters.categories.join(', ')}`);
    }
    if (startDateInput.value || endDateInput.value) {
        const dateRange = [];
        if (startDateInput.value) dateRange.push(startDateInput.value);
        if (endDateInput.value) dateRange.push(endDateInput.value);
        filterParts.push(`Date Range: ${dateRange.join(' to ')}`);
    }
    if (isUngrouped) {
        filterParts.push('Ungrouped view');
    }

    const filterSummary = filterParts.length > 0
        ? `<div class="obs-summary-filters"><strong>Filters:</strong> ${filterParts.join(' | ')}</div>`
        : '';

    // Build table rows
    let rows = '';
    observationsList.forEach(obs => {
        const obsDate = getObservationDate(obs);
        const dateStr = obsDate ? formatDate(obsDate) : '-';

        // Main observation row
        rows += `
            <tr>
                <td>${escapeHtml(dateStr)}</td>
                <td>${escapeHtml(obs.name || '-')}</td>
                <td>${escapeHtml(obs.value || '-')}</td>
                <td>${escapeHtml(obs.units || '-')}</td>
                <td>${escapeHtml(obs.category || '-')}</td>
            </tr>
        `;

        // Component rows
        if (obs.components && obs.components.length > 0) {
            obs.components.forEach(comp => {
                rows += `
                    <tr class="obs-summary-component">
                        <td></td>
                        <td>&nbsp;&nbsp;&rarr; ${escapeHtml(comp.name || '-')}</td>
                        <td>${escapeHtml(comp.value || '-')}</td>
                        <td>${escapeHtml(comp.unit || '-')}</td>
                        <td></td>
                    </tr>
                `;
            });
        }

        // Member rows
        if (obs.members && obs.members.length > 0) {
            obs.members.forEach(member => {
                const memberDate = getObservationDate(member);
                const memberDateStr = memberDate ? formatDate(memberDate) : '-';
                rows += `
                    <tr class="obs-summary-member">
                        <td>${escapeHtml(memberDateStr)}</td>
                        <td>&nbsp;&nbsp;&rarr; ${escapeHtml(member.name || '-')}</td>
                        <td>${escapeHtml(member.value || '-')}</td>
                        <td>${escapeHtml(member.units || '-')}</td>
                        <td>${escapeHtml(member.category || '-')}</td>
                    </tr>
                `;

                // Member's components
                if (member.components && member.components.length > 0) {
                    member.components.forEach(comp => {
                        rows += `
                            <tr class="obs-summary-component">
                                <td></td>
                                <td>&nbsp;&nbsp;&nbsp;&nbsp;&rarr; ${escapeHtml(comp.name || '-')}</td>
                                <td>${escapeHtml(comp.value || '-')}</td>
                                <td>${escapeHtml(comp.unit || '-')}</td>
                                <td></td>
                            </tr>
                        `;
                    });
                }
            });
        }
    });

    const html = `
        ${styles}
        <div class="obs-summary-header">
            <strong>Observation Summary</strong> - ${new Date().toLocaleDateString()}
            <br/>
            <small>Total: ${totalCount} observations</small>
        </div>
        ${filterSummary}
        <table class="obs-summary-table">
            <thead>
                <tr>
                    <th>Date</th>
                    <th>Name</th>
                    <th>Value</th>
                    <th>Units</th>
                    <th>Category</th>
                </tr>
            </thead>
            <tbody>
                ${rows}
            </tbody>
        </table>
    `;

    return html;
}

/**
 * Fetch ALL observations (all pages) for the Chart Review summary
 */
async function fetchAllObservations() {
    const params = new URLSearchParams();
    if (PATIENT_ID) params.append('patient_id', PATIENT_ID);

    // Add current filter parameters
    if (currentFilters.names.length > 0) {
        params.append('name', currentFilters.names.join('||'));
    }
    if (currentFilters.categories.length > 0) {
        params.append('category', currentFilters.categories.join('||'));
    }
    if (startDateInput.value) {
        params.append('effective_datetime_start', startDateInput.value + 'T00:00:00Z');
    }
    if (endDateInput.value) {
        params.append('effective_datetime_end', endDateInput.value + 'T23:59:59Z');
    }

    // Use current sort settings
    params.append('sort_by', currentSort.column);
    params.append('sort_order', currentSort.order);

    // Grouping parameter
    if (isUngrouped) {
        params.append('ungrouped', 'true');
    }

    // Fetch all pages by using a large page size
    params.append('page', '1');
    params.append('page_size', '10000');

    try {
        const response = await fetch(
            `/plugin-io/api/custom_observation_management/visualizer/observations?${params.toString()}`
        );

        if (!response.ok) {
            throw new Error(`HTTP error! status: ${response.status}`);
        }

        const data = await response.json();
        return {
            observations: data.observations || [],
            totalCount: data.pagination?.total_count || data.observations?.length || 0
        };
    } catch (error) {
        console.error('Error fetching all observations:', error);
        return { observations: [], totalCount: 0 };
    }
}

/**
 * Open the Chart Review modal - fetches all observations first
 */
async function openChartReviewModal() {
    // Show modal with loading state
    chartReviewModal.style.display = 'flex';
    summaryPreview.innerHTML = '<div style="text-align: center; padding: 20px;">Loading all observations...</div>';
    createChartReviewBtn.disabled = true;

    // Clear previous comment
    summaryComment.value = '';

    // Hide messages
    successMessage.style.display = 'none';
    errorMessage.style.display = 'none';

    // Fetch ALL observations (not just current page)
    const { observations: allObservations, totalCount } = await fetchAllObservations();

    // Store for use in createChartReview
    chartReviewData.observations = allObservations;
    chartReviewData.totalCount = totalCount;

    // Generate and display the summary preview as HTML
    const summary = generateSummary(allObservations, totalCount);
    summaryPreview.innerHTML = summary;

    // Enable the create button
    createChartReviewBtn.disabled = false;
    createChartReviewBtn.textContent = 'Create Chart Review Note';
}

/**
 * Close the Chart Review modal
 */
function closeChartReviewModal() {
    chartReviewModal.style.display = 'none';
}

/**
 * Create the Chart Review note via API
 */
async function createChartReview() {
    // Use the stored chart review data (all observations)
    const summary = generateSummary(chartReviewData.observations, chartReviewData.totalCount);
    const comment = summaryComment.value.trim();

    // Hide any previous messages
    successMessage.style.display = 'none';
    errorMessage.style.display = 'none';

    // Disable button and show loading state
    createChartReviewBtn.disabled = true;
    createChartReviewBtn.textContent = 'Creating...';

    try {
        const response = await fetch('/plugin-io/api/custom_observation_management/visualizer/create-chart-review', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({
                patient_id: PATIENT_ID,
                staff_id: STAFF_ID,
                summary_text: summary,
                comment: comment,
            }),
        });

        const data = await response.json();

        if (response.ok) {
            successMessage.style.display = 'block';
            createChartReviewBtn.textContent = 'Created!';

            // Close modal after 2 seconds
            setTimeout(() => {
                closeChartReviewModal();
            }, 2000);
        } else {
            errorMessage.textContent = data.error || 'Failed to create Chart Review note';
            errorMessage.style.display = 'block';
            createChartReviewBtn.disabled = false;
            createChartReviewBtn.textContent = 'Create Chart Review Note';
        }
    } catch (err) {
        console.error('Error creating Chart Review:', err);
        errorMessage.textContent = 'Failed to create Chart Review note. Please try again.';
        errorMessage.style.display = 'block';
        createChartReviewBtn.disabled = false;
        createChartReviewBtn.textContent = 'Create Chart Review Note';
    }
}

/**
 * Initialize the application
 */
async function init() {
    // Fetch filter options and initial data in parallel
    await Promise.all([
        fetchObservationFilters(),
        fetchObservations(1)
    ]);

    // Build filter UI with backend data
    buildFilterDropdowns();

    // Render initial table
    renderTable();
    updatePaginationControls();

    // Setup event listeners
    tableViewBtn.addEventListener('click', () => switchView('table'));
    graphViewBtn.addEventListener('click', () => switchView('graph'));
    applyFiltersBtn.addEventListener('click', applyFilters);
    clearFiltersBtn.addEventListener('click', clearFilters);

    // Pagination event listeners
    prevButton.addEventListener('click', () => {
        if (paginationData.has_previous) {
            goToPage(paginationData.current_page - 1);
        }
    });

    nextButton.addEventListener('click', () => {
        if (paginationData.has_next) {
            goToPage(paginationData.current_page + 1);
        }
    });

    pageSizeSelect.addEventListener('change', async () => {
        await fetchObservations(1);
        renderTable();
        updatePaginationControls();
    });

    // Graph event listeners
    metricSelect1.addEventListener('change', () => {
        updateChart(chart1, metricSelect1.value);
        if (chart2) filterMetricSelect2();
    });

    addGraphBtn.addEventListener('click', () => {
        addGraphBtn.style.display = 'none';
        graph2Ctrl.style.display = 'flex';
        chart2Wrapper.style.display = 'flex';
        filterMetricSelect2();
        chart2 = createChart(
            document.getElementById('observationChart2').getContext('2d'),
            'rgba(255, 99, 132, 1)'
        );
        if (metricSelect2.value) {
            updateChart(chart2, metricSelect2.value);
        }
        metricSelect2.addEventListener('change', () => updateChart(chart2, metricSelect2.value));
    });

    removeGraphBtn.addEventListener('click', () => {
        graph2Ctrl.style.display = 'none';
        chart2Wrapper.style.display = 'none';
        if (chart2) {
            chart2.destroy();
            chart2 = null;
        }
        addGraphBtn.style.display = 'inline-block';
    });

    // Chart Review modal event listeners
    addToNoteBtn.addEventListener('click', openChartReviewModal);
    closeModalBtn.addEventListener('click', closeChartReviewModal);
    cancelModalBtn.addEventListener('click', closeChartReviewModal);
    createChartReviewBtn.addEventListener('click', createChartReview);

    // Close modal when clicking outside
    chartReviewModal.addEventListener('click', (e) => {
        if (e.target === chartReviewModal) {
            closeChartReviewModal();
        }
    });

    // Close modal with Escape key
    document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape' && chartReviewModal.style.display === 'flex') {
            closeChartReviewModal();
        }
    });
}

// Start the application
init();
