abstractive_health
==================

### Important Note!

The CANVAS_MANIFEST.json is used when installing your plugin. Please ensure it
gets updated if you add, remove, or rename protocols.

# How to enable the Canvas Medical SMART on FHIR app of Abstractive on a customer site:
1. Access the registration form for a token at the following canvas site: https://{customer-initials}.canvasmedical.com/login?next=/auth/applications/register/
2. Create a token for SMART on FHIR app with the following:
    - Client Type: Public
    - Authorization grant type: Authorization code
    - Algorithm: RSA with SHA-2 256
3. Create a second token so you can push the changes to the app, you need to set it to the following
    - Client Type: Public
    - Authorization grant type: client credentials
    - Algorithm: RSA with SHA-2 256
4. Add both host names with the client ID and client secret in the folder ~.canvas\credentials.ini (Note: the folder and file might need to be saved in your HOME directory to enable the next step. e.g. `C:\Users\vince\.canvas\credentials.ini`)
5. Push the app to the client with `canvas install .\abstractive_health --host {host-name}`
6. Set the app to active with `canvas enable abstractive_health --host {host-name}`