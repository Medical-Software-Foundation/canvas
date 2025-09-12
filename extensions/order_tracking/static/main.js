

let allProviders = [];
let allLocations = [];
let urgentOrders = [];
let routineOrders = [];
let loggedInStaffId = null;
let providerIdToNameMap = new Map();
let searchTimeout = null;
let savedFilters = [];

// Pagination state for each section
let urgentOrdersState = {
  page: 1,
  hasMore: true,
  loading: false,
  total: 0
};

let routineOrdersState = {
  page: 1,
  hasMore: true,
  loading: false,
  total: 0
};

// Load saved filters from backend on startup
async function loadSavedFilters() {
    try {
        const response = await fetch('/plugin-io/api/order_tracking/filters');
        if (!response.ok) {
            throw new Error('Failed to load saved filters');
        }
        const data = await response.json();
        savedFilters = data.filters || [];
        renderSavedFilters();
    } catch (error) {
        console.error('Error loading saved filters:', error);
        savedFilters = [];
        renderSavedFilters();
    }
}

// Save filter to backend
async function saveFilterToBackend(filterData) {
    try {
        const response = await fetch('/plugin-io/api/order_tracking/filter', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify(filterData)
        });

        if (!response.ok) {
            throw new Error('Failed to save filter');
        }

        const data = await response.json();
        return data.filter;
    } catch (error) {
        console.error('Error saving filter:', error);
        throw error;
    }
}

// Delete filter from backend
async function deleteFilterFromBackend(filterId) {
    try {
        const response = await fetch(`/plugin-io/api/order_tracking/filter/${filterId}`, {
            method: 'DELETE'
        });

        if (!response.ok) {
            throw new Error('Failed to delete filter');
        }

        return true;
    } catch (error) {
        console.error('Error deleting filter:', error);
        throw error;
    }
}

// Get current filter state
function getCurrentFilterState() {
    const providerDropdown = document.getElementById('provider-dropdown');
    const typeDropdown = document.getElementById('type-dropdown');
    const statusDropdown = document.getElementById('status-dropdown');
    const locationDropdown = document.getElementById('location-dropdown');
    const patientNameInput = document.getElementById('patient-name-filter');
    const dobInput = document.getElementById('patient-dob-filter');
    const sentToInput = document.getElementById('sent-to-filter');
    const dateFromInput = document.getElementById('date-from-filter');
    const dateToInput = document.getElementById('date-to-filter');

    return {
        providers: providerDropdown.getAttribute('data-values').split(',').filter(v => v),
        types: typeDropdown.getAttribute('data-values').split(',').filter(v => v),
        statuses: statusDropdown.getAttribute('data-values').split(',').filter(v => v),
        location: locationDropdown ? locationDropdown.getAttribute('data-value') || '' : '',
        patientName: patientNameInput.value.trim(),
        patientDob: dobInput.value,
        sentTo: sentToInput.value.trim(),
        dateFrom: dateFromInput.value,
        dateTo: dateToInput.value
    };
}

// Apply filter state
function applyFilterState(filterState) {
    // Apply provider filters
    const providerDropdown = document.getElementById('provider-dropdown');
    const providerCheckboxes = providerDropdown.querySelectorAll('input[type="checkbox"]');
    const providerAllCheckbox = providerDropdown.querySelector('#provider-all');

    // Reset all provider checkboxes
    providerCheckboxes.forEach(cb => cb.checked = false);

    if (!filterState.providers || filterState.providers.length === 0) {
        providerAllCheckbox.checked = true;
    } else {
        filterState.providers.forEach(provider => {
            const checkbox = Array.from(providerCheckboxes).find(cb => {
                const option = cb.closest('.dropdown-option');
                return option && option.getAttribute('data-value') === provider;
            });
            if (checkbox) checkbox.checked = true;
        });
    }
    updateSelectedDisplay(providerDropdown);

    // Apply type filters
    const typeDropdown = document.getElementById('type-dropdown');
    const typeCheckboxes = typeDropdown.querySelectorAll('input[type="checkbox"]');
    const typeAllCheckbox = typeDropdown.querySelector('#type-all');

    // Reset all type checkboxes
    typeCheckboxes.forEach(cb => cb.checked = false);

    if (!filterState.types || filterState.types.length === 0) {
        typeAllCheckbox.checked = true;
    } else {
        filterState.types.forEach(type => {
            const checkbox = Array.from(typeCheckboxes).find(cb => {
                const option = cb.closest('.dropdown-option');
                return option && option.getAttribute('data-value') === type;
            });
            if (checkbox) checkbox.checked = true;
        });
    }
    updateSelectedDisplay(typeDropdown);

    // Apply status filters
    const statusDropdown = document.getElementById('status-dropdown');
    const statusCheckboxes = statusDropdown.querySelectorAll('input[type="checkbox"]');
    const statusAllCheckbox = statusDropdown.querySelector('#status-all');

    // Reset all status checkboxes
    statusCheckboxes.forEach(cb => cb.checked = false);

    if (!filterState.statuses || filterState.statuses.length === 0) {
        statusAllCheckbox.checked = true;
    } else {
        filterState.statuses.forEach(status => {
            const checkbox = Array.from(statusCheckboxes).find(cb => {
                const option = cb.closest('.dropdown-option');
                return option && option.getAttribute('data-value') === status;
            });
            if (checkbox) checkbox.checked = true;
        });
    }
    updateSelectedDisplay(statusDropdown);

    const locationDropdown = document.getElementById('location-dropdown');
    if (locationDropdown && filterState.location !== undefined) {
        const locationOptions = locationDropdown.querySelectorAll('.dropdown-option');
        const selectedValue = locationDropdown.querySelector('.selected-value');

        // Remove selected class from all options
        locationOptions.forEach(opt => opt.classList.remove('selected'));

        // Find and select the matching option
        const matchingOption = Array.from(locationOptions).find(opt =>
            opt.getAttribute('data-value') === filterState.location
        );

        if (matchingOption) {
            matchingOption.classList.add('selected');
            const text = matchingOption.textContent;
            const value = matchingOption.getAttribute('data-value');

            if (value === '') {
                selectedValue.innerHTML = `<span class="placeholder-text">${text}</span>`;
            } else {
                selectedValue.innerHTML = `<span>${text}</span>`;
            }

            locationDropdown.setAttribute('data-value', value);
        }
    }

    // Apply text inputs
    document.getElementById('patient-name-filter').value = filterState.patientName || '';
    document.getElementById('patient-dob-filter').value = filterState.patientDob || '';
    document.getElementById('sent-to-filter').value = filterState.sentTo || '';
    document.getElementById('date-from-filter').value = filterState.dateFrom || '';
    document.getElementById('date-to-filter').value = filterState.dateTo || '';

    // Trigger filter change
    handleFilterChange();
}

// Check if current state has any active filters
function hasActiveFilters() {
    const state = getCurrentFilterState();
    return state.providers.length > 0 ||
        state.types.length > 0 ||
        state.statuses.length > 0 ||
        state.location ||
        state.patientName ||
        state.patientDob ||
        state.sentTo ||
        state.dateFrom ||
        state.dateTo;
}

// Render saved filters
function renderSavedFilters() {
    const container = document.getElementById('saved-filters-container');
    const saveBtn = document.getElementById('save-current-btn');

    // Update save button state
    saveBtn.disabled = !hasActiveFilters();

    if (savedFilters.length === 0) {
        container.innerHTML = '<span class="no-saved-filters">No saved filters yet</span>';
        return;
    }

    container.innerHTML = savedFilters.map(filter => `
      <div class="saved-filter-pill" data-filter-id="${filter.id}">
        <span class="filter-name" title="${filter.name}">${filter.name}</span>
        <span class="remove-filter" data-filter-id="${filter.id}" title="Remove filter">&times;</span>
      </div>
    `).join('');

    // Add event listeners
    container.querySelectorAll('.saved-filter-pill').forEach(pill => {
        const filterId = pill.getAttribute('data-filter-id');

        pill.addEventListener('click', (e) => {
            if (e.target.classList.contains('remove-filter')) {
                return; // Let the remove handler handle this
            }
            loadSavedFilter(filterId);
        });
    });

    container.querySelectorAll('.remove-filter').forEach(removeBtn => {
        removeBtn.addEventListener('click', (e) => {
            e.stopPropagation();
            const filterId = removeBtn.getAttribute('data-filter-id');
            removeSavedFilter(filterId);
        });
    });
}

// Initialize saved filters functionality
function initializeSavedFilters() {
    const saveBtn = document.getElementById('save-current-btn');
    const modal = document.getElementById('save-filter-modal');
    const nameInput = document.getElementById('filter-name-input');
    const cancelBtn = document.getElementById('cancel-save-btn');
    const confirmBtn = document.getElementById('confirm-save-btn');

    // Save current button
    saveBtn.addEventListener('click', () => {
        if (!hasActiveFilters()) return;

        modal.style.display = 'flex';
        nameInput.value = '';
        nameInput.focus();
    });

    // Cancel save
    cancelBtn.addEventListener('click', () => {
        modal.style.display = 'none';
    });

    // Confirm save
    confirmBtn.addEventListener('click', async () => {
        const name = nameInput.value.trim();
        if (!name) {
            nameInput.focus();
            return;
        }

        // Disable button to prevent double-clicks
        confirmBtn.disabled = true;
        confirmBtn.textContent = 'Saving...';

        try {
            await saveCurrentFilter(name);
            modal.style.display = 'none';
        } catch (error) {
            alert('Error saving filter. Please try again.');
        } finally {
            confirmBtn.disabled = false;
            confirmBtn.textContent = 'Save';
        }
    });

    // Enter key in name input
    nameInput.addEventListener('keypress', (e) => {
        if (e.key === 'Enter') {
            confirmBtn.click();
        }
    });

    // Close modal on backdrop click
    modal.addEventListener('click', (e) => {
        if (e.target === modal) {
            modal.style.display = 'none';
        }
    });

    // Load saved filters on startup
    loadSavedFilters();
}

// Save current filter state
async function saveCurrentFilter(name) {
    const filterState = getCurrentFilterState();
    const filterData = {
        id: `${new Date().getTime()}`,
        name: name,
        filters: filterState
    };

    try {
        const savedFilter = await saveFilterToBackend(filterData);

        // Add to local array
        savedFilters.push(savedFilter);
        renderSavedFilters();
    } catch (error) {
        throw error; // Re-throw to handle in the calling function
    }
}

// Load a saved filter
function loadSavedFilter(filterId) {
    const filter = savedFilters.find(f => f.id === filterId);
    if (!filter) return;

    applyFilterState(filter.filters);
    renderSavedFilters(); // Re-render to show active state
}

// Remove a saved filter
async function removeSavedFilter(filterId) {
    if (!confirm('Are you sure you want to delete this saved filter?')) {
        return;
    }

    try {
        await deleteFilterFromBackend(filterId);

        // Remove from local array
        savedFilters = savedFilters.filter(f => f.id !== filterId);
        renderSavedFilters();
    } catch (error) {
        alert('Error deleting filter. Please try again.');
    }
}

// Filter toggle functionality
function initializeFilterToggle() {
    const filterToggle = document.getElementById('filter-toggle');
    const filtersContainer = document.getElementById('filters-container');

    if (!filterToggle || !filtersContainer) {
        console.error('Filter toggle elements not found');
        return;
    }

    filterToggle.addEventListener('click', function(e) {
        // Prevent event bubbling
        e.stopPropagation();

        const isExpanded = filtersContainer.classList.contains('expanded');

        if (isExpanded) {
            filtersContainer.classList.remove('expanded');
            filterToggle.classList.remove('expanded');
        } else {
            filtersContainer.classList.add('expanded');
            filterToggle.classList.add('expanded');
        }
    });
}

// Function to count and update active filters
function updateFilterBadge() {
    let activeFilterCount = 0;

    // Check dropdown filters
    const providerDropdown = document.getElementById('provider-dropdown');
    const typeDropdown = document.getElementById('type-dropdown');
    const statusDropdown = document.getElementById('status-dropdown');
    const locationDropdown = document.getElementById('location-dropdown');

    const selectedProviders = providerDropdown.getAttribute('data-values').split(',').filter(v => v);
    const selectedTypes = typeDropdown.getAttribute('data-values').split(',').filter(v => v);
    const selectedStatuses = statusDropdown.getAttribute('data-values').split(',').filter(v => v);
    const selectedLocation = locationDropdown ? locationDropdown.getAttribute('data-value') : '';

    if (selectedProviders.length > 0) activeFilterCount++;
    if (selectedTypes.length > 0) activeFilterCount++;
    if (selectedStatuses.length > 0) activeFilterCount++;
    if (selectedLocation) activeFilterCount++;

    // Check text inputs
    const patientNameInput = document.getElementById('patient-name-filter');
    const sentToInput = document.getElementById('sent-to-filter');
    const dobInput = document.getElementById('patient-dob-filter');
    const dateFromInput = document.getElementById('date-from-filter');
    const dateToInput = document.getElementById('date-to-filter');

    if (patientNameInput.value.trim()) activeFilterCount++;
    if (sentToInput.value.trim()) activeFilterCount++;
    if (dobInput.value) activeFilterCount++;
    if (dateFromInput.value || dateToInput.value) activeFilterCount++;

    // Update badge
    const filterBadge = document.getElementById('filter-badge');

    if (activeFilterCount > 0) {
        filterBadge.textContent = activeFilterCount;
        filterBadge.classList.remove('hidden');
    } else {
        filterBadge.classList.add('hidden');
    }

    // Update save button state
    const saveBtn = document.getElementById('save-current-btn');
    if (saveBtn) {
        saveBtn.disabled = !hasActiveFilters();
    }
}

// Custom dropdown functionality
function initializeDropdowns() {
    const dropdowns = document.querySelectorAll('.filter-dropdown');

    dropdowns.forEach(dropdown => {
        const selectedValue = dropdown.querySelector('.selected-value');
        const options = dropdown.querySelector('.dropdown-options');

        // Toggle dropdown
        selectedValue.addEventListener('click', (e) => {
            e.stopPropagation();

            // Close other dropdowns
            dropdowns.forEach(otherDropdown => {
                if (otherDropdown !== dropdown) {
                    otherDropdown.classList.remove('open');
                    otherDropdown.querySelector('.dropdown-options').classList.remove('show');
                }
            });

            // Toggle current dropdown
            dropdown.classList.toggle('open');
            options.classList.toggle('show');
        });

        // Handle checkbox changes
        function setupOptionListeners() {
            const checkboxes = dropdown.querySelectorAll('input[type="checkbox"]');
            const allCheckbox = dropdown.querySelector('input[type="checkbox"][id$="-all"]');

            checkboxes.forEach(checkbox => {
                checkbox.addEventListener('change', (e) => {
                    e.stopPropagation();

                    if (checkbox === allCheckbox) {
                        // If "All" is checked, uncheck all others
                        if (checkbox.checked) {
                            checkboxes.forEach(cb => {
                                if (cb !== allCheckbox) cb.checked = false;
                            });
                        }
                    } else {
                        // If any specific option is checked, uncheck "All"
                        if (checkbox.checked && allCheckbox) {
                            allCheckbox.checked = false;
                        }

                        // If no specific options are checked, check "All"
                        const specificCheckboxes = Array.from(checkboxes).filter(cb => cb !== allCheckbox);
                        const anyChecked = specificCheckboxes.some(cb => cb.checked);
                        if (!anyChecked && allCheckbox) {
                            allCheckbox.checked = true;
                        }
                    }

                    updateSelectedDisplay(dropdown);
                    handleFilterChange();
                });
            });
        }

        setupOptionListeners();
        dropdown.setupOptionListeners = setupOptionListeners;
    });

    // Close dropdowns when clicking outside
    document.addEventListener('click', () => {
        dropdowns.forEach(dropdown => {
            dropdown.classList.remove('open');
            dropdown.querySelector('.dropdown-options').classList.remove('show');
        });
    });
}

function updateSelectedDisplay(dropdown) {
    const selectedValue = dropdown.querySelector('.selected-value');
    const checkboxes = dropdown.querySelectorAll('input[type="checkbox"]');
    const allCheckbox = dropdown.querySelector('input[type="checkbox"][id$="-all"]');

    // Get selected values (excluding "All")
    const selectedValues = [];
    const selectedLabels = [];

    checkboxes.forEach(checkbox => {
        if (checkbox.checked && checkbox !== allCheckbox) {
            const label = dropdown.querySelector(`label[for="${checkbox.id}"]`);
            if (label) {
                selectedValues.push(checkbox.closest('.dropdown-option').getAttribute('data-value'));
                selectedLabels.push(label.textContent);
            }
        }
    });

    // Update data-values attribute
    dropdown.setAttribute('data-values', selectedValues.join(','));

    // Update display
    selectedValue.innerHTML = '';

    if (selectedLabels.length === 0 || (allCheckbox && allCheckbox.checked)) {
        // Show placeholder
        let placeholder = 'All Options';
        if (dropdown.id === 'provider-dropdown') placeholder = 'All Providers';
        else if (dropdown.id === 'type-dropdown') placeholder = 'All Types';
        else if (dropdown.id === 'status-dropdown') placeholder = 'All Statuses';

        selectedValue.innerHTML = `<span class="placeholder-text">${placeholder}</span>`;
    } else {
        // Show selected tags
        selectedLabels.forEach((label, index) => {
            const tag = document.createElement('span');
            tag.className = 'selected-tag';
            tag.innerHTML = `
      ${label}
      <span class="remove-tag" data-value="${selectedValues[index]}">&times;</span>
    `;
            selectedValue.appendChild(tag);
        });

        // Add event listeners to remove tags
        selectedValue.querySelectorAll('.remove-tag').forEach(removeBtn => {
            removeBtn.addEventListener('click', (e) => {
                e.stopPropagation();
                const valueToRemove = removeBtn.getAttribute('data-value');
                const checkbox = dropdown.querySelector(`input[type="checkbox"][data-value="${valueToRemove}"]`) ||
                    dropdown.querySelector(`.dropdown-option[data-value="${valueToRemove}"] input[type="checkbox"]`);
                if (checkbox) {
                    checkbox.checked = false;
                    updateSelectedDisplay(dropdown);
                    handleFilterChange();
                }
            });
        });
    }
}

function initializePatientNameFilter() {
    const patientNameInput = document.getElementById('patient-name-filter');

    patientNameInput.addEventListener('input', (e) => {
        // Clear existing timeout
        if (searchTimeout) {
            clearTimeout(searchTimeout);
        }

        // Set new timeout to debounce the search
        searchTimeout = setTimeout(() => {
            handleFilterChange();
        }, 300); // Wait 300ms after user stops typing
    });

    // Also trigger search on Enter key
    patientNameInput.addEventListener('keypress', (e) => {
        if (e.key === 'Enter') {
            if (searchTimeout) {
                clearTimeout(searchTimeout);
            }
            handleFilterChange();
        }
    });
}

function initializeDobFilter() {
    const dobInput = document.getElementById('patient-dob-filter');

    dobInput.addEventListener('change', (e) => {
        handleFilterChange();
    });
}

function initializeSentToFilter() {
    const sentToInput = document.getElementById('sent-to-filter');

    sentToInput.addEventListener('input', (e) => {
        // Clear existing timeout
        if (searchTimeout) {
            clearTimeout(searchTimeout);
        }

        // Set new timeout to debounce the search
        searchTimeout = setTimeout(() => {
            handleFilterChange();
        }, 300); // Wait 300ms after user stops typing
    });

    // Also trigger search on Enter key
    sentToInput.addEventListener('keypress', (e) => {
        if (e.key === 'Enter') {
            if (searchTimeout) {
                clearTimeout(searchTimeout);
            }
            handleFilterChange();
        }
    });
}

function initializeDateRangeFilter() {
    const dateFromInput = document.getElementById('date-from-filter');
    const dateToInput = document.getElementById('date-to-filter');

    const today = new Date();
    const defaultDate = new Date(new Date().setDate(today.getDate() - 30));
    dateFromInput.defaultValue = defaultDate.toISOString().split('T')[0];

    dateFromInput.addEventListener('change', (e) => {
        handleFilterChange();
    });

    dateToInput.addEventListener('change', (e) => {
        handleFilterChange();
    });
}

function handleFilterChange() {
    // Clear active filter when manually changing filters
   renderSavedFilters();

    // Update filter badge
    updateFilterBadge();

    // Reset pagination state for both sections
    urgentOrdersState = { page: 1, hasMore: true, loading: false, total: 0 };
    routineOrdersState = { page: 1, hasMore: true, loading: false, total: 0 };

    // Clear existing orders
    urgentOrders = [];
    routineOrders = [];

    // Fetch initial orders for both sections
    fetchOrders('urgent');
    fetchOrders('routine');
}

async function fetchProviders() {
    try {
        const response = await fetch('/plugin-io/api/order_tracking/providers');
        const data = await response.json();

        loggedInStaffId = data.logged_in_staff_id;

        const providers = data.providers || [];

        // Create maps for providers
        const providerMap = new Map();

        providers.forEach(provider => {
            if (provider.preferred_name && provider.id) {
                providerMap.set(provider.id, provider.preferred_name);
                providerIdToNameMap.set(provider.id, provider.preferred_name);
            }
        });

        allProviders = Array.from(providerMap.values());
        populateProvidersDropdown();
    } catch (error) {
        console.error('Error fetching providers:', error);
    }
}

async function fetchLocations() {
    try {
        const response = await fetch('/plugin-io/api/order_tracking/locations');
        const data = await response.json();

        const locations = data.locations || [];
        allLocations = locations;
        populateLocationsDropdown();
    } catch (error) {
        console.error('Error fetching locations:', error);
        allLocations = [];
        populateLocationsDropdown();
    }
}

function populateProvidersDropdown() {
    const providerOptions = document.getElementById('provider-options');
    const providerDropdown = document.getElementById('provider-dropdown');

    // Get the logged-in staff member's name if they exist in providers
    const loggedInStaffName = loggedInStaffId ? providerIdToNameMap.get(loggedInStaffId) : null;

    let optionsHTML = `
  <div class="dropdown-option" data-value="">
    <input type="checkbox" id="provider-all" checked>
    <label for="provider-all">All Providers</label>
  </div>
`;

    allProviders.forEach((provider, index) => {
        const isSelected = loggedInStaffName && provider === loggedInStaffName;
        optionsHTML += `
    <div class="dropdown-option" data-value="${provider}">
      <input type="checkbox" id="provider-${index}" ${isSelected ? 'checked' : ''}>
      <label for="provider-${index}">${provider}</label>
    </div>
  `;
    });

    providerOptions.innerHTML = optionsHTML;

    // Update selected display and trigger filter if logged-in staff should be auto-selected
    if (loggedInStaffName && allProviders.includes(loggedInStaffName)) {
        const allCheckbox = providerDropdown.querySelector('#provider-all');
        if (allCheckbox) allCheckbox.checked = false;
    }
    updateSelectedDisplay(providerDropdown);

    // Re-setup event listeners for new options
    providerDropdown.setupOptionListeners();

    // Update filter badge after populating
    updateFilterBadge();
}

// New function to fetch orders by priority type
async function fetchOrders(priority = 'all') {
    const state = priority === 'urgent' ? urgentOrdersState : routineOrdersState;

    if (state.loading || !state.hasMore) {
        return;
    }

    state.loading = true;
    updateLoadMoreButton(priority, true);

    try {
        const currentFilters = getCurrentFilterParams();

        // Build query parameters
        const params = new URLSearchParams(currentFilters);
        params.append('page', state.page);
        params.append('page_size', 20);
        params.append('priority', priority);

        const url = `/plugin-io/api/order_tracking/orders?${params.toString()}`;
        const response = await fetch(url);
        const data = await response.json();

        // Process the orders
        const newOrders = processOrdersData(data);

        if (priority === 'urgent') {
            urgentOrders = [...urgentOrders, ...newOrders];
            urgentOrdersState.total = data.count?.urgent || 0;
        } else {
            routineOrders = [...routineOrders, ...newOrders];
            routineOrdersState.total = data.count?.routine || 0;
        }

        // Update pagination state
        state.page++;
        state.hasMore = data.pagination?.has_next || false;
        state.loading = false;

        // Update UI
        populateOrdersTable();
        updateLoadMoreButton(priority, false);

    } catch (error) {
        console.error('Error fetching orders:', error);
        state.loading = false;
        updateLoadMoreButton(priority, false);
    }
}

function getCurrentFilterParams() {
    const providerDropdown = document.getElementById('provider-dropdown');
    const typeDropdown = document.getElementById('type-dropdown');
    const statusDropdown = document.getElementById('status-dropdown');
    const locationDropdown = document.getElementById('location-dropdown');
    const patientNameInput = document.getElementById('patient-name-filter');
    const dobInput = document.getElementById('patient-dob-filter');
    const sentToInput = document.getElementById('sent-to-filter');
    const dateFromInput = document.getElementById('date-from-filter');
    const dateToInput = document.getElementById('date-to-filter');

    const selectedProviders = providerDropdown.getAttribute('data-values').split(',').filter(v => v);
    const selectedTypes = typeDropdown.getAttribute('data-values').split(',').filter(v => v);
    const selectedStatuses = statusDropdown.getAttribute('data-values').split(',').filter(v => v);
    const selectedLocation = locationDropdown ? locationDropdown.getAttribute('data-value') : '';

    const params = {};

    // Handle multiple provider IDs as comma-separated string
    if (selectedProviders && selectedProviders.length > 0) {
        const providerIds = selectedProviders.map(providerName => {
            return Array.from(providerIdToNameMap.entries())
                .find(([id, name]) => name === providerName)?.[0];
        }).filter(id => id);

        if (providerIds.length > 0) {
            params.provider_ids = providerIds.join(',');
        }
    }

    // Handle multiple order types as comma-separated string
    if (selectedTypes && selectedTypes.length > 0) {
        const validOrderTypes = selectedTypes.filter(type => type && type !== 'All Types');
        if (validOrderTypes.length > 0) {
            params.types = validOrderTypes.join(',');
        }
    }

    // Handle multiple statuses as comma-separated string
    if (selectedStatuses && selectedStatuses.length > 0) {
        const validStatuses = selectedStatuses.filter(status => status && status !== 'All Statuses');
        if (validStatuses.length > 0) {
            params.status = validStatuses.join(',');
        }
    }

    if (selectedLocation && selectedLocation.length > 0) {
        params.location = selectedLocation;
    }
    if (patientNameInput.value.trim()) {
        params.patient_name = patientNameInput.value.trim();
    }
    if (dobInput.value) {
        params.patient_dob = dobInput.value;
    }
    if (sentToInput.value.trim()) {
        params.sent_to = sentToInput.value.trim();
    }
    if (dateFromInput.value) {
        params.date_from = dateFromInput.value;
    }
    if (dateToInput.value) {
        params.date_to = dateToInput.value;
    }

    return params;
}

function processOrdersData(data) {
    return (data.orders || []).map(order => ({
        id: order.id,
        type: order.type,
        orderName: order.order,
        patientId: order.patient_id,
        patientName: order.patient_name,
        dob: order.dob,
        orderingProvider: order.ordering_provider?.preferred_name,
        orderingProviderId: order.ordering_provider?.id,
        sentTo: order.sent_to,
        orderedDate: formatDate(order.ordered_date),
        priority: order.priority,
        status: order.status,
        permalink: order.permalink,
        noteTitle: order.note.title,
        notePermalink: order.note.permalink
    }));
}

function formatDate(dateString) {
    if (!dateString) return '';
    try {
        return new Date(dateString).toLocaleDateString('en-US', {
            month: 'short',
            day: 'numeric',
            year: 'numeric'
        });
    } catch {
        return dateString;
    }
}

function populateOrdersTable() {
    const accordion = document.getElementById('orders-accordion');
    const infoBar = document.getElementById('info-bar');

    if (urgentOrders.length === 0 && routineOrders.length === 0) {
        accordion.innerHTML = '<div class="section-header">No orders found</div>';
        infoBar.textContent = 'No orders available';
        return;
    }

    let html = '';

    // Add table header
    html += `
      <div class="accordion-header-row">
        <div>Patient</div>
        <div>DOB</div>
        <div>Order</div>
        <div>Type</div>
        <div>Provider</div>
        <div>Sent To</div>
        <div>Status</div>
        <div>Date</div>
        <div></div>
      </div>
    `;

    // Urgent Orders Section
    if (urgentOrders.length > 0) {
        html += `
            <div class="order-section">
                <div class="section-header section-header-urgent">
                    <span>⚠ Urgent Orders (${urgentOrdersState.total})</span>
                </div>
        `;

        urgentOrders.forEach(order => {
            html += createOrderAccordionItem(order, true);
        });

        // Add Load More button for urgent orders if there are more
        if (urgentOrdersState.hasMore) {
            html += `
                <button class="load-more-btn" id="load-more-urgent" onclick="loadMoreOrders('urgent')">
                    <span class="load-more-text">Load More...</span>
                    <div class="load-more-spinner" style="display: none;"></div>
                </button>
            `;
        }

        html += '</div>';
    }

    // Routine Orders Section
    if (routineOrders.length > 0) {
        html += `
            <div class="order-section">
                <div class="section-header text-gray-700">
                    <span>⏱ Routine Orders (${routineOrdersState.total})</span>
                </div>
        `;

        routineOrders.forEach(order => {
            html += createOrderAccordionItem(order, false);
        });

        // Add Load More button for routine orders if there are more
        if (routineOrdersState.hasMore) {
            html += `
                <button class="load-more-btn" id="load-more-routine" onclick="loadMoreOrders('routine')">
                    <span class="load-more-text">Load More...</span>
                    <div class="load-more-spinner" style="display: none;"></div>
                </button>
            `;
        }

        html += '</div>';
    }

    if (urgentOrdersState.total + routineOrdersState.total === 0) {
        html = '<div class="section-header">No orders found</div>';
    }

    accordion.innerHTML = html;
    if (ENABLE_TASK_COMMENTS) {
        setupAccordionListeners();
    }


    // Update info bar
    const totalUrgent = urgentOrdersState.total;
    const totalRoutine = routineOrdersState.total;
    const loadedUrgent = urgentOrders.length;
    const loadedRoutine = routineOrders.length;

    infoBar.textContent = `Showing ${loadedUrgent + loadedRoutine} of ${totalUrgent + totalRoutine} orders (${loadedUrgent}/${totalUrgent} urgent, ${loadedRoutine}/${totalRoutine} routine)`;
}

function updateLoadMoreButton(priority, isLoading) {
    const buttonId = `load-more-${priority}`;
    const button = document.getElementById(buttonId);

    if (!button) return;

    const text = button.querySelector('.load-more-text');
    const spinner = button.querySelector('.load-more-spinner');

    if (isLoading) {
        button.disabled = true;
        text.textContent = 'Loading...';
        spinner.style.display = 'block';
    } else {
        button.disabled = false;
        text.textContent = priority === 'urgent' ? 'Load More...' : 'Load More...';
        spinner.style.display = 'none';
    }
}

function createOrderAccordionItem(order, isUrgent) {
    const itemClass = isUrgent ? 'bg-red-50' : '';
    const badgeClass = getBadgeClass(order.type);
    const statusBadgeClass = getStatusBadgeClass(order.status);
    const actions = order.actions ? `<button>${order.actions}</button>` : '';
    const orderId = `${order.id}`;
    const headerId = `header-${orderId}`;

    // Check if this is a Lab order
    const isLabOrder = order.type && order.type.toLowerCase() === 'lab';
    const headerClass = isLabOrder ? 'disabled' : '';
    const iconClass = isLabOrder ? 'hidden' : '';

    return `
  <div class="accordion-item ${itemClass}">
    <div class="accordion-header ${headerClass}" id="${headerId}" data-target="${orderId}" data-patient-id="${order.patientId}" data-order-type="${order.type}" data-order-id="${order.id}">
      <div class="column-value"><a href='/patient/${order.patientId}/#application=${PATIENT_CHART_APPLICATION}' target="_top" style="color: var(--primary); cursor: pointer;">${order.patientName || ''}</a></div>
      <div class="column-value">${order.dob || ''}</div>
      <div class="column-value"><a href='/patient/${order.patientId}/#application=${PATIENT_CHART_APPLICATION}&${order.permalink}' target="_top" style="color: var(--primary); cursor: pointer;">${order.orderName || ''}</a></div>
      <div class="column-value"><span class="badge ${badgeClass}">${order.type || ''}</span></div>
      <div class="column-value">${order.orderingProvider || ''}</div>
      <div class="column-value">${order.sentTo || ''}</div>
      <div class="column-value"><span class="badge ${statusBadgeClass}">${order.status}</span></div>
      <div class="column-value">${order.orderedDate || ''}</div>
      <div class="expand-icon ${!ENABLE_TASK_COMMENTS ? 'hidden' : ''} ${iconClass}">▶</div>
    </div>
    <div class="accordion-content" id="${orderId}">
      <div style="margin-bottom: 1rem;">
        <h4 style="margin: 0 0 0.5rem 0; font-weight: 600;">Task Comments</h4>
        <div id="comments-${orderId}" style="margin-bottom: 1rem; padding: 0.5rem; background-color: #f9fafb; border-radius: 0.375rem; min-height: 60px;">
          Loading comments...
        </div>
        <div style="display: flex; gap: 0.5rem;">
          <input type="text" id="comment-input-${orderId}" placeholder="Add a comment..." style="flex: 1; padding: 0.5rem; border: 1px solid #d1d5db; border-radius: 0.375rem;">
          <button id="add-btn-${orderId}" onclick="addComment('${order.patientId}', '${order.type}', '${order.id}')" style="padding: 0.5rem 1rem; background-color: var(--primary); color: white; border: none; border-radius: 0.375rem; cursor: pointer;">Add</button>

        </div>
      </div>
      ${actions ? `<div>${actions}</div>` : ''}
    </div>
  </div>
`;
}

function getBadgeClass(type) {
    switch (type?.toLowerCase()) {
        case 'lab':
            return 'badge-outline';
        case 'imaging':
            return 'badge-outline';
        case 'referral':
            return 'badge-outline';
        default:
            return 'badge-outline';
    }
}

function getStatusBadgeClass(status) {
    switch (status?.toLowerCase()) {
        case 'uncommitted':
            return 'badge-outline';
        case 'open/sent':
            return 'badge-secondary';
        case 'delegated':
            return 'badge-secondary';
        case 'closed':
            return 'badge-default';
        default:
            return 'badge-outline';
    }
}

function setupAccordionListeners() {
    // Get all accordion headers and add individual listeners
    const accordionHeaders = document.querySelectorAll('.accordion-header');

    accordionHeaders.forEach(header => {
        const headerId = header.id;
        if (!headerId) return; // Skip if no ID

        // Skip if this is a disabled header (Lab orders)
        if (header.classList.contains('disabled')) {
            return;
        }

        // Create a unique click handler for this specific header
        const clickHandler = function(event) {
            // Allow links to work normally
            if (event.target.tagName === 'A') {
                return; // Don't prevent default for links
            }

            event.preventDefault();
            event.stopPropagation();

            const targetId = this.getAttribute('data-target');
            const content = document.getElementById(targetId);
            const icon = this.querySelector('.expand-icon');

            if (!content || !icon) return;

            // Close all other accordion items first (single open behavior)
            const allHeaders = document.querySelectorAll('.accordion-header');
            allHeaders.forEach(otherHeader => {
                if (otherHeader.id !== headerId) {
                    const otherTargetId = otherHeader.getAttribute('data-target');
                    const otherContent = document.getElementById(otherTargetId);
                    const otherIcon = otherHeader.querySelector('.expand-icon');

                    if (otherContent && otherContent.classList.contains('show')) {
                        otherContent.classList.remove('show');
                        otherHeader.classList.remove('expanded');
                        if (otherIcon) otherIcon.classList.remove('rotated');
                    }
                }
            });

            // Toggle current accordion item
            const isCurrentlyOpen = content.classList.contains('show');

            if (isCurrentlyOpen) {
                content.classList.remove('show');
                this.classList.remove('expanded');
                icon.classList.remove('rotated');
            } else {
                content.classList.add('show');
                this.classList.add('expanded');
                icon.classList.add('rotated');

                // Get order data from the data attributes
                const patientId = this.getAttribute('data-patient-id');
                const orderType = this.getAttribute('data-order-type');
                const orderId = this.getAttribute('data-order-id');
                loadComments({
                    patientId,
                    type: orderType,
                    id: orderId
                });
            }
        };

        // Remove any existing listeners on this header
        header.removeEventListener('click', header._accordionClickHandler);

        // Store the handler reference and add the listener
        header._accordionClickHandler = clickHandler;
        header.addEventListener('click', clickHandler);
    });
}

async function loadComments(order) {
    const commentsDiv = document.getElementById(`comments-${order.id}`);
    try {
        let url = `/plugin-io/api/order_tracking/task-comments?order_type=${order.type}`;

        // Add specific ID parameters based on order type
        if (order.type.toLowerCase() === 'referral') {
            url += `&referral_id=${order.id}`;
        } else if (order.type.toLowerCase() === 'imaging') {
            url += `&imaging_id=${order.id}`;
        }

        const response = await fetch(url);
        const data = await response.json();

        // Store task_id for adding comments
        let taskId = null;
        if (data.comments && data.comments.length > 0) {
            taskId = data.comments[0].task_id; // All comments belong to the same task
            commentsDiv.innerHTML = data.comments.map(comment =>
                `<div style="margin-bottom: 0.75rem; padding: 0.75rem; background-color: white; border-radius: 0.5rem; border: 1px solid #e5e7eb; box-shadow: 0 1px 2px rgba(0,0,0,0.05);">
        <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 0.5rem; padding-bottom: 0.25rem; border-bottom: 1px solid #f3f4f6;">
          <div style="font-weight: 500; color: #374151; font-size: 0.875rem;">${comment.author}</div>
          <div style="font-size: 0.75rem; color: #6b7280;">${comment.date}</div>
        </div>
        <div style="color: #1f2937; line-height: 1.5; white-space: pre-wrap;">${comment.text}</div>
      </div>`
            ).join('');
        } else {
            commentsDiv.innerHTML = '<div style="color: #6b7280; font-style: italic; text-align: center; padding: 2rem;">No comments yet</div>';
        }

        // Store the task_id in a data attribute for the add comment button
        const addButton = document.getElementById(`add-btn-${order.id}`);
        if (addButton && taskId) {
            addButton.setAttribute('data-task-id', taskId);
        }
    } catch (error) {
        console.error('Error loading comments:', error);
        commentsDiv.innerHTML = '<div style="color: #dc2626;">Error loading comments</div>';
    }
}

async function addComment(patientId, orderType, orderId) {
    const input = document.getElementById(`comment-input-${orderId}`);
    const comment = input.value.trim();

    if (!comment) return;

    // Get the task_id from the button's data attribute
    const addButton = document.getElementById(`add-btn-${orderId}`);
    const taskId = addButton ? addButton.getAttribute('data-task-id') : null;

    try {
        const response = await fetch('/plugin-io/api/order_tracking/task-comments', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({
                patient_id: patientId,
                task_id: taskId,
                comment: comment,
                order_type: orderType,
                order_id: orderId
            })
        });

        if (response.ok) {
            input.value = '';
            loadComments({
                patientId,
                type: orderType,
                id: orderId
            });
        } else {
            console.error('Failed to add comment');
        }
    } catch (error) {
        console.error('Error adding comment:', error);
    }
}

document.addEventListener('DOMContentLoaded', async function() {
    initializeFilterToggle();

    // Initialize saved filters
    initializeSavedFilters();

    // Initialize clear filter button
    initializeClearFilters();

    // Initialize other components
    initializeDropdowns();
    initializePatientNameFilter();
    initializeDobFilter();
    initializeSentToFilter();
    initializeDateRangeFilter();

    // Load data
    await Promise.all([fetchProviders(), fetchLocations()]);

    // Initial load of orders
    handleFilterChange();
});

// Add this to your initializeSavedFilters() function
function initializeClearFilters() {
    const clearBtn = document.getElementById('clear-filters-btn');

    if (clearBtn) {
        clearBtn.addEventListener('click', () => {
            clearAllFilters();
        });
    }
}

// Add this new function
function clearAllFilters() {
    // Clear dropdowns - set all to "All" option
    const providerAllCheckbox = document.getElementById('provider-all');
    const typeAllCheckbox = document.getElementById('type-all');
    const statusAllCheckbox = document.getElementById('status-all');
    const locationDropdown = document.getElementById('location-dropdown');

    if (providerAllCheckbox) providerAllCheckbox.checked = true;
    if (typeAllCheckbox) typeAllCheckbox.checked = true;
    if (statusAllCheckbox) statusAllCheckbox.checked = true;

    if (locationDropdown) {
        const locationOptions = locationDropdown.querySelectorAll('.dropdown-option');
        const selectedValue = locationDropdown.querySelector('.selected-value');
        const allOption = locationDropdown.querySelector('.dropdown-option[data-value=""]');

        // Remove selected class from all options
        locationOptions.forEach(opt => opt.classList.remove('selected'));

        // Select "All Locations" option
        if (allOption) {
            allOption.classList.add('selected');
            selectedValue.innerHTML = `<span class="placeholder-text">All Locations</span>`;
            locationDropdown.setAttribute('data-value', '');
        }
    }

    // Clear all specific checkboxes
    document.querySelectorAll('.filter-dropdown input[type="checkbox"]:not([id$="-all"])').forEach(cb => {
        cb.checked = false;
    });

    // Clear text inputs
    document.getElementById('patient-name-filter').value = '';
    document.getElementById('sent-to-filter').value = '';
    document.getElementById('patient-dob-filter').value = '';
    document.getElementById('date-from-filter').value = '';
    document.getElementById('date-to-filter').value = '';

    // Update dropdown displays
    const providerDropdown = document.getElementById('provider-dropdown');
    const typeDropdown = document.getElementById('type-dropdown');
    const statusDropdown = document.getElementById('status-dropdown');
    updateSelectedDisplay(providerDropdown);
    updateSelectedDisplay(typeDropdown);
    updateSelectedDisplay(statusDropdown);

    // Trigger filter change
    handleFilterChange();
}

// Add this function to populate the location dropdown
function populateLocationsDropdown() {
    const locationOptions = document.getElementById('location-options');
    const locationDropdown = document.getElementById('location-dropdown');

    if (!locationOptions || !locationDropdown) return;

    let optionsHTML = `<div class="dropdown-option" data-value="">All Locations</div>`;

    allLocations.forEach((location, index) => {
        optionsHTML += `<div class="dropdown-option" data-value="${location.value}">${location.name}</div>`;
    });

    locationOptions.innerHTML = optionsHTML;

    // Setup single select listeners for location dropdown
    setupSingleSelectListeners(locationDropdown);
}

// Add this function to handle single select dropdowns
function setupSingleSelectListeners(dropdown) {
    const options = dropdown.querySelectorAll('.dropdown-option');

    options.forEach(option => {
        option.addEventListener('click', (e) => {
            e.stopPropagation();

            // Remove selected class from all options
            options.forEach(opt => opt.classList.remove('selected'));

            // Add selected class to clicked option
            option.classList.add('selected');

            // Update the dropdown display
            const selectedValue = dropdown.querySelector('.selected-value');
            const value = option.getAttribute('data-value');
            const text = option.textContent;

            if (value === '') {
                selectedValue.innerHTML = `<span class="placeholder-text">${text}</span>`;
            } else {
                selectedValue.innerHTML = `<span>${text}</span>`;
            }

            // Store the selected value
            dropdown.setAttribute('data-value', value);

            // Close dropdown
            dropdown.classList.remove('open');
            dropdown.querySelector('.dropdown-options').classList.remove('show');

            // Trigger filter change
            handleFilterChange();
        });
    });
}

function loadMoreOrders(priority) {
    fetchOrders(priority);
}