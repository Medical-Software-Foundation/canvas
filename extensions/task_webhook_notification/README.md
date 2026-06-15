# Task Webook Notification

## Description

Make integrations more efficient with webhooks. Webhooks are used to notify an application when an event occurs in another system, acting as a real-time communication channel and "push" information as soon as an event happens.

When a task in Canvas is created or updated, send a webhook playload to an endpoint of your choice.

The payload includes the following:
- Task: ID, event (updated, created), title, due date
- Patient: ID, first name, last name, date of birth, sex at birth
- Assignee: ID, first name, last name, team (if applicable)
- Task creator, ID, first name, last name

Customize the event trigger and payload to fit your needs.

## Who it's for

Engineering and operations teams who integrate Canvas with an external system - a ticketing tool, a notification service, or a custom workflow app - and need it to react the moment a task is created or updated rather than polling for changes.

## How to install

```
canvas install task_webhook_notification
```

Set the required secrets before use (see Configuration).

### Important Note!

There are two plugin secrets to set:
- `WEBHOOD_NOTIFICATION_URL`: Webhook URL
- `AUTH_TOKEN`: If webhook requires bearer token authentication
