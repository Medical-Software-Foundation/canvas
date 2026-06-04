# External Calendar Busy Blocks

Subscribe Canvas to a provider's personal calendar (Google Calendar, Outlook, Apple iCloud) via the calendar's secret iCal/ICS URL. Every 15 minutes, the plugin fetches each connected feed and writes the busy times as "Busy" events on the provider's Canvas Admin calendar.

## How it works

Each provider opens the **Calendar Busy Blocks** application from the Canvas global menu, pastes their personal calendar's secret iCal URL, and clicks Save. A scheduled task runs every 15 minutes:

1. Fetches each provider's ICS feed (sending `If-None-Match` / `If-Modified-Since` so unchanged feeds return `304 Not Modified` and skip work).
2. Parses the feed, filters to confirmed busy events, expands recurring events within a 90-day window, and converts everything to UTC.
3. Diffs the parsed events against the events the plugin previously imported and emits `Event.create`, `Event.update`, or `Event.delete` effects.

Canvas users see only "Busy" — the original event titles never leave the personal calendar.

## Configuration

| Plugin secret | Default | Notes |
|---|---|---|
| `LOOKAHEAD_DAYS` | `90` | How far in advance to expand recurring events. |

## Privacy & security

- The secret ICS URL **is** a bearer token. Store it as the provider's personal calendar's *secret* iCal URL, not a shared one.
- The plugin imports only event start/end times. Titles, descriptions, and attendees are discarded.
- URLs are never logged in full — tokens are redacted.

## Limitations

- Tentative events (`STATUS=TENTATIVE`) and transparent events (`TRANSP=TRANSPARENT`) are not imported.
- Recurring events use a subset of RFC 5545: `FREQ=DAILY|WEEKLY|MONTHLY|YEARLY` with `INTERVAL`, `BYDAY`, `BYMONTHDAY`, `BYMONTH`, `UNTIL`, `COUNT`, `EXDATE`, `RECURRENCE-ID`. Unsupported rule features (`BYSETPOS`, `BYWEEKNO`, `BYYEARDAY`, a non-default `WKST` other than `MO`, sub-daily `BY*`) cause the VEVENT to be dropped with a warning log. `WKST=MO` (the default the expander assumes) is accepted.
- One feed per provider in v1.
- Source-side lag dominates: Google and Outlook regenerate their public ICS feeds on a 30–60 min cycle; Canvas-side polling is 15 min.
- **Supported hosts are allowlisted to known calendar providers** — Google (`*.google.com`), Outlook/Office 365 (`*.outlook.com`, `*.office365.com`, `*.live.com`), and Apple iCloud (`*.icloud.com`). Self-hosted ICS feeds (Nextcloud, Fastmail, etc.) are not supported in v1. This is a deliberate SSRF mitigation: the cron fetches feed URLs server-side from Canvas's network, and the plugin sandbox does not permit the DNS/IP inspection that would otherwise let us safely allow arbitrary hosts. Note that because the SDK HTTP client does not expose redirect control, the allowlist trusts that these providers do not redirect feed requests to internal addresses.
