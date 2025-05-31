# Task Webook Notification

## Description

When a task in Canvas is ceated or updated, send a webhook playload to an endpoint of your choice.

The payload includes the following:
- Task: ID, event (updated, created), title, due date
- Patient: ID, first name, last name, date of birth, sex at birth
- Assignee: ID, first name, last name, team (if applicable)
- Task creator, ID, first name, last name

Customize the event trigger and payload to fit your needs.

### Important Note!

There are two plugin secrets to set:
- `WEBHOOD_NOTIFICATION_URL`: Webhook URL
- `AUTH_TOKEN`: If webhook requires bearer token authentication
