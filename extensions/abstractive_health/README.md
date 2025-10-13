# Abstractive Health Plugin
The Abstractive Health Extension enables your organization to gain deep patient intelligence for your clinicians. You are able to access a patient's complete medical record from the national health information exchanges, see automated AI summaries from those documents, and get quick answers to any clinical questions on the patient chart with streamlined research.

## About Abstractive
An Abstractive account is required to access the platform. The application flow will prompt you to create one to register for a free trial, after which plans start at $99/month.

## Installation
To install the extension and populate the application in your Canvas instance, run the following CLI command:

`canvas install abstractive_health`

## Authentication
The application uses SMART on FHIR authentication, as described [here](https://docs.canvasmedical.com/guides/embedding-a-smart-on-fhir-application). You will need to complete a one time step to authorize the Abstractive Health extension by configuring OAuth credentials for it to use.

Navigate to <YOUR_CANVAS_URL>/auth/applications/register/ and fill in the following form values:

* Name: Abstractive Health Application (* can be any name)
* Client ID: `QthYrxa08pr9wg4QSWtOFJeSuDzsv6XRpeH1lWAL` (* must be an exact match)
* Client secret: <a secret lives here, do not change>
* Client type: Public
* Authorization grant type: Authorization code
* Redirect uris: https://app.abstractive.ai/
* Algorithm: RSA with SHA-2 256
