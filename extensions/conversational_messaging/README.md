Conversational Messaging
========================

## Description

This plugin adds a "Conversational Messaging" application to Canvas that opens in the right chart pane for the current patient. The experience consolidates inbound and outbound messages so staff can read and respond without leaving the chart.

## Installation

```
canvas install conversational_messaging
```

### Key Capabilities
- **Unified timeline:** pulls both practitioner- and patient-authored messages and renders them as chat bubbles with timestamps and sender context.
- **Send workflow:** includes a simple composer for staff to send secure messages directly to the patient; submissions post through the plugin’s SimpleAPI endpoint and immediately refresh the thread.
- **Unread awareness:** highlights the oldest unread patient message and includes a "Mark All as Read" control that updates message state via the API.
- **Live updates:** listens on the messaging websocket channel so new activity (patient replies or other staff messages) appears without a page reload.
- **Pagination:** fetches the newest messages first and lets users load older batches in place, preserving scroll position for long conversations.

## Current limitations/caveats
1. Messages on the timeline view are not automatically filtered from view. Users can filter messages from the timeline view, but the filter may reset under certain conditions, e.g. adding a new note that is not part of the current filter view.
2. Unable to display message attachments. A message will appear to let the user know of attachments contained in the specific message, but they will be directed to the timeline view to see the attachments.
3. Providers unable to add message attachments (not currently supported today without the view)
4. No alert notification or badge when new message

## Configuration

- `simpleapi-api-key` (secret): API key used by the plugin to authenticate outbound SimpleAPI requests (e.g., broadcasting message creation events).
- `MESSAGING_CONVERSATION_PAGE_LIMIT` (secret): optional override for the number of messages fetched per page. Defaults to `20` when unset or invalid. Maximum enforced value is `200`.
  
<img width="2005" height="1167" alt="image" src="https://github.com/user-attachments/assets/9f86c7ba-610c-44a0-a681-e72506231b3c" />
