On-Demand Provider Queue adds a **Provider Queue** screen to Canvas: a live waiting room for on-demand visits. An outside system (a scheduling site, a triage form) sends visit requests to the plugin, and providers work them from one board.

- Each request shows the patient, reason for visit and priority (routine, urgent or emergent).
- A provider claims a request, or staff assign one, then chooses **Start Visit**. The patient's chart opens and a new note is created.
- A visit can be paused and resumed. When the provider locks the note, the entry moves to **Completed** by itself.
- The board updates live for everyone watching, and re-checks every 30 seconds and after every reconnect.
- Requests are accepted only from systems that hold the practice's API key. The board is for signed-in staff only.
- The queue is kept in Canvas, one record per request, so two providers can't claim the same patient. No AWS account is needed.

Good to know:

- Requests come in through the plugin's web address, so something on the practice's side has to send them. Canvas does not create them.
- Notes are created with the note type and location the practice picks in the settings.
- The plugin is off until `QUEUE_ENABLED` is set to `true`.
