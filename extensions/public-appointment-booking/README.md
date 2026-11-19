public-appointment-booking
==========================

## What it does

Gives a practice a public booking page that people without a Canvas login can use. The page lists open slots for one note type. The visitor picks a time and enters their name, date of birth, email, phone and an optional reason.

- If the details match exactly one active patient (same name and date of birth, plus the same email or phone), the plugin books an **unconfirmed** appointment on that chart. It also creates a "Confirm online booking" task for staff.
- Otherwise it books nothing. It creates an "Online booking request (no matching patient)" task, so staff can register the person and then book the visit.

Both tasks carry the entered details as a comment, labelled `public-booking`. They go to a team if one is configured.

The visitor always sees the same reply: "Thanks. Your request has been received. The practice will contact you to confirm your appointment." Whether a patient matched is never revealed.

This is a **reference plugin**. Read the security model below before you adapt it.

## Routes

All routes live under `/plugin-io/api/public_appointment_booking/public/`:

| Method | Path | Returns |
|---|---|---|
| GET | `book` | The booking page (HTML) |
| GET | `slots` | `{"slots": [{provider_id, provider_name, start_iso, end_iso, location_name, duration_minutes}]}` |
| POST | `book` | `202 {"status": "received", "message": ...}` |

Every route answers `404 {"error": "not_found"}` until `PUBLIC_BOOKING_ENABLED` is `true`.

## Pre-conditions on the Canvas instance

Slot search is copied unchanged from `urgent-care-self-scheduler` (`slot_search.py`), so the setup is the same:

1. **A `NoteType`** with these settings:
   - `category = encounter`
   - `is_active`, `is_scheduleable` and `is_scheduleable_via_patient_portal` set to true
   - an `online_duration` (this is the slot length)
2. **For each bookable provider**, a `Clinic` calendar titled `"{Provider Name}: Clinic"` (or `"{Provider Name}: Clinic: {Location Name}"`). It needs availability events whose `allowed_note_types` include that note type.
3. **The provider holds a Provider role.** Rooms and other resources are filtered out.

## Secrets

| Secret | Default | Purpose |
|---|---|---|
| `PUBLIC_BOOKING_ENABLED` | off | Must be exactly `true` (any case) to turn the plugin on. Any other value leaves it off. |
| `PUBLIC_BOOKING_NOTE_TYPE_NAME` | none | Exact name of the note type above. If it is missing or can't be resolved, `slots` and `book` return 503. |
| `PUBLIC_BOOKING_LEAD_TIME_MINUTES` | 120 | Earliest bookable slot, in minutes from now. |
| `PUBLIC_BOOKING_WINDOW_DAYS` | 14 | How many days ahead to offer slots. Capped at 14, the plugin cache TTL ceiling, so a slot hold always outlives the slot. |
| `PUBLIC_BOOKING_TASK_TEAM_ID` | none | UUID of the team that receives the tasks. |
| `PUBLIC_BOOKING_ALLOWED_HOSTS` | none | Extra hostnames, comma-separated, allowed as `Origin` for POSTs. Use this if you serve the page from your own domain. |

```bash
canvas config set public_appointment_booking \
  PUBLIC_BOOKING_NOTE_TYPE_NAME="New patient visit" \
  PUBLIC_BOOKING_ENABLED=true --host <your-instance>
```

## Security model

The handler's `authenticate()` returns `True`: these routes are public on purpose. Protection comes from what each route does instead.

- **Off by default.** Every route returns 404 until the enabled secret is `true`.
- **No PHI out.** `slots` returns provider name, time and location name only. `book` returns one fixed body for both outcomes and never echoes input. Validation errors name the bad field but don't explain why.
- **No existence oracle.**
  - The response is the same whether or not a patient matched.
  - The requested slot is **held for both outcomes**, so the public slot list doesn't reveal it either.
  - An ambiguous match (more than one patient) books nothing.
- **Rate limits** (plugin cache, fixed window):
  - `slots`: 60 per client per 10 minutes.
  - `book`: 5 per client per hour, 3 per email per day, and 200 per instance per hour.
  - The instance-wide budget is charged only for well-formed requests, so junk POSTs can't lock out real bookings.
  - The client is the **last** `X-Forwarded-For` hop.
  - **Caveat:** a live test showed that a caller who sends their own `X-Forwarded-For` still lands in a separate bucket, so per-client limits can be dodged. The per-email and instance-wide limits are the real backstop. A trusted client IP from the platform would fix this.
  - Cache errors are not caught, so a broken cache fails closed.
- **CSRF / origin.**
  - POST needs `Content-Type: application/json`, which forces a CORS preflight from browsers.
  - If an `Origin` (or `Referer`) is present, its host must be one of these: the instance host (`<CUSTOMER_IDENTIFIER>.canvasmedical.com`), the forwarded host, or an entry in `PUBLIC_BOOKING_ALLOWED_HOSTS`.
  - Origin `null` is rejected. An Origin with no known hosts is rejected.
  - Requests with no Origin (curl, server-to-server) are allowed. Rate limits still apply.
- **Input validation.**
  - Body capped at 8 KB.
  - Names are letters, spaces, `'`, `-` and `.`, up to 60 characters.
  - Date of birth is ISO and in the past.
  - Phone must be 10 US digits. Email has a basic shape check.
  - `start_iso` must carry a timezone.
  - Reason is up to 300 characters with no control characters.
  - The chosen slot is re-checked server-side against the current open slots. It is then claimed with an add-if-absent cache write (`get_or_set`), so two requests racing for the same slot can't both book it. A taken slot returns 409.
- **The page.** Strict CSP (`default-src 'none'`, `connect-src 'self'`, `frame-ancestors 'self'`). Everything is rendered with `textContent`. Fetches use `credentials: "omit"`.

### Known limits

- The matched path emits one more effect than the unmatched path. The response is built before effects are applied, so the timing difference is small, but it is not zero.
- Rate limits are per process window and not atomic (the plugin cache has no increment), so a burst can go slightly over a limit.
- A requester who knows a patient's name, date of birth and email or phone can put an unconfirmed appointment on that chart. That is why the appointment is **unconfirmed** and a staff confirm task is always created.
- No CAPTCHA. Add one in front of the page if you see abuse.

## Tests

```bash
uv run --frozen pytest
```
