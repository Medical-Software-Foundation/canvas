# Order Tracking Plugin

## Overview

The Order Tracking plugin provides comprehensive tracking and management of outstanding medical orders within Canvas Medical. It displays outstanding laboratory orders, imaging orders, and referrals in an organized interface with advanced filtering capabilities, allowing healthcare providers to efficiently monitor and follow up on pending orders.

Orders are removed from the dashboard when a result has been linked. **There is currently no way to manually mark an order as resolved or choose to ignore an outstanding order**

## Features

- **Multi-Order Type Support**: Tracks lab orders, imaging orders, and referrals
- **Dual Views**: Global worklist view and patient-specific view
- **Advanced Filtering**: Filter by provider, location, order type, status, patient name, DOB, sent to location, and date range
- **Saved Filter Presets**: Save and manage custom filter combinations
- **Priority Categorization**: Separates urgent and routine orders with visual indicators
- **Pagination**: Handles large datasets with paginated results
- **Task Comments**: Add and view comments on imaging and referral orders (when enabled)


## How to Access

### Installation

Install the plugin using the Canvas CLI:
```bash
canvas plugin install order_tracking
```

### User Interface Access

The plugin provides two access points:

1. **Global Order Tracking Application**
   - Scope: Global (available system-wide)
   - Opens a full-page modal showing all outstanding orders across the system
   - Accessible from the Canvas main navigation

2. **Patient Order Tracking Application**
   - Scope: Patient-specific
   - Opens in the right chart pane when viewing a patient record
   - Shows orders filtered to the current patient only


## Configuration Through Secrets

### Available Secrets

| Secret Name | Description | Default Value | Required |
|-------------|-------------|---------------|----------|
| `ENABLE_TASK_COMMENTS` | Enable/disable task commenting functionality for orders | `"true"` | No |

### Setting Secrets

Configure secrets through the Canvas admin interface or via Canvas CLI:

```bash
# Enable task comments (default)
canvas secret set ENABLE_TASK_COMMENTS "true"

# Disable task comments
canvas secret set ENABLE_TASK_COMMENTS "false"
```

When `ENABLE_TASK_COMMENTS` is enabled:
- Users can expand order rows to view and add comments
- Comments are linked to tasks associated with imaging and referral orders
- Lab orders do not support commenting in the current implementation

## Order Types Supported

### Lab Orders
- **Status tracking**: uncommitted, open/sent, closed
- **Display**: Shows test names, ordering provider, lab partner
- **Limitations**: No task commenting, always considered routine priority

### Imaging Orders
- **Status tracking**: uncommitted, delegated, open, closed
- **Priority support**: Urgent and routine
- **Task support**: Full task commenting when enabled
- **Display**: Shows imaging type, ordering provider, imaging center

### Referrals
- **Status tracking**: uncommitted, delegated, open, closed
- **Priority support**: Urgent and routine
- **Task support**: Full task commenting when enabled
- **Display**: Shows referral specialty, ordering provider, service provider

## Status Definitions

- **Uncommitted**: Order created but not yet committed/finalized
- **Delegated**: Order forwarded to staff for handling
- **Open**: Order committed. 
- **Sent**: Order committed and sent electronically. (Labs only. Status of outbound faxes are not reflected).
- **Closed**: Order completed with results received

## Filtering Capabilities

### Available Filters

1. **Ordering Provider**: Multi-select dropdown of providers who have created orders
2. **Location**: Single-select dropdown of practice locations
3. **Type**: Multi-select of order types (Lab, Imaging, Referral)
4. **Status**: Multi-select of order statuses
5. **Patient Name**: Text search across patient first, middle, and last names
6. **Patient DOB**: Date picker for exact date of birth matching
7. **Sent To**: Text search across external provider/facility names
8. **Order Date Range**: Date range picker for when orders were placed

### Saved Filter Presets

- Save frequently used filter combinations with custom names
- Quickly apply saved presets from the filter interface
- Manage saved presets (load, delete)
- Presets are saved per user

## API Endpoints

The plugin provides several internal API endpoints:

- `/plugin-io/api/order_tracking/main.css` - Stylesheet
- `/plugin-io/api/order_tracking/main.js` - JavaScript functionality
- `/plugin-io/api/order_tracking/providers` - Provider data for filters
- `/plugin-io/api/order_tracking/locations` - Location data for filters
- `/plugin-io/api/order_tracking/orders` - Order data with filtering and pagination
- `/plugin-io/api/order_tracking/task-comments` - Task comment management
- `/plugin-io/api/order_tracking/filter` - Saved filter management
- `/plugin-io/api/order_tracking/filters` - Retrieve saved filters

## Data Caching

The plugin uses Canvas caching for:
- Saved filter presets (stored per user)
- Improved performance for frequently accessed data

## Pagination

- Default page size: 20 orders
- Separate pagination for urgent and routine orders
- "Load More" functionality for seamless browsing
- Display of total counts and current position

## Technical Implementation

### Database Integration
- Integrates with Canvas ORM models: `ImagingOrder`, `LabOrder`, `Referral`
- Uses Django querysets with union operations for efficient cross-order-type queries
- Supports complex filtering with Q objects

### Frontend Technology
- Vanilla JavaScript (no external frameworks)
- CSS Grid and Flexbox for responsive layouts
- Custom dropdown and filtering components

## Troubleshooting

### Common Issues

1. **Performance issues**: Large datasets may require adjusted pagination or additional filtering

### Monitoring

Monitor plugin functionality through Canvas logs:
```bash
canvas logs order_tracking
```

## Version Compatibility

- Canvas SDK: 0.1.4+
- Python: 3.8+
- Canvas Instance: Compatible with current Canvas Medical platforms

