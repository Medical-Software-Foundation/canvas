# Note Template Button

## Description

For routine office visits, users can easily insert a note template with a click of button, saving providers time and streamline documentation.

In this extension, the button will only appear in the note header for Office visits and when the notes is empty. 

The note template will insert the following blank commands:
- Reason for Visit (RFV)
- History of Present Illness (HPI)
  - Insert with dynamic variables: "`PATIENT NAME` is a `AGE` year old `SEX` who presents today for"
- Review of Systems (ROS)
- Physical Exam
- Diagnose
- Plan

This useful and flexible extension is great starting point for organizations that want to customize this extension to their own use cases and workflows as it also contains sample code in the comments for how to do the following:
- Display the button based on a patient's diagnosis
- Default a Brief ROS instead of blank
- Default a Brief Physical exam instead of blank

## Installation

`canvas install note_template_button`



### Important Note!

The CANVAS_MANIFEST.json is used when installing your plugin. Please ensure it
gets updated if you add, remove, or rename protocols.
