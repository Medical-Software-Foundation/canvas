# Unsigned Note Reminder

Creates follow-up tasks for notes that remain unsigned past a configurable threshold. Runs daily at 6pm UTC and assigns reminder tasks to the note's provider.

## Behavior

1. Finds notes that are **not locked** (unsigned) and older than the threshold (default: 48 hours)
2. Skips notes without an assigned provider
3. Checks for existing open reminder tasks to avoid duplicates
4. Creates a task assigned to the provider: *"Sign note for [Patient Name] from [Date]"*

## Configuration

| Secret | Default | Description |
|--------|---------|-------------|
| `THRESHOLD_HOURS` | `48` | Hours before a note is considered overdue for signing |
| `NOTE_TYPES` | *(empty = all)* | Comma-separated note type names to filter |

## Installation

```bash
canvas install unsigned-note-reminder --host <instance>
```

After installation, configure secrets in the plugin admin page.
