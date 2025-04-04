ical Calendar Subscriptions
====

## Description

This allows users to subscribe to their appointments in the calendar program
of their choice. Patient and appointment details are not shared. The calendar
events contain location, provider name, provider email, appointment type,
appointment status, start time, and duration.

You can subscribe to your own calendar, or a location's calendar.

## Configuration and Use

Once installed, set the plugin secret
`CALENDAR_LINK_SALT__EXISTING_LINKS_BECOME_INVALID_IF_CHANGED`.

As the name implies, if you modify this secret, users will no longer receive
updates in their calendars, and will have to manually remove the
non-functional subscription and resubscribe using the new link.

Here's a handy command to generate a good value for the plugin secret:

```bash
python -c "import secrets; print(secrets.token_hex(32))"
```

Once configured, logged in users can find their calendar links at
`<your-canvas-url>/plugin-io/api/ical/calendars`. They must be logged in prior
to visiting that link. They can also click the "Calendar Links" application
from the schedule page.
