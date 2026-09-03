# Appointment No-Show Task Plugin

## Description

This plugin automatically creates a task when a user marks an appointment as "no show". The task reminds the team to reach out to the patient and reschedule the appointment.

## How It Works

1. When an appointment is marked as "no-show" (via `APPOINTMENT_NO_SHOWED` event)
2. The plugin automatically creates a task with:
   - Title: "Reschedule no-show appointment for [Patient Name]"
   - Assignment: Team specified in plugin secrets
   - Labels: Labels specified in plugin secrets
   - Patient context: Linked to the patient who no-showed


## Configuration

### Plugin Secrets Configuration

The plugin uses secrets to allow admins to configure behavior without modifying code.

#### TEAM_NAME (Required)

Specifies which team should receive no-show tasks.

**Configuration:**
1. In the Canvas admin interface, navigate to the plugin settings
2. Set the `TEAM_NAME` secret to the exact name of your team
   - Example: `"Admin"`, `"Scheduling"`, `"Front Desk"`, etc.
3. Ensure the team name matches exactly (case-sensitive) with a team that exists in Canvas

**Note:** If the `TEAM_NAME` secret is not configured or the team doesn't exist, tasks will still be created but without team assignment.

#### LABELS (Optional)

Specifies comma-separated labels to apply to created tasks.

**Configuration:**
- Set the `LABELS` secret to a comma-separated list of labels
- Default value if not configured: `"no-show,reschedule"`
- Examples:
  - `"no-show,reschedule"` - Default labels
  - `"no-show,urgent,follow-up"` - Custom labels
  - `"patient-no-show"` - Single label

**Example SECRETS.json:**
```json
{
  "TEAM_NAME": "Admin",
  "LABELS": "no-show,reschedule"
}
```

### Advanced Customization (Optional)

For further customization beyond what secrets provide, you can modify the protocol code in [no_show_creates_task.py](protocols/no_show_creates_task.py):

- **Task title**: Modify line 96 to change the title format
  ```python
  task_title = f"Reschedule no-show appointment for {patient_name}"
  ```
- **Due date**: Add a `due` parameter to the `AddTask` call (requires `import arrow`)
  ```python
  effect = AddTask(
      patient_id=patient_id,
      title=task_title,
      team_id=team_id,
      labels=labels,
      due=arrow.now().shift(hours=24).datetime,  # Due in 24 hours
  )
  ```


## Important Note

The CANVAS_MANIFEST.json is used when installing your plugin. Please ensure it gets updated if you add, remove, or rename protocols.

## Troubleshooting

### Tasks not being created

1. Verify the plugin is installed and enabled in Canvas
2. Check the plugin logs for error messages (look for lines starting with `NoShowCreatesTask:`)
3. Ensure you're marking the appointment as "no-show" (not just cancelling it)

### Tasks created without team assignment

This happens when:
- The `TEAM_NAME` secret is not configured
- The team name in the secret doesn't match an existing team (case-sensitive)
- The team was deleted after configuration

**To fix:**
1. Check your plugin secrets configuration in Canvas admin
2. Verify the `TEAM_NAME` value matches an existing team exactly
3. Check the logs to see what team name the plugin is looking for

### Viewing plugin logs

Plugin logs will show detailed information about each no-show event:
```
NoShowCreatesTask: Event received - Type: 7
NoShowCreatesTask: Event name: APPOINTMENT_NO_SHOWED
NoShowCreatesTask: Extracted appointment ID: <uuid>
NoShowCreatesTask: Found appointment with status: 'no-show'
NoShowCreatesTask: Task will be assigned to team 'Admin' (ID: <team-id>)
NoShowCreatesTask: Creating task for patient <patient-id>
```
