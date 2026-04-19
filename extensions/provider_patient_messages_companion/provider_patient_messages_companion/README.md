# provider_patient_messages_companion

A mobile-friendly messaging surface that lets the logged-in provider read and reply to every patient on their panel, with live WebSocket updates.

## What providers see

An icon titled **My Messages** appears in the provider companion launcher. Tapping it opens a modal with:

- A header showing the title **My Messages**, a subtitle with the panel size (e.g., "42 patients on your panel"), and a live-status pill ("Live" when connected; "Reconnecting…" if the WebSocket drops).
- A scrollable list of patient threads, one card per patient on the provider's active care-team panel, sorted alphabetically by last name, then first name.

Each thread card shows:

- The patient's name as a link that leaves the modal to open their patient companion page.
- A preview of the most recent message (with a "You:" prefix if the provider sent it) and a relative timestamp ("now", "15m", "3h", "2d", or a date for older).
- A teal unread badge in the top-right with the count of inbound messages that haven't been read yet. Threads with no unread messages show no badge.
- A chevron that rotates 180° when the card is expanded.

## How to use it

### Reading a thread

Tap any thread card to expand it. The drawer reveals the message history (oldest at top, newest at bottom; paginated to the most recent 100). Inbound messages from the patient appear as light gray bubbles on the left; your outbound messages appear as teal bubbles on the right. Each bubble has a small timestamp.

Tapping an expanded card also auto-marks any unread inbound messages in that thread as read — the unread badge clears immediately on the UI side, and the server records the read timestamp on each inbound message.

Tap the card header again (outside the conversation drawer) to collapse it.

### Sending a message

In an expanded thread, type into the composer at the bottom and tap **Send**. Your message appears immediately in the conversation as an optimistic teal bubble, and the server processes the send asynchronously. If the send fails, the optimistic bubble is removed and an error is surfaced.

### Live updates

While the modal is open, the plugin holds a WebSocket to the Canvas platform. When anyone sends a new message that involves the logged-in provider and a patient on their panel — whether the patient replies, the provider sends from another surface, or the conversation updates from elsewhere — the thread list refreshes within a second. The live-status pill reflects the WebSocket state.

### Attachments

Attachments are currently not supported on the provider send side. Patients can include attachments from their portal; those appear in the conversation via the Canvas message machinery. A later revision will add provider-side attachment uploads once the SDK exposes that capability.

## Installation

No environment variables or secrets are required.

```sh
canvas install --host <host> \
    ~/src/plugin-development/msf-canvas/extensions/provider_patient_messages_companion/provider_patient_messages_companion
```

After install, the plugin registers itself against the `provider_companion_global` scope and will appear in the provider companion launcher on next page load.

Panel membership is driven by `CareTeamMembership` rows with `status=active`. Configure care-team memberships in your instance to control which patients appear here.

---

## For developers

### Scope

This plugin uses the `provider_companion_global` `ApplicationScope` — it surfaces on the provider companion main page and does not receive patient or note context.

### Architecture

```
provider_patient_messages_companion/
├── CANVAS_MANIFEST.json               # scope: provider_companion_global; 3 handlers registered
├── README.md                          # this file
├── LICENSE                            # MIT
├── applications/
│   └── messages_app.py                # Application subclass; on_open → LaunchModalEffect
├── handlers/
│   ├── messages_api.py                # HTTP SimpleAPI: shell, threads, conversation, send, mark-read
│   ├── messages_websocket.py          # WebSocketAPI: accepts channel = "staff-<caller uuid>"
│   └── new_message_notifier.py        # BaseHandler on MESSAGE_CREATED → Broadcast to staff channel
├── static/
│   ├── index.html                     # SPA shell (header, live indicator, thread list slot)
│   ├── main.js                        # vanilla JS; fetch + WebSocket client
│   └── styles.css                     # teal accent, chat bubble styling
└── assets/
    ├── icon.png                       # 256×256 launcher icon
    └── messages-teal-icon.svg         # source SVG for the icon
```

### Realtime architecture

1. On modal open, the HTTP shell endpoint (`GET /`) renders `index.html` with a computed `ws_url` of the form `/plugin-io/ws/provider_patient_messages_companion/staff-<staff_uuid>`. The server sets this based on the `canvas-logged-in-user-id` header.
2. `main.js` opens a WebSocket to that URL. The path's `channel_name` segment is `staff-<staff_uuid>`.
3. The platform fires `SIMPLE_API_WEBSOCKET_AUTHENTICATE` at `PatientMessagesWebSocket.authenticate()`, which accepts only if:
   - the session is `type == "Staff"`, and
   - `self.websocket.channel == f"staff-{self.websocket.logged_in_user['id']}"`.
   This enforces "you can only subscribe to your own channel."
4. Anywhere in Canvas, a `MESSAGE_CREATED` event fires when a Message record is created. `NewMessageNotifier` (a `BaseHandler` subscribed to that event) loads the message, identifies which side is Staff and which is Patient, and emits a `Broadcast(channel=f"staff-{staff.id}", message={type: "new_message", patient_id, message_id})` effect.
5. The client receives the broadcast, re-fetches `/threads`, and repaints. If the affected thread is currently expanded, its conversation is re-fetched as well.

There is no per-connection registry or custom-data namespace. The channel name is deterministic on both sides (`staff-<uuid>`), which is also how the broadcast handler knows where to push without any lookup.

### Data access

All reads; sends and mark-read go through SDK effects (no direct ORM writes).

- **Panel**: `CareTeamMembership.objects.filter(staff__id=<uuid>, status="active").select_related("patient")` — ordered, de-duplicated.
- **Thread latest message**: `Message.objects.filter(Q(sender__patient__id__in=<panel>, recipient__staff__id=<staff>) | Q(sender__staff__id=<staff>, recipient__patient__id__in=<panel>)).annotate(thread_patient_id=Case(...)).order_by("thread_patient_id", "-created").distinct("thread_patient_id")`. Postgres-native `DISTINCT ON` bounds the result size to one row per panel patient, independent of message volume.
- **Unread counts**: one `Message.objects.filter(recipient__staff__id=<staff>, sender__patient__id__in=<panel>, read__isnull=True).values_list("sender__patient__id").annotate(Count("id"))`.
- **Conversation**: `Message.objects.filter(Q(sender__patient__id=<id>, recipient__staff__id=<staff>) | Q(sender__staff__id=<staff>, recipient__patient__id=<id>)).select_related(...).order_by("-created")[:limit]`. Defaults to 100 messages, max 200 per fetch; supports `?before=<iso>` for paging older messages.
- **Send**: `canvas_sdk.effects.note.message.Message(sender_id=<staff_uuid>, recipient_id=<patient_uuid>, content=...).create_and_send()`.
- **Mark read**: for each inbound unread, an `EDIT_MESSAGE` effect with `read=<now>` and the existing content (unchanged).

Total DB round-trips for the thread list: **3** (memberships, `DISTINCT ON`, unread counts) — regardless of panel size.

### Auth

- HTTP endpoints: `StaffSessionAuthMixin` rejects non-staff sessions with `InvalidCredentialsError`.
- WebSocket: custom `authenticate()` that verifies the session is staff AND the URL-chosen channel name matches `staff-<caller uuid>`.
- All patient-scoped endpoints re-verify that the patient is on the caller's panel before returning data or emitting effects (no reliance on the front-end filtering).

### Endpoints

All HTTP endpoints mounted under `/plugin-io/api/provider_patient_messages_companion/app/`.

| Method & path | Purpose |
|---|---|
| `GET /` | HTML shell, with `ws_url` and `cache_bust` template vars |
| `GET /threads` | JSON: `{threads: [{patient_id, patient_name, last_message, unread_count}]}` |
| `GET /threads/<patient_id>/messages?limit=&before=` | JSON: `{messages: [{id, content, sent_by_me, created, read}]}`; limit defaults to 100, max 200; `before` is ISO-8601 |
| `POST /threads/<patient_id>/messages` | body `{content}`; emits `create_and_send()`; returns 202 with `{pending: {content, sent_by_me:true}}` |
| `POST /threads/<patient_id>/mark-read` | emits `EDIT_MESSAGE` per unread inbound; returns `{marked: N}` |
| `GET /main.js`, `GET /styles.css` | served static assets (cache-busted) |

WebSocket URL: `/plugin-io/ws/provider_patient_messages_companion/staff-<staff_uuid>`.

### Known considerations

- **Live refresh granularity**: on a broadcast, the client refetches the full thread list (`/threads`). For very large panels this could be optimized to refetch just the one thread's latest message, but the thread-list query is already 3 round-trips and scales with panel size, not message volume.
- **Patient-first sender for reads**: "mark-read" sets `read=<now>` via `EDIT_MESSAGE` effects. The effect's `Message` class requires `sender_id` and `recipient_id` to be provided even on edit; we pass the Patient and Staff UUIDs respectively and re-submit the message's existing `content` unchanged to satisfy the effect schema.
- **No attachments on send**: patients can attach via their portal (handled by Canvas's message machinery); providers cannot send attachments here. A follow-up can add provider-side attachments once the SDK exposes that surface.
- **Notifier breadth**: `NewMessageNotifier` fires on every `MESSAGE_CREATED` event and emits at most one `Broadcast` per message. Messages that are staff↔staff or patient↔patient are silently skipped.

## Testing

```sh
cd ~/src/canvas-plugins && uv run pytest \
    ~/src/plugin-development/msf-canvas/extensions/provider_patient_messages_companion/tests \
    --cov=provider_patient_messages_companion --cov-branch --cov-report=term-missing
```

Target: 100% statement + branch coverage.

## License

MIT. See [LICENSE](./LICENSE).
