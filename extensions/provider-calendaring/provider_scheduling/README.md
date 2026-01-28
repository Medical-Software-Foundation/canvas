# Provider Scheduling Plugin

A Canvas plugin for managing provider availability calendars and viewing schedule utilization metrics.

## Applications

This plugin provides two applications accessible from the provider menu:

### 1. Availability Manager

The Availability Manager allows providers and staff to create and manage schedule templates that define when providers are available for appointments or blocked for administrative time.

#### Features

- **Schedule Templates**: Create recurring availability blocks with customizable:
  - Template name
  - Provider assignment
  - Calendar (location)
  - Start and end times
  - Days of week
  - Recurrence pattern (daily/weekly)
  - Recurrence end (number of times or until a specific date)
  - Allowed note types for appointments

- **Available vs Busy**: Toggle between two calendar types:
  - **Available** (Clinic): Time slots when the provider can see patients
  - **Busy** (Administrative): Blocked time for meetings, paperwork, etc.

- **Provider Filtering**: Filter the view by provider, defaulting to the logged-in user

- **Grouped Display**: Events are grouped by provider with clear separators

#### Usage

1. Access from the provider menu by clicking "Availability Manager"
2. Use the provider filter to view specific provider schedules or all providers
3. Toggle between "Available" and "Busy" tabs to see different event types
4. Click "+ New Schedule Template" to create a new availability block
5. Fill in the form fields and click "Save"
6. Click on any existing template to edit or delete it

---

### 2. Schedule Utilization

The Schedule Utilization dashboard provides metrics on how effectively provider time is being used, comparing available time against actual booked appointments.

#### Features

- **Utilization Metrics**: For each provider, view:
  - **Available**: Total hours marked as available (from Clinic calendar events)
  - **Booked**: Total hours of scheduled appointments
  - **Unbooked**: Available time that wasn't booked (Available - Booked)
  - **Administrative**: Total hours blocked for administrative tasks

- **Lookback Period**: Toggle between viewing data for:
  - Past Day
  - Past Week
  - Past Month

- **Provider Filtering**: View metrics for all providers or filter to a specific provider

- **Expandable Rows**: Click on any provider row to expand and see a pie chart breakdown of their time allocation

- **CSV Export**: Export the current view to a CSV file for reporting and analysis

#### Usage

1. Access from the provider menu by clicking "Schedule Utilization"
2. Select a lookback period (Past Day, Past Week, or Past Month)
3. Optionally filter to a specific provider
4. Click on a provider row to expand and view the pie chart breakdown
5. Click "Export CSV" to download the current data

#### Metrics Calculation

- **Available Minutes**: Sum of all Clinic calendar event durations for the provider in the selected period
- **Administrative Minutes**: Sum of all Admin calendar event durations for the provider in the selected period
- **Booked Minutes**: Sum of appointment durations (excluding cancelled and no-showed appointments)
- **Unbooked Minutes**: Available minutes minus booked minutes

---

## Technical Details

### Components

#### Applications
- `AvailabilityManager`: Launches the availability management interface
- `UtilizationDashboard`: Launches the utilization metrics dashboard

#### API Endpoints
- `CalendarAPI`: Create and retrieve calendars
- `CalendarEventsAPI`: Create, update, and delete calendar events
- `UtilizationAPI`: Retrieve utilization metrics for a provider

#### Web Handlers
- `AvailabilityWebApp`: Serves the Availability Manager application
- `UtilizationWebApp`: Serves the Schedule Utilization dashboard

### Data Models Used

- **Staff**: Provider information
- **Calendar**: Calendar containers with type (Clinic/Admin) and location
- **Event**: Calendar events with recurrence rules
- **Appointment**: Patient appointments with duration and status

### Calendar Naming Convention

Calendars follow the naming pattern:
```
{Provider Name}: {Calendar Type}: {Location}
```

For example:
- `Dr. Jane Smith: Clinic: Main Office`
- `Dr. Jane Smith: Admin`

---

## Installation

1. Ensure the `CANVAS_MANIFEST.json` is properly configured
2. Install the plugin through the Canvas plugin system
3. The applications will appear in the provider menu for users with appropriate access

## Notes

- Both applications default to showing data for the currently logged-in provider
- The plugin requires staff to have clinical or hybrid roles to appear in provider lists
- All times are handled in UTC and converted for display
