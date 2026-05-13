# Voice Dictation

Voice dictation for HPI and Plan commands in Canvas using ElevenLabs speech-to-text.

## Features

- **Dictate tab** appears in every note as a NoteApplication
- **HPI / Plan selector** — choose which command type to create
- **Scribe-style recording controls** — Record, Pause, Resume, Finish (2-click confirm)
- **Audio level visualization** — recording dot pulses with voice activity
- **Silence detection** — warning after 7.5s of no audio detected
- **ElevenLabs Scribe v1** batch transcription
- **Editable transcript** — review and modify text before adding to note
- **Command origination** — creates HPI or Plan command in the note

## Triggers

- `APPLICATION__ON_GET` — shows the Dictate tab in notes
- `APPLICATION__ON_OPEN` — loads the recording UI when tab is selected
- `SIMPLE_API_AUTHENTICATE` / `SIMPLE_API_REQUEST` — serves UI and handles API calls

## Effects

- `SHOW_APPLICATION` — registers the Dictate tab
- `LAUNCH_MODAL` (target: NOTE) — renders recording UI in the tab
- `ORIGINATE_HPI_COMMAND` — creates HPI command from transcript
- `ORIGINATE_PLAN_COMMAND` — creates Plan command from transcript

## Configuration

Set the following secret after installing:

- `ELEVENLABS_API_KEY` — Your ElevenLabs API key (get one at https://elevenlabs.io)

## Installation

```bash
canvas install voice_dictation --host <your-instance>
canvas config set voice_dictation ELEVENLABS_API_KEY=<your-key> --host <your-instance>
```
