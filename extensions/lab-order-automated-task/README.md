# Automate Tasks Based on Lab Orders

## Description

When ordering labs, staff follow up is often necessary. You may want to alert phlebotomists that an order has been placed, or you may need to ensure the patient goes to their local patient service centers (PSC).

This plugin automates the creation of a task based on lab orders. It is a simple implementation that responds to all lab orders using the `LAB_ORDER_COMMAND__POST_COMMIT` event and creates a task titled **Follow up with patient regarding lab order**. The task is assigned to the staff member who committed the command.

The conditions that trigger the task, as well as task attributes (title, assignee, due date) can be updated to fit your specific lab workflows
