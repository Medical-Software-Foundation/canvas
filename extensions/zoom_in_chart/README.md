zoom_in_chart
===================

## Description

This plugin adds an action button to a note when an appointment is a telehealth visit that is set up with a Zoom meeting. The action button will launch the Zoom telehealth visit directly in the right hand pane of the browswer in the patient's chart (rather than opening in the Zoom desktop app). This plugin uses the [Zoom Meeting SDK for web](https://developers.zoom.us/docs/meeting-sdk/web/) to integrate the meeting directly into the browser.

### Setup

The Zoom SDK requires that an application is registered in able to use the features in a browser. The Zoom account used must either hold the `Owner` or `Admin` role in order to create an application. For our purposes here, we are setting up a Zoom application in Development mode.

#### Set up a Zoom application

1. Log in to your the Zoom app marketplace with your Zoom credentials [here](https://marketplace.zoom.us/).
2. In the top right-hand side of the page, select _Develop_ and the _Build App_.
3. In the popup for the app type, select _General App_.
4. How the app is managed will depend on the use case and how many users will be using the app. For initial setup, select _User-managed_ for this option.
5. Copy the app's _Client ID_ and _Client Secret_. You will need these later.

### Installing the plugin

1. Install the plugin with the following Canvas SDK command, replacing `hostname` with your selected environment:

```
canvas install zoom_in_chart --host <hostname>
```

2. In the Canvas instance, navigate to Settings > Plugin_IO > Plugins.
3. Click on the _zoom\_in\_chart_ plugin.
4. Under _Plugin Secrets_, paste the Client ID and Client Secret from the Zoom app into `ZOOM_CLIENT_ID` and `ZOOM_CLIENT_SECRET`, respectively.

### Using the plugin

1. Navigate to a patient's chart that has an upcoming telehealth appointment that is set up with a Zoom link (`Appointment.meeting_link`).
2. The plugin should show the `Launch Meeting` action button underneath the Note header.
3. Click the `Launch Meeting` button. The Zoom meeting will open in the side pane on the right hand side of the chart, where you can click _Join_.
4. To end the meeting, click the `End` button in the Zoom controls.