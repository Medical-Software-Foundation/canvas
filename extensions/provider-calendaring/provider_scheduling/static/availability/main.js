// Availability Manager - Vanilla JavaScript

const daysOfWeek = [
  { id: 'SU', label: 'Su' },
  { id: 'MO', label: 'Mo' },
  { id: 'TU', label: 'Tu' },
  { id: 'WE', label: 'We' },
  { id: 'TH', label: 'Th' },
  { id: 'FR', label: 'Fr' },
  { id: 'SA', label: 'Sa' }
];

// State
let state = {
  providers: window.providers || [],
  locations: window.locations || [],
  recurrenceTypes: window.recurrence || [],
  noteTypes: window.noteTypes || [],
  calendarTypes: window.calendarTypes || [],
  events: window.events || [],
  loggedInUserId: window.loggedInUserId || null,
  providerFilter: window.loggedInUserId || 'all',
  calendarTypeTab: 'available',
  showForm: false,
  editingEvent: null,
  currentEvent: {
    id: null,
    title: '',
    provider: null,
    location: null,
    calendarType: null,
    allowedNoteTypes: [],
    startTime: '',
    endTime: '',
    daysOfWeek: [],
    recurrence: {
      type: '',
      interval: 0,
      endType: 'times',
      endDate: ''
    }
  }
};

// Helper functions
function getLocationName(locationId) {
  const location = state.locations.find(l => l.id.toString() === locationId);
  return location ? location.name : '';
}

function getProviderById(id) {
  return state.providers.find(p => p.id === id);
}

function getFilteredEvents() {
  const availableType = state.calendarTypes.find(t => t.label === 'Available')?.value;
  const busyType = state.calendarTypes.find(t => t.label === 'Busy')?.value;
  const targetType = state.calendarTypeTab === 'available' ? availableType : busyType;

  return state.events.filter(event => {
    const matchesProvider = state.providerFilter === 'all' || event.provider === state.providerFilter;
    const matchesType = event.calendarType === targetType;
    return matchesProvider && matchesType;
  });
}

function updateCalendarTypeTab(value) {
  state.calendarTypeTab = value;
  render();
}

function updateProviderFilter(value) {
  state.providerFilter = value;
  render();
}

// Convert Date to datetime-local format in local timezone
function toLocalDateTimeString(date = new Date()) {
  const d = new Date(date);
  const year = d.getFullYear();
  const month = String(d.getMonth() + 1).padStart(2, '0');
  const day = String(d.getDate()).padStart(2, '0');
  const hours = String(d.getHours()).padStart(2, '0');
  const minutes = String(d.getMinutes()).padStart(2, '0');
  return `${year}-${month}-${day}T${hours}:${minutes}`;
}

// Convert datetime-local string to UTC ISO format for backend storage
function toUTCISOString(localDateTimeString) {
  if (!localDateTimeString) return '';
  // Create Date object from local datetime string (browser interprets as local time)
  const localDate = new Date(localDateTimeString);
  // Convert to ISO string (UTC format)
  return localDate.toISOString();
}

// Format date for display with timezone
function formatDateTime(dateString) {
  const date = new Date(dateString);
  return date.toLocaleString('en-US', {
    year: 'numeric',
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
    timeZoneName: 'short'
  });
}

function formatTime(dateString) {
  const date = new Date(dateString);
  return date.toLocaleString('en-US', {
    hour: '2-digit',
    minute: '2-digit'
  });
}

function formatDate(dateString) {
  const date = new Date(dateString);
  return date.toLocaleString('en-US', {
    year: 'numeric',
    month: 'short',
    day: 'numeric'
  });
}

// State management
function updateCurrentEvent(field, value) {
  state.currentEvent[field] = value;
}

function toggleProvider(providerId) {
  state.currentEvent.provider = providerId;
}

function toggleNoteType(noteTypeId) {
  const index = state.currentEvent.allowedNoteTypes.indexOf(noteTypeId);
  if (index > -1) {
    state.currentEvent.allowedNoteTypes.splice(index, 1);
  } else {
    state.currentEvent.allowedNoteTypes.push(noteTypeId);
  }
}

function toggleDay(dayId) {
  const index = state.currentEvent.daysOfWeek.indexOf(dayId);
  if (index > -1) {
    state.currentEvent.daysOfWeek.splice(index, 1);
  } else {
    state.currentEvent.daysOfWeek.push(dayId);
  }
  // Update button active state
  const button = document.getElementById(`day-button-${dayId}`);
  if (button) {
    button.classList.toggle('active');
  }
}

function updateRecurrence(field, value) {
  state.currentEvent.recurrence[field] = value;
}

function deleteEvent(eventId) {
  if (window.confirm('Are you sure you want to delete this availability event?')) {

    fetch('/plugin-io/api/provider_scheduling/events', {
        method: 'DELETE',
        headers: {
            'Content-Type': 'application/json',
        },
        body: JSON.stringify({ eventId })
    })
    .then(response => {
        if (!response.ok) throw new Error('Failed to delete event');

        state.events = state.events.filter(event => event.id !== eventId);

        render();
    }).catch(error => {
      alert('Error deleting event: ' + error.message);
    });


  }
}

function updateEvent() {
    if (state.currentEvent.recurrence.type === '' && (state.currentEvent.daysOfWeek.length > 0 || state.currentEvent.recurrence.interval !== 0)) {
      alert('Please select a recurrence frequency when days of the week are selected or an interval is set');
      return;
    }

    const event = state.currentEvent;

    const eventData = {
        eventId: event.id,
        title: event.title,
        startTime: toUTCISOString(event.startTime),
        endTime: toUTCISOString(event.endTime),
        recurrenceFrequency: event.recurrence.type,
        recurrenceInterval: event.recurrence.interval,
        recurrenceDays: event.daysOfWeek,
        recurrenceEndsAt: toUTCISOString(event.recurrence.endDate),
        allowedNoteTypes: event.allowedNoteTypes
    }

    fetch('/plugin-io/api/provider_scheduling/events', {
        method: 'PATCH',
        headers: {
            'Content-Type': 'application/json',
        },
        body: JSON.stringify(eventData)
    })
    .then(response => {
        if (!response.ok) throw new Error('Failed to update event');
        // TODO : Improve this logic to update state properly

        // Find the event in state.events and update its values after successful update
        const idx = state.events.findIndex(e => e.id === eventData.eventId);
        if (idx !== -1) {
          state.events[idx] = {
              ...state.events[idx],
              ...eventData,
              ...{allowedNoteTypes: event.allowedNoteTypes},
              ...{daysOfWeek: event.daysOfWeek},
              ...{recurrence: event.recurrence}
          };
          render();
        }
    }).catch(error => {
        alert('Error updating event: ' + error.message);
    });

    resetForm();
}

function saveEvent() {
    if (state.currentEvent.provider === null || state.currentEvent.title === '' || state.currentEvent.startTime === '' || state.currentEvent.endTime === '' || !state.currentEvent.location) {
        alert('Please fill in all required fields: provider, title, calendar, and start/end times.');
        return;
    }

    if (state.currentEvent.recurrence.type === '' && (state.currentEvent.daysOfWeek.length > 0 || state.currentEvent.recurrence.interval !== 0)) {
        alert('Please select a recurrence frequency when days of the week are selected or an interval is set');
        return;
    }

    const event = state.currentEvent;

    const calendarData = {
        provider: state.currentEvent.provider,
        providerName: getProviderById(state.currentEvent.provider).full_name,
        location: state.currentEvent.location || '',
        locationName: getLocationName(state.currentEvent.location),
        type: state.currentEvent.calendarType
    }

    fetch('/plugin-io/api/provider_scheduling/calendar', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
        },
        body: JSON.stringify(calendarData)
    })
        .then(response => {
            if (!response.ok) throw new Error('Failed to create calendar');
            return response.json();
        })
        .then(data => {
            const {calendarId} = data;

            if (calendarId) {
                const eventData = {
                    calendar: calendarId,
                    title: event.title,
                    startTime: toUTCISOString(event.startTime),
                    endTime: toUTCISOString(event.endTime),
                    recurrenceFrequency: event.recurrence.type,
                    recurrenceInterval: event.recurrence.interval,
                    recurrenceDays: event.daysOfWeek,
                    recurrenceEndsAt: toUTCISOString(event.recurrence.endDate),
                    allowedNoteTypes: event.allowedNoteTypes
                }

                fetch('/plugin-io/api/provider_scheduling/events', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                    },
                    body: JSON.stringify(eventData)
                })
                    .then(response => {
                        if (!response.ok) throw new Error('Failed to create event');

                        state.events.push({
                            ...event,
                            provider: event.provider,
                            location: event.location || '',
                            calendarType: event.calendarType,
                            allowedNoteTypes: event.allowedNoteTypes,
                            daysOfWeek: event.daysOfWeek,
                            recurrence: event.recurrence
                        });
                        render();

                        resetForm();

                    })
                    .catch(error => {
                        alert('Error saving event: ' + error.message);
                    });
            }
        })
        .catch(error => {
            alert('Error saving event: ' + error.message);
        });

    resetForm();
}

function resetForm() {
  state.currentEvent = {
    id: null,
    title: '',
    providers: [],
    location: null,
    calendarType: null,
    allowedNoteTypes: [],
    startTime: toLocalDateTimeString(),
    endTime: toLocalDateTimeString(),
    daysOfWeek: [],
    recurrence: {
      type: '',
      interval: 0,
      endType: 'times',
      endDate: ''
    }
  };
  state.showForm = false;
  state.editingEvent = null;
  render();
}

function editEvent(event) {
  state.currentEvent = JSON.parse(JSON.stringify(event));
  // Convert times to local datetime format for datetime-local inputs
  if (state.currentEvent.startTime) {
    state.currentEvent.startTime = toLocalDateTimeString(new Date(state.currentEvent.startTime));
  }
  if (state.currentEvent.endTime) {
    state.currentEvent.endTime = toLocalDateTimeString(new Date(state.currentEvent.endTime));
  }
  if (state.currentEvent.recurrence && state.currentEvent.recurrence.endDate) {
    state.currentEvent.recurrence.endDate = toLocalDateTimeString(new Date(state.currentEvent.recurrence.endDate));
  }
  state.editingEvent = event
  state.showForm = true;
  render();
}

function showForm() {
  // Pre-select provider if filtered to a specific provider
  if (state.providerFilter !== 'all') {
    state.currentEvent.provider = state.providerFilter;
  }
  state.showForm = true;
  render();
}

// Render functions
function render() {
  const app = document.getElementById('app');

  app.innerHTML = `
    <div class="app-container">
      <div class="max-width-container">
        ${state.showForm ? renderFormModal() : ''}
        ${renderEventsList()}
      </div>
    </div>
  `;
}

function renderFormModal() {
  return `
    <div class="modal-overlay">
      <div class="modal">
        <div class="modal-content">
          <div class="modal-body">
            <div class="modal-top-row">
              ${renderCalendarTypeToggle()}
              <button onclick="resetFormHandler()" class="btn-close">
                ✕
              </button>
            </div>
            <div class="grid grid-cols-2">
              ${renderEventNameInput()}
              ${renderProvidersSelect()}
            </div>
            ${renderLocationSelect()}
            <div class="grid grid-cols-1-2">
              ${renderStartTime()}
              ${renderDaysOfWeek()}
            </div>
            <div class="grid grid-cols-1-2">
              ${renderEndTime()}
              ${renderRecurrencePattern()}
            </div>
            ${renderNoteTypesSelect()}
          </div>

          <div class="modal-footer">
            <button
              onclick="resetFormHandler()"
              class="btn btn-secondary"
            >
              Cancel
            </button>
            ${state.currentEvent.id ? `
                <button
                  onclick="updateEventHandler()"
                  class="btn btn-primary"
                >
                  Update
                </button>
            ` : `
                <button
                  onclick="saveEventHandler()"
                  class="btn btn-primary"
                >
                  Save
                </button>
            `}

          </div>
        </div>
      </div>
    </div>
  `;
}

function renderEventNameInput() {
  return `
    <div class="form-group">
      <label class="form-label">
        Schedule Template Name *
      </label>
      <input
        type="text"
        id="template-name"
        value="${state.currentEvent.title}"
        onchange="updateEventNameHandler(this.value)"
        class="form-input"
        placeholder="e.g., Regular Weekday Schedule"
      />
    </div>
  `;
}

function renderProvidersSelect() {
  const isNewEvent = !state.currentEvent.id;
  const isEditing = !!state.currentEvent.id;
  const hasPreselectedProvider = isNewEvent && state.currentEvent.provider && state.providerFilter !== 'all';
  const selectedProvider = state.currentEvent.provider ? getProviderById(state.currentEvent.provider) : null;

  // Show label + hidden field when editing or creating new event with pre-selected provider from filter
  if ((hasPreselectedProvider || isEditing) && selectedProvider) {
    return `
      <div class="form-group">
        <label class="form-label">
          Provider
        </label>
        <input type="hidden" id="provider-select" value="${selectedProvider.id}" />
        <div class="provider-display">${selectedProvider.name}</div>
      </div>
    `;
  }

  // Show dropdown for selecting provider (new event without filter)
  return `
    <div class="form-group">
      <label class="form-label">
        Assign Provider *
      </label>
      <div class="grid providers-container">
        <select
          id="provider-select"
          onchange="toggleProviderHandler(this.value)"
          class="form-select"
        >
          <option value="">Select a provider</option>
          ${state.providers.map(provider => `
            <option value="${provider.id}" ${state.currentEvent.provider === provider.id ? 'selected' : ''}>
              ${provider.name}
            </option>
          `).join('')}
        </select>
      </div>
    </div>
  `;
}

function renderNoteTypesSelect() {
  const allSelected = state.noteTypes.length > 0 &&
    state.noteTypes.every(nt => state.currentEvent.allowedNoteTypes.includes(nt.id));

  return `
    <div class="form-group">
      <label class="form-label">
        Allowed Note Types
      </label>
      <div class="grid providers-container">
        ${state.noteTypes.length > 1 ? `
          <label class="provider-item select-all-item">
            <input
              type="checkbox"
              ${allSelected ? 'checked' : ''}
              onchange="selectAllNoteTypesHandler(this.checked)"
              class="provider-checkbox"
            />
            <div class="provider-info">
              <p class="provider-name"><strong>Select All</strong></p>
            </div>
          </label>
        ` : ''}
        ${state.noteTypes.map(noteType => `
          <label class="provider-item">
            <input
              type="checkbox"
              ${state.currentEvent.allowedNoteTypes.includes(noteType.id) ? 'checked' : ''}
              onchange="toggleNoteTypeHandler('${noteType.id}')"
              class="provider-checkbox"
            />
            <div class="provider-info">
              <p class="provider-name">${noteType.name}</p>
            </div>
          </label>
        `).join('')}
      </div>
    </div>
  `;
}

function renderLocationSelect() {
  return `
    <div class="form-group">
      <label class="form-label">
        Calendar *
      </label>
      <select
        id="location-select"
        onchange="updateLocationHandler(this.value)"
        class="form-select"
        ${state.currentEvent.id ? 'disabled' : ''}
      >
        <option value="">Select a calendar</option>
        ${state.locations.map(location => `
          <option value="${location.id}" ${state.currentEvent.location === location.id ? 'selected' : ''}>
            ${location.name}
          </option>
        `).join('')}
      </select>
    </div>
  `;
}

function renderCalendarTypeToggle() {
  const availableType = state.calendarTypes.find(t => t.label === 'Available');
  const busyType = state.calendarTypes.find(t => t.label === 'Busy');
  const isAvailable = state.currentEvent.calendarType === availableType?.value || !state.currentEvent.calendarType;
  const isDisabled = state.currentEvent.id ? 'disabled' : '';

  return `
    <div class="calendar-type-toggle ${isDisabled ? 'disabled' : ''}">
      <button
        type="button"
        class="toggle-option ${isAvailable ? 'active' : ''}"
        onclick="${!isDisabled ? `updateCalendarTypeHandler('${availableType?.value}')` : ''}"
        ${isDisabled}
      >
        Available
      </button>
      <button
        type="button"
        class="toggle-option ${!isAvailable ? 'active' : ''}"
        onclick="${!isDisabled ? `updateCalendarTypeHandler('${busyType?.value}')` : ''}"
        ${isDisabled}
      >
        Busy
      </button>
    </div>
  `;
}

function renderStartTime() {
  return `
    <div class="form-group">
      <label class="form-label">
        Start Time *
      </label>
      <input
        type="datetime-local"
        id="start-time"
        value="${state.currentEvent.startTime}"
        onchange="updateStartTimeHandler(this.value)"
        class="form-input"
      />
    </div>
  `;
}

function renderEndTime() {
  return `
    <div class="form-group">
      <label class="form-label">
        End Time *
      </label>
      <input
        type="datetime-local"
        id="end-time"
        value="${state.currentEvent.endTime}"
        onchange="updateEndTimeHandler(this.value)"
        class="form-input"
      />
    </div>
  `;
}

function renderDaysOfWeek() {
  return `
    <div class="form-group">
      <label class="form-label">
        Days of Week
      </label>
      <div class="days-of-week-container">
        ${daysOfWeek.map(day => `
          <button
            id="day-button-${day.id}"
            type="button"
            onclick="toggleDayHandler('${day.id}')"
            class="day-button ${state.currentEvent.daysOfWeek.includes(day.id) ? 'active' : ''}"
          >
            ${day.label}
          </button>
        `).join('')}
      </div>
    </div>
  `;
}

function renderRecurrencePattern() {
  const endType = state.currentEvent.recurrence.endType || 'times';

  return `
    <div class="form-group">
      <label class="form-label">
        Recurrence Pattern
      </label>
      <div class="recurrence-fields">
        <select
          id="recurrence-type"
          onchange="updateRecurrenceTypeHandler(this.value)"
          class="form-select"
        >
          <option value="" ${state.currentEvent.recurrence.type === null || state.currentEvent.recurrence.type === '' ? 'selected' : ''}>
            Frequency
          </option>
          ${state.recurrenceTypes.map(type => `
            <option value="${type.value}" ${state.currentEvent.recurrence.type === type.value ? 'selected' : ''}>
              ${type.label}
            </option>
          `).join('')}
        </select>
        <div class="recurrence-end-options">
          <label class="recurrence-end-option">
            <input
              type="radio"
              name="recurrence-end-type"
              value="times"
              ${endType === 'times' ? 'checked' : ''}
              onchange="updateRecurrenceEndTypeHandler('times')"
            />
            <input
              type="number"
              min="1"
              max="12"
              id="recurrence-interval"
              value="${state.currentEvent.recurrence.interval}"
              onchange="updateRecurrenceIntervalHandler(this.value)"
              class="form-input input-narrow"
              placeholder="#"
              ${endType !== 'times' ? 'disabled' : ''}
            />
            <span class="recurrence-label">times</span>
          </label>
          <label class="recurrence-end-option">
            <input
              type="radio"
              name="recurrence-end-type"
              value="until"
              ${endType === 'until' ? 'checked' : ''}
              onchange="updateRecurrenceEndTypeHandler('until')"
            />
            <span class="recurrence-label">until</span>
            <input
              type="date"
              id="recurrence-end-date"
              value="${state.currentEvent.recurrence.endDate ? state.currentEvent.recurrence.endDate.split('T')[0] : ''}"
              onchange="updateRecurrenceEndDateHandler(this.value)"
              class="form-input"
              ${endType !== 'until' ? 'disabled' : ''}
            />
          </label>
        </div>
      </div>
    </div>
  `;
}

function renderEventsList() {
  const filteredEvents = getFilteredEvents();

  // Group events by provider
  const eventsByProvider = {};
  filteredEvents.forEach(event => {
    const providerId = event.provider || 'unknown';
    if (!eventsByProvider[providerId]) {
      eventsByProvider[providerId] = [];
    }
    eventsByProvider[providerId].push(event);
  });

  // Render grouped events
  const groupedEventsHtml = Object.keys(eventsByProvider).map(providerId => {
    const provider = getProviderById(providerId);
    const providerName = provider ? provider.full_name : 'Unknown Provider';
    const events = eventsByProvider[providerId];

    return `
      <div class="provider-group">
        <div class="provider-group-header">
          ${providerName}
        </div>
        ${events.map(event => renderEventCard(event)).join('')}
      </div>
    `;
  }).join('');

  return `
    <div class="events-container">
      <div class="events-header">
        <h2 class="events-title">
          Availability
        </h2>
        <div class="events-header-actions">
          <div class="events-filter">
            <label for="provider-filter" class="filter-label">Filter by Provider:</label>
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
          <button
            onclick="showFormHandler()"
            class="btn btn-primary"
          >
            + New Schedule Template
          </button>
        </div>
      </div>

      <div class="events-tabs">
        <button
          class="events-tab ${state.calendarTypeTab === 'available' ? 'active' : ''}"
          onclick="updateCalendarTypeTabHandler('available')"
        >
          Available
        </button>
        <button
          class="events-tab ${state.calendarTypeTab === 'busy' ? 'active' : ''}"
          onclick="updateCalendarTypeTabHandler('busy')"
        >
          Busy
        </button>
      </div>

      <div class="events-list">
        ${groupedEventsHtml}
      </div>
    </div>
  `;
}

function renderEventCard(event) {
  const recurrenceLabel = event.recurrence.type
    ? state.recurrenceTypes.find(t => t.value === event.recurrence.type)?.label
    : '';

  const dayOrder = ['SU', 'MO', 'TU', 'WE', 'TH', 'FR', 'SA'];
  const dayLabels = { SU: 'Su', MO: 'Mo', TU: 'Tu', WE: 'We', TH: 'Th', FR: 'Fr', SA: 'Sa' };
  const daysOfWeekStr = event.daysOfWeek && event.daysOfWeek.length > 0
    ? event.daysOfWeek
        .slice()
        .sort((a, b) => dayOrder.indexOf(a) - dayOrder.indexOf(b))
        .map(d => dayLabels[d])
        .join(' ')
    : '';

  const timeRange = `from ${formatTime(event.startTime)} to ${formatTime(event.endTime)}`;

  const recurrenceRule = event.recurrence.endDate
    ? `until ${formatDate(event.recurrence.endDate)}`
    : event.recurrence.interval && event.recurrence.interval > 0
      ? `${event.recurrence.interval} times`
      : '';

  const scheduleSentence = [
    daysOfWeekStr,
    timeRange,
    recurrenceLabel && recurrenceRule ? `${recurrenceLabel} ${recurrenceRule}` : recurrenceLabel
  ].filter(Boolean).join(', ');

  return `
    <div class="template-card">
      <div class="template-content">
        <div class="template-info">
          <div class="template-header">
            ${recurrenceLabel ? `
              <span class="badge badge-blue">
                ${recurrenceLabel}
              </span>
            ` : ''}
            <h3 class="template-name">${event.title}</h3>
            <span class="schedule-sentence">${scheduleSentence}</span>
          </div>

          ${event.location !== '' ? `
          <div class="template-details">
            <div class="detail-item">
              <span>${getLocationName(event.location)}</span>
            </div>
          </div>
          ` : ''}
        </div>

        <div class="template-actions">
          <button
            onclick="editEventHandler('${event.id}')"
            class="btn-icon"
            title="Edit Event"
          >
            ✏️
          </button>
          <button
            onclick="deleteEventHandler('${event.id}')"
            class="btn-icon delete"
            title="Delete Event"
          >
            🗑️
          </button>
        </div>
      </div>
    </div>
  `;
}

// Event handlers (global functions for onclick attributes)
function showFormHandler() {
  showForm();
}

function resetFormHandler() {
  resetForm();
}

function saveEventHandler() {
  saveEvent();
}

function updateEventHandler() {
  updateEvent();
}

function updateEventNameHandler(value) {
  updateCurrentEvent('title', value);
}

function toggleProviderHandler(id) {
  toggleProvider(id);
}

function toggleNoteTypeHandler(id) {
  toggleNoteType(id);
  render();
}

function selectAllNoteTypesHandler(checked) {
  if (checked) {
    state.currentEvent.allowedNoteTypes = state.noteTypes.map(nt => nt.id);
  } else {
    state.currentEvent.allowedNoteTypes = [];
  }
  render();
}

function updateLocationHandler(value) {
  updateCurrentEvent('location', value);
}

function updateCalendarTypeHandler(value) {
  updateCurrentEvent('calendarType', value);
  render();
}

function updateStartTimeHandler(value) {
  updateCurrentEvent('startTime', value);
}

function updateEndTimeHandler(value) {
  updateCurrentEvent('endTime', value);
}

function toggleDayHandler(dayId) {
  toggleDay(dayId);
}

function updateRecurrenceTypeHandler(value) {
  updateRecurrence('type', value);
}

function updateRecurrenceIntervalHandler(value) {
  updateRecurrence('interval', parseInt(value));
}

function updateRecurrenceEndTypeHandler(value) {
  updateRecurrence('endType', value);
  render();
}

function updateRecurrenceEndDateHandler(value) {
  updateRecurrence('endDate', value);
}

function editEventHandler(id) {
  const event = state.events.find(t => t.id === id);
  if (event) {
    editEvent(event);
  }
}

function deleteEventHandler(id) {
  deleteEvent(id);
}

function updateProviderFilterHandler(value) {
  updateProviderFilter(value);
}

function updateCalendarTypeTabHandler(value) {
  updateCalendarTypeTab(value);
}

// Initialize the app
document.addEventListener('DOMContentLoaded', function() {
  render();
});
