## Description

This plugin automates the creation of a task based on lab orders. It responds to `LAB_ORDER_COMMAND__POST_COMMIT` and creates a task titled **Follow up with patient regarding lab order**. The task is assigned to the staff member who committed the command.
