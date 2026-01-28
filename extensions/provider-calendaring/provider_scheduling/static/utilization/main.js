// Schedule Utilization Dashboard - Vanilla JavaScript

// State
let state = {
  providers: window.providers || [],
  loggedInUserId: window.loggedInUserId || null,
  providerFilter: window.loggedInUserId || 'all',
  lookbackPeriod: 'week', // 'day', 'week', 'month'
  expandedRows: {}, // { providerId: true/false }
  providerMetrics: {}, // { `${providerId}-${lookbackPeriod}`: { loading, error, data } }
};

// Helper functions
function getProviderById(id) {
  return state.providers.find(p => p.id === id);
}

function getMetricsKey(providerId) {
  return `${providerId}-${state.lookbackPeriod}`;
}

function getProviderMetrics(providerId) {
  const key = getMetricsKey(providerId);
  return state.providerMetrics[key] || null;
}

async function fetchProviderMetrics(providerId) {
  const key = getMetricsKey(providerId);

  // Skip if already loading or loaded
  if (state.providerMetrics[key]?.loading || state.providerMetrics[key]?.data) {
    return;
  }

  // Set loading state
  state.providerMetrics[key] = { loading: true, error: null, data: null };
  render();

  try {
    const response = await fetch(
      `/plugin-io/api/provider_scheduling/utilization?provider_id=${providerId}&lookback_period=${state.lookbackPeriod}`
    );

    if (!response.ok) {
      throw new Error('Failed to fetch utilization data');
    }

    const data = await response.json();
    state.providerMetrics[key] = { loading: false, error: null, data };
  } catch (error) {
    state.providerMetrics[key] = { loading: false, error: error.message, data: null };
  }

  render();
}

function formatMinutesAsHours(minutes) {
  if (minutes === null || minutes === undefined) return '--';
  const hours = Math.round(minutes / 60 * 10) / 10;
  return `${hours}h`;
}

function formatMinutesAsHoursNumeric(minutes) {
  if (minutes === null || minutes === undefined) return '';
  return Math.round(minutes / 60 * 10) / 10;
}

function exportToCSV() {
  const providers = getFilteredProviders();
  const lookbackLabels = { day: 'Past Day', week: 'Past Week', month: 'Past Month' };
  const lookbackLabel = lookbackLabels[state.lookbackPeriod] || state.lookbackPeriod;

  // CSV header
  const headers = ['Provider', 'Period', 'Available (hours)', 'Booked (hours)', 'Unbooked (hours)', 'Administrative (hours)'];

  // CSV rows
  const rows = providers.map(provider => {
    const metricsState = getProviderMetrics(provider.id);
    const data = metricsState?.data;

    return [
      provider.full_name,
      lookbackLabel,
      formatMinutesAsHoursNumeric(data?.availableMinutes),
      formatMinutesAsHoursNumeric(data?.bookedMinutes),
      formatMinutesAsHoursNumeric(data?.unbookedMinutes),
      formatMinutesAsHoursNumeric(data?.administrativeMinutes),
    ];
  });

  // Build CSV content
  const csvContent = [
    headers.join(','),
    ...rows.map(row => row.map(cell => `"${cell}"`).join(','))
  ].join('\n');

  // Create and trigger download
  const blob = new Blob([csvContent], { type: 'text/csv;charset=utf-8;' });
  const link = document.createElement('a');
  const url = URL.createObjectURL(blob);

  const timestamp = new Date().toISOString().split('T')[0];
  link.setAttribute('href', url);
  link.setAttribute('download', `utilization-${state.lookbackPeriod}-${timestamp}.csv`);
  link.style.visibility = 'hidden';

  document.body.appendChild(link);
  link.click();
  document.body.removeChild(link);
}

function updateProviderFilter(value) {
  state.providerFilter = value;
  render();
}

function updateLookbackPeriod(value) {
  state.lookbackPeriod = value;
  // Clear metrics cache when lookback period changes - will refetch
  state.providerMetrics = {};
  render();
}

function toggleRowExpanded(providerId) {
  state.expandedRows[providerId] = !state.expandedRows[providerId];
  render();
}

function renderAllPieCharts() {
  Object.keys(state.expandedRows).forEach(providerId => {
    if (state.expandedRows[providerId]) {
      renderPieChart(providerId);
    }
  });
}

// Render functions
function render() {
  const app = document.getElementById('app');

  app.innerHTML = `
    <div class="app-container">
      <div class="max-width-container">
        ${renderHeader()}
        ${renderDashboard()}
      </div>
    </div>
  `;

  // Render pie charts for all expanded rows after DOM update
  setTimeout(() => renderAllPieCharts(), 0);
}

function renderHeader() {
  return `
    <div class="header">
      <div class="header-content">
        <div>
          <h1 class="header-title">Schedule Utilization</h1>
          <p class="header-subtitle">View scheduling metrics and utilization rates</p>
        </div>
        <div class="header-actions">
          ${renderLookbackToggle()}
          <div class="provider-filter">
            <label for="provider-filter" class="filter-label">Provider:</label>
            <select
              id="provider-filter"
              onchange="updateProviderFilterHandler(this.value)"
              class="form-select"
            >
              <option value="all" ${state.providerFilter === 'all' ? 'selected' : ''}>
                All Providers
              </option>
              ${state.providers.map(provider => `
                <option value="${provider.id}" ${state.providerFilter === provider.id ? 'selected' : ''}>
                  ${provider.name}
                </option>
              `).join('')}
            </select>
          </div>
          <button onclick="exportToCSVHandler()" class="btn btn-secondary">
            Export CSV
          </button>
        </div>
      </div>
    </div>
  `;
}

function renderLookbackToggle() {
  return `
    <div class="lookback-toggle">
      <button
        type="button"
        class="toggle-option ${state.lookbackPeriod === 'day' ? 'active' : ''}"
        onclick="updateLookbackPeriodHandler('day')"
      >
        Past Day
      </button>
      <button
        type="button"
        class="toggle-option ${state.lookbackPeriod === 'week' ? 'active' : ''}"
        onclick="updateLookbackPeriodHandler('week')"
      >
        Past Week
      </button>
      <button
        type="button"
        class="toggle-option ${state.lookbackPeriod === 'month' ? 'active' : ''}"
        onclick="updateLookbackPeriodHandler('month')"
      >
        Past Month
      </button>
    </div>
  `;
}

function getFilteredProviders() {
  if (state.providerFilter === 'all') {
    return state.providers;
  }
  const provider = getProviderById(state.providerFilter);
  return provider ? [provider] : [];
}

function renderDashboard() {
  const providers = getFilteredProviders();

  return `
    <div class="dashboard-container">
      ${providers.length > 0
        ? providers.map(provider => renderProviderRow(provider)).join('')
        : '<div class="empty-state"><p class="empty-text">No providers found.</p></div>'
      }
    </div>
  `;
}

function renderProviderRow(provider) {
  const metricsState = getProviderMetrics(provider.id);
  const isLoading = metricsState?.loading;
  const metricsData = metricsState?.data;

  // Trigger fetch if no data yet
  if (!metricsState) {
    setTimeout(() => fetchProviderMetrics(provider.id), 0);
  }

  const metrics = {
    availableTime: isLoading ? '...' : formatMinutesAsHours(metricsData?.availableMinutes),
    bookedTime: isLoading ? '...' : formatMinutesAsHours(metricsData?.bookedMinutes),
    administrativeTime: isLoading ? '...' : formatMinutesAsHours(metricsData?.administrativeMinutes),
    unbookedTime: isLoading ? '...' : formatMinutesAsHours(metricsData?.unbookedMinutes),
  };

  const isExpanded = state.expandedRows[provider.id];

  return `
    <div class="provider-row-container ${isExpanded ? 'expanded' : ''}">
      <div class="provider-row" onclick="toggleRowExpandedHandler('${provider.id}')">
        <div class="provider-row-left">
          <span class="expand-icon">${isExpanded ? '▼' : '▶'}</span>
          <div class="provider-row-name">${provider.full_name}</div>
        </div>
        <div class="provider-row-metrics">
          <div class="metric">
            <span class="metric-value">${metrics.availableTime}</span>
            <span class="metric-label">Available</span>
          </div>
          <div class="metric">
            <span class="metric-value">${metrics.bookedTime}</span>
            <span class="metric-label">Booked</span>
          </div>
          <div class="metric">
            <span class="metric-value">${metrics.unbookedTime}</span>
            <span class="metric-label">Unbooked</span>
          </div>
          <div class="metric">
            <span class="metric-value">${metrics.administrativeTime}</span>
            <span class="metric-label">Administrative</span>
          </div>
        </div>
      </div>
      ${isExpanded ? `
        <div class="provider-row-expanded">
          <div class="pie-chart-container" id="pie-chart-${provider.id}"></div>
          <div class="pie-chart-legend" id="pie-legend-${provider.id}"></div>
        </div>
      ` : ''}
    </div>
  `;
}

function renderPieChart(providerId) {
  const container = document.getElementById(`pie-chart-${providerId}`);
  const legendContainer = document.getElementById(`pie-legend-${providerId}`);

  if (!container) return;

  const metricsState = getProviderMetrics(providerId);
  const metricsData = metricsState?.data;

  if (!metricsData) {
    container.innerHTML = '<p class="empty-text">Loading...</p>';
    return;
  }

  // Calculate percentages based on available time
  const total = metricsData.bookedMinutes + metricsData.unbookedMinutes + metricsData.administrativeMinutes;
  const bookedPct = total > 0 ? Math.round((metricsData.bookedMinutes / total) * 100) : 0;
  const unbookedPct = total > 0 ? Math.round((metricsData.unbookedMinutes / total) * 100) : 0;
  const adminPct = total > 0 ? Math.round((metricsData.administrativeMinutes / total) * 100) : 0;

  const data = [
    { label: 'Booked', value: bookedPct, color: '#22c55e' },
    { label: 'Unbooked', value: unbookedPct, color: '#eab308' },
    { label: 'Administrative', value: adminPct, color: '#3b82f6' },
  ].filter(d => d.value > 0);

  if (data.length === 0) {
    container.innerHTML = '<p class="empty-text">No data available</p>';
    if (legendContainer) legendContainer.innerHTML = '';
    return;
  }

  const width = 200;
  const height = 200;
  const radius = Math.min(width, height) / 2;

  // Clear any existing chart
  d3.select(container).selectAll('*').remove();

  const svg = d3.select(container)
    .append('svg')
    .attr('width', width)
    .attr('height', height)
    .append('g')
    .attr('transform', `translate(${width / 2}, ${height / 2})`);

  const pie = d3.pie()
    .value(d => d.value)
    .sort(null);

  const arc = d3.arc()
    .innerRadius(0)
    .outerRadius(radius - 10);

  const arcs = svg.selectAll('arc')
    .data(pie(data))
    .enter()
    .append('g');

  arcs.append('path')
    .attr('d', arc)
    .attr('fill', d => d.data.color)
    .attr('stroke', 'white')
    .attr('stroke-width', 2);

  // Render legend
  if (legendContainer) {
    legendContainer.innerHTML = data.map(d => `
      <div class="legend-item">
        <span class="legend-color" style="background-color: ${d.color}"></span>
        <span class="legend-label">${d.label}</span>
        <span class="legend-value">${d.value}%</span>
      </div>
    `).join('');
  }
}

// Event handlers
function updateProviderFilterHandler(value) {
  updateProviderFilter(value);
}

function updateLookbackPeriodHandler(value) {
  updateLookbackPeriod(value);
}

function toggleRowExpandedHandler(providerId) {
  toggleRowExpanded(providerId);
}

function exportToCSVHandler() {
  exportToCSV();
}

// Initialize the app
document.addEventListener('DOMContentLoaded', function() {
  render();
});
