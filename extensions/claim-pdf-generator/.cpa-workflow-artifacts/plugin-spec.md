# Plugin Specification: Claim PDF Generator

## Problem Statement
Staff and external billing systems need to generate superbill and CMS-1500 (HCFA) PDF forms from Canvas claim data. There is currently no built-in way to produce these standard billing documents on demand.

## Solution Overview
A SimpleAPI plugin that exposes two GET endpoints — one for superbills and one for CMS-1500 forms. Each endpoint accepts a `claim_id`, queries the full claim data tree via SDK models, renders an HTML template, converts it to PDF via `pdf_generator.from_html()`, and returns either a JSON response with the presigned PDF URL or the raw PDF bytes depending on a query parameter.

## Functional Requirements

### Endpoints

| Route | Method | Description |
|---|---|---|
| `/superbill/<claim_id>` | GET | Generate a superbill PDF for the given claim |
| `/hcfa/<claim_id>` | GET | Generate a CMS-1500 (HCFA) PDF for the given claim |

### Authentication
- API key authentication via `Authorization` header
- Secret name: `api-key`

### Query Parameters
| Param | Values | Default | Description |
|---|---|---|---|
| `format` | `url`, `pdf` | `url` | `url` returns JSON with presigned S3 URL; `pdf` returns raw PDF bytes |

### Response Formats

**`format=url` (default)**
```json
{
  "pdf_url": "https://s3.amazonaws.com/...",
  "claim_id": "abc-123",
  "form_type": "superbill"
}
```

**`format=pdf`**
Returns `application/pdf` content type with raw PDF bytes fetched from the presigned URL.

### Error Responses
```json
{"error": "Claim not found"}  // 404
{"error": "PDF generation failed"}  // 500
```

## Technical Design

### Handler Class
Single `SimpleAPI` handler with `PREFIX = "/claim-forms"` and two routes:
- `@api.get("/superbill/<claim_id>")`
- `@api.get("/hcfa/<claim_id>")`

### Data Retrieval
For each claim, query the following SDK models:
- `Claim` — core claim fields (accept_assign, auto_accident, illness_date, prior_auth, etc.)
- `Claim.claimpatient` — patient demographics (name, DOB, sex, SSN, address, phone)
- `Claim.coverages.filter(active=True)` — insurance/payer info (payer name, address, subscriber info, group, plan)
- `Claim.claimprovider_set` — provider info (billing provider, rendering provider, referring provider, facility)
- `Claim.line_items.active()` — procedure line items (CPT, charges, dates, units, place of service, modifiers, NDC)
- `Claim.diagnosis_codes` — ICD-10 diagnosis codes ordered by rank
- `ClaimLineItemDiagnosisCode` — diagnosis pointer linkages per line item
- `Claim.note` — note for date of service

### HTML Templates

**Superbill Template** (`templates/superbill.html`):
- Practice/facility header (name, address, phone, NPI, Tax ID)
- Patient info block (name, DOB, sex, address, phone, insurance)
- Provider info (rendering provider name, NPI)
- Date of service
- Diagnosis codes table (rank, ICD-10 code, description)
- Procedures table (CPT, description, modifiers, diagnosis pointers, units, charge)
- Totals row
- Authorization/signature lines

**CMS-1500 / HCFA Template** (`templates/hcfa.html`):
Standard CMS-1500 form layout with all 33 boxes:
- Box 1: Insurance type
- Box 1a: Insured's ID number (subscriber_number)
- Box 2: Patient name
- Box 3: Patient DOB, sex
- Box 4: Insured's name
- Box 5: Patient address
- Box 6: Patient relationship to insured
- Box 7: Insured's address
- Box 8: Reserved
- Box 9: Other insured info (secondary coverage)
- Box 10: Condition related to (employment, auto accident, other)
- Box 11: Insured's policy/group/plan, DOB, sex, employer
- Box 12-13: Signature placeholders
- Box 14: Date of illness
- Box 17: Referring provider
- Box 17a-b: Referring provider NPI
- Box 21: Diagnosis codes (up to 12, with ICD indicator)
- Box 23: Prior authorization
- Box 24A-J: Service lines (date, POS, CPT, modifiers, diagnosis pointers, charges, units, NPI)
- Box 25: Tax ID
- Box 26: Patient account number
- Box 27: Accept assignment
- Box 28: Total charge
- Box 29-30: Amount paid / balance (from claim computed properties)
- Box 31: Provider signature
- Box 32: Facility info
- Box 33: Billing provider info

### PDF Generation
```python
from canvas_sdk.utils.pdf import pdf_generator

response = pdf_generator.from_html(content=rendered_html)
pdf_url = response.url if response else None
```

### Files to Create/Modify
1. `protocols/claim_pdf_api.py` — Main SimpleAPI handler with data retrieval and response logic
2. `templates/superbill.html` — Superbill HTML template
3. `templates/hcfa.html` — CMS-1500 form HTML template
4. `CANVAS_MANIFEST.json` — Register the handler and declare `api-key` secret

### CANVAS_MANIFEST.json Updates
```json
{
  "sdk_version": "0.1.4",
  "plugin_version": "0.0.1",
  "name": "claim-pdf-generator",
  "description": "Generates superbill and CMS-1500 PDF forms from claim data",
  "components": {
    "protocols": [
      {
        "class": "claim_pdf_generator.protocols.claim_pdf_api:ClaimPdfAPI",
        "description": "API endpoints for generating superbill and HCFA PDFs"
      }
    ]
  },
  "secrets": ["api-key"],
  "tags": {},
  "references": [],
  "license": "",
  "readme": "./README.md"
}
```

## Testing Strategy

### Unit Tests
1. **Superbill generation** — Mock claim data, verify HTML rendering includes all expected fields
2. **HCFA generation** — Mock claim data, verify all 33 CMS-1500 boxes populated correctly
3. **format=url** — Verify JSON response with pdf_url
4. **format=pdf** — Verify raw PDF bytes returned with correct content type
5. **Claim not found** — Verify 404 response
6. **PDF generation failure** — Verify 500 response
7. **Authentication** — Verify API key validation
8. **Missing/optional data** — Verify graceful handling when optional claim fields are null

### UAT Scenarios
1. Call `/superbill/{claim_id}` with a valid claim — get PDF URL, open it, verify superbill content
2. Call `/hcfa/{claim_id}` with a valid claim — get PDF URL, open it, verify CMS-1500 layout
3. Call with `?format=pdf` — verify PDF downloads directly
4. Call with invalid claim_id — verify 404 error
5. Call without API key — verify 401 error

## Plugin Name
`claim-pdf-generator`
