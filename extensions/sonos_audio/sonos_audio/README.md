# Sonos Audio

Control [Sonos](https://www.sonos.com/) speakers from inside Canvas. Map speakers
to your practice locations, manage reusable ambient-music presets, play / pause /
adjust volume per location, and set recurring playback schedules — all from a
single staff-facing app.

## What it does

- **In-app Connect Sonos** — a one-click OAuth handshake stores the refresh token
  on an org-wide credential record. No copy-pasting tokens.
- **Speaker mapping** — link each Sonos player/group to a Canvas practice
  location. One speaker per location.
- **Presets** — name a Sonos favorite + volume as a reusable "station." Mark one
  as the global default, or bind a preset to a specific location.
- **Manual control** — play, pause, and set volume per location. The last station
  and volume played in a location become its remembered default.
- **Schedules** — recurring playback windows (e.g. *Waiting Room, Mon–Fri,
  09:00–17:00, Ocean Waves*). A once-a-minute cron handler starts and stops them.
- **Activity log** — an append-only audit trail of every play / pause / volume
  change, manual or scheduled, including errors.

The plugin runs in **demo mode** until you connect a Sonos household, so you can
explore the full UI (with sample speakers and stations) before wiring up real
credentials.

## Problem it solves

Clinics that use Sonos for ambient music in waiting rooms and exam areas normally
manage it from the Sonos mobile app on a separate device, disconnected from the
clinical workflow. Front-desk and clinical staff have no in-Canvas way to start
calming music for a room, pause it, adjust volume, or keep music on a consistent
daily schedule. This plugin brings that control into Canvas, tied to the practice
locations staff already work with, so audio management is one click away from the
EHR and runs on a schedule without anyone remembering to press play.

## Who it's for

Practices that run Sonos speakers across one or more locations and want staff to
manage ambient audio from within Canvas — front-desk staff starting/stopping
music per room, and operations staff configuring per-location stations and
recurring playback schedules. No Sonos hardware is required to evaluate it: demo
mode exercises the full UI with sample data.

## How to install

1. **Create a Sonos developer app.** In the
   [Sonos developer portal](https://developer.sonos.com/), create a *Control
   Integration*. Set its redirect URI to:

   ```
   https://<your-instance>.canvasmedical.com/plugin-io/api/sonos_audio/sonos/oauth/callback
   ```

   The exact URI for your instance is shown in the app's connection banner.

2. **Add the app keys as plugin secrets** (Settings → Plugins → `sonos_audio` →
   Secrets):

   | Secret | Value |
   | --- | --- |
   | `SONOS_CLIENT_ID` | Your Sonos app's Key |
   | `SONOS_CLIENT_SECRET` | Your Sonos app's Secret |

3. **Connect** — open the Sonos Audio app and click **Connect Sonos**. Approve
   access in the popup; the household is detected automatically.

4. **Map speakers** to your practice locations, then play.

## Configuration options

**Secrets** (required to leave demo mode):

| Secret | Purpose |
| --- | --- |
| `SONOS_CLIENT_ID` | Sonos developer app Key |
| `SONOS_CLIENT_SECRET` | Sonos developer app Secret |

**Presets** — create named stations (a Sonos favorite + volume) in the app. Set a
global default (`match_type = default`) or bind a preset to a location
(`match_type = location`). Higher `priority` wins when several presets match.

**Schedules and time zones** — schedule start/stop times are wall-clock `HH:MM`
values interpreted in the schedule's own UTC offset (set per schedule in minutes
— e.g. `-420` for US Pacific Daylight Time, `-300` for US Eastern Daylight Time,
`0` for UTC). The plugin needs no time-zone database; pick the offset that matches
the location. Note that fixed offsets do not auto-adjust for daylight saving —
update the offset when DST changes if you need exact local time year-round.

## Screenshots or screen recordings

> _TODO: add at least one screenshot of the Sonos Audio app (e.g. the speaker
> mapping / playback view) to `assets/` and embed it here, for example:_
>
> `![Sonos Audio — playback controls](../assets/screenshot-playback.png)`

## Components

| Component | Class | Purpose |
| --- | --- | --- |
| Application | `applications.sonos_app:SonosApp` | The staff-facing UI (full-page modal). |
| Protocol (SimpleAPI) | `applications.sonos_app:SonosApi` | REST API for OAuth, mapping, presets, playback, schedules. |
| Protocol (CronTask) | `handlers.scheduler:PlaybackScheduler` | Runs every minute to start/stop scheduled playback. |

## Custom data models

`SonosSpeaker`, `AudioPreset`, `SonosOAuthCredential`, `PlaybackSchedule`, and
`SonosPlaybackLog` (namespace `sonos__audio`).

## Tests

```
pytest extensions/sonos_audio/tests
```

The tests cover the Sonos API client, the OAuth result page, the application's
launch effect, the scheduler (decision logic and the cron tick), the SimpleAPI
endpoints, and the custom data models.
