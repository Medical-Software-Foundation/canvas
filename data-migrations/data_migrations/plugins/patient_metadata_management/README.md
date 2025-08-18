patient_metadata_management
===========================

## Description

Managing Patient's Custom Metadata. 

1. Ability to control what metadata fields appear in the Patient's Profile in the Canvas UI
2. SimpleAPI endpoint for updating a patient's metadata key or a list of keys


### Important Note!

When installing there is a plugin secret to create a `simpleapi-api-key`. 
To create a key to use, here is some helpful code: `python -c "import secrets; print(secrets.token_hex(16))"`


Example Payloads 

1. Upsert example to update one metadata key for a patient
```python

import requests

url = "http://example.canvasmedical.com/plugin-io/api/patient_metadata_management/upsert"

payload = {
    "patient": "118c102a1c594c24a3509c5f14e01db7",
    "key": "intake_form_complete",
    "value": ""
}
headers = {
    "authorization": "e50d319f7bec5563c02e958b9977719b",
    "content-type": "application/json"
}

response = requests.post(url, json=payload, headers=headers)

print(response.json())
```

2. Bulk upsert example to update a list of metadata for a patient 

```python
import requests

url = "http://example.canvasmedical.com/plugin-io/api/patient_metadata_management/bulk_upsert"

payload = {
    "patient": "118c102a1c594c24a3509c5f14e01db7",
    "metadata": [
        {
            "key": "other_legal_names",
            "value": "Smith"
        },
        {
            "key": "marital_status",
            "value": "Unknown"
        },
        {
            "key": "intake_form_complete",
            "value": "2023-02-01"
        }
    ]
}
headers = {
    "authorization": "e50d319f7bec5563c02e958b9977719b",
    "content-type": "application/json"
}

response = requests.post(url, json=payload, headers=headers)

print(response.json())
```