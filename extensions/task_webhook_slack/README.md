# Task Webhook Slack Integration

<img width="546" height="140" alt="image" src="https://github.com/user-attachments/assets/d1d195ea-87e5-4584-90b2-1d90a64b8b7b" />


## Description
Make integrations more efficient with webhooks. Webhooks are used to notify an application when an event occurs in another system, acting as a real-time communication channel and "push" information as soon as an event happens.

When a task in Canvas is created or updated, send a webhook playload to an endpoint of your choice.

The Canvas payload includes the following:

- Task: ID, event (updated, created), title, due date
- Patient: ID, first name, last name, date of birth, sex at birth
- Assignee: ID, first name, last name, team (if applicable)
- Task creator, ID, first name, last name
- Customize the event trigger and payload to fit your needs.

## Example
An example implemenation integrates Canvas task management with Slack notifications. When a task in Canvas is created or updated, it automatically sends a formatted message to a Slack channel via webhook, keeping your team informed in real-time.


### How It Works

When a task event occurs in Canvas, this extension:
1. Captures the task details and associated patient/assignee information
2. Formats the data into a Slack-friendly payload
3. Sends the notification to your configured Slack webhook URL

### Slack Setup

#### 1. Create a Slack App and Webhook
Reference: https://docs.slack.dev/messaging/sending-messages-using-incoming-webhooks/

1. Go to [api.slack.com/apps](https://api.slack.com/apps) and create a new app
2. Choose "From scratch" and give it a name like "Canvas Task Notifications"
3. Select your workspace
4. Go to "Incoming Webhooks" and activate them
5. Click "Add New Webhook to Workspace"
6. Choose the channel where you want task notifications
7. Copy the webhook URL (it will look like: `https://hooks.slack.com/services/T00000000/B00000000/XXXXXXXXXXXXXXXXXXXXXXXX`)

#### 2. Configure Canvas Extension

Set these plugin secrets in your Canvas environment:

- `WEBHOOK_NOTIFICATION_URL`: Your Slack webhook URL
- `AUTH_TOKEN`: Leave empty (Slack webhooks don't require bearer tokens)

### Payload Structure

The webhook sends the following data to Slack:

```json
{
  "task_id": "12345",
  "event": "created", // or "updated"
  "title": "Follow up with patient",
  "due_date": "2024-01-15T10:00:00Z",
  "patient": {
    "id": "67890",
    "first_name": "John",
    "last_name": "Doe",
    "birth_date": "1980-05-15",
    "sex_at_birth": "Male"
  },
  "creator": {
    "id": "11111",
    "first_name": "Dr. Jane",
    "last_name": "Smith"
  },
  "assignee": {
    "staff": {
      "id": "22222",
      "first_name": "Nurse",
      "last_name": "Johnson"
    },
    "team": null
  }
}
```

### Example Slack Message

When a task is created, you'll see a message like:

**📋 New Task Created**

- **Title:** Follow up with patient
- **Due:** January 15, 2024 at 10:00 AM
- **Patient:** John Doe (DOB: 05/15/1980, Male)
- **Created by:** Dr. Jane Smith
- **Assigned to:** Nurse Johnson

## Customization

You can customize the webhook payload format by modifying the `task_webhook_notification.py` file to match your specific Slack integration needs.
