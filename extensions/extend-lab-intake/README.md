# Extend Lab Intake

Automated lab report intake plugin using Extend AI for document classification and extraction.

## Overview

This plugin receives lab report PDFs via HTTP POST, classifies and extracts structured data using Extend AI,
matches patients using LLM-based demographics matching, and creates FHIR DiagnosticReports in Canvas.

## Features

- **Document Queue Application** - Global Canvas application to view and manage received lab documents
- **Automated extraction** - Uses Extend AI to classify and extract structured lab data
- **Patient matching** - LLM-based patient matching from extracted demographics
- **FHIR integration** - Creates DiagnosticReports via the `create-lab-report` operation
- **Task tracking** - Optional task completion callback for workflow integration

## Endpoints

### Inbound Fax Endpoint

**POST** `/plugin-io/api/extend_lab_intake/lab-intake/inbound-fax`

#### Request

- **Content-Type**: `multipart/form-data`
- **Authorization**: API key in `Authorization` header (use `INBOUND_FAX_TOKEN` value)
- **Body**: PDF file in `file` field

#### Response

```json
{
    "status": "success",
    "intake_id": "abc123def456",
    "patient_id": "0e6c07fd1274489281d0044876eebfa1",
    "diagnostic_report_id": "report-uuid",
    "confidence": "high",
    "classification": "lipid_panel",
    "summary": "LIPID PANEL SUMMARY - Collection Date: 11/19/2025..."
}
```

### Document Queue Endpoints

- **GET** `/lab-intake/documents` - List all intake documents
- **POST** `/lab-intake/extract/{intake_id}` - Manually trigger extraction for a document
- **POST** `/lab-intake/save-report/{intake_id}` - Save extracted data as FHIR DiagnosticReport
- **POST** `/lab-intake/discard/{intake_id}` - Discard a document from the queue

### Health Check Endpoint

**GET** `/plugin-io/api/extend_lab_intake/lab-intake/health`

Returns `{"status": "healthy", "service": "lab-intake"}` (unauthenticated)

## Required Secrets

| Secret | Description |
|--------|-------------|
| `EXTEND_AI_KEY` | Extend AI API key |
| `EXTEND_AI_PROCESSOR_TREE` | JSON tree mapping classifiers to extractors (see below) |
| `ANTHROPIC_API_KEY` | Anthropic Claude API key for patient matching/summarization |
| `AWS_ACCESS_KEY_ID` | AWS access key for S3 storage |
| `AWS_SECRET_ACCESS_KEY` | AWS secret key for S3 storage |
| `FHIR_CLIENT_ID` | Canvas FHIR API client ID |
| `FHIR_CLIENT_SECRET` | Canvas FHIR API client secret |
| `INBOUND_FAX_TOKEN` | API key for authenticating POST requests |
| `CALLBACK_URL` | (Optional) URL to POST completion notifications |

### Processor Tree Format

The `EXTEND_AI_PROCESSOR_TREE` secret defines the classification-to-extraction flow:

```json
{
    "dp_M69JkcrxCTM-VSn2XMO_j": {
        "name": "Lipid Panel Classifier",
        "type": "CLASSIFY",
        "extractors": {
            "lipid_panel": {
                "processor_id": "dp_vniDOpbx4iYxzoTYRKGa6",
                "name": "Lab Report Extractor",
                "type": "EXTRACT"
            }
        }
    }
}
```

- The top-level key is the classifier processor ID
- `extractors` maps classification results (e.g., `lipid_panel`) to extractor processor IDs
- Documents classified as types without an extractor are skipped

## Processing Pipeline

1. **Receive PDF** - Accept multipart form upload with authentication
2. **Upload to S3** - Store PDF in `canvas-plugin-data` bucket for Extend AI access
3. **Classify Document** - Run Extend AI classifier to determine document type
4. **Extract Data** - Run appropriate Extend AI extractor based on classification
5. **Match Patient** - Query Canvas patients and use LLM to match demographics
6. **Generate Summary** - Create clinical summary of lab results using LLM
7. **Create FHIR Report** - Build DiagnosticReport with structured lab values (if patient matched)
8. **Create Task** - Track intake with Canvas task (linked to patient if matched)
9. **Callback** - POST completion notification to callback URL (if configured)

## S3 Configuration

PDFs are stored in the `canvas-plugin-data` S3 bucket with the path pattern:
```
{instance}-plugins/extend_lab_intake/intake/{intake_id}/{filename}
```

The bucket policy requires objects to start with `{instance}-plugins/`.

---

## Scripts

Scripts for creating and managing Extend AI processors used by the plugin.

### Prerequisites

Set the required environment variables:

```bash
export EXTEND_AI_KEY="your-extend-ai-api-key"
export ANTHROPIC_API_KEY="your-anthropic-api-key"  # Only needed for LLM schema generation
```

### create_processor.py

Creates an **extraction** processor that extracts structured data from documents.

**List existing extractors:**
```bash
uv run python scripts/create_processor.py --list
```

**Create from a JSON schema file:**
```bash
uv run python scripts/create_processor.py \
  --input-schema scripts/sample_lab_schema.json \
  --name "Lab Report Extractor"
```

**Create from a text specification (uses LLM to generate schema):**
```bash
uv run python scripts/create_processor.py \
  scripts/example_lab_report_spec.txt \
  --name "Lab Report Extractor"
```

**Dry run (generate schema without creating processor):**
```bash
uv run python scripts/create_processor.py \
  scripts/example_lab_report_spec.txt \
  --name "Lab Report Extractor" \
  --dry-run
```

**Save generated schema to file:**
```bash
uv run python scripts/create_processor.py \
  scripts/example_lab_report_spec.txt \
  --name "Lab Report Extractor" \
  --output-schema my_schema.json \
  --dry-run
```

**Add extraction rules:**
```bash
uv run python scripts/create_processor.py \
  --input-schema scripts/sample_lab_schema.json \
  --name "Lab Report Extractor" \
  --rules "Extract all numeric values with their units. If a reference range is provided, include it."
```

#### Options

| Option | Description |
|--------|-------------|
| `spec_file` | Text file with extraction specification (for LLM conversion) |
| `--name` | Name for the processor (required) |
| `--input-schema` | JSON schema file (skips LLM generation) |
| `--output-schema` | Save generated schema to this file |
| `--rules` | Natural language extraction rules |
| `--dry-run` | Generate schema but don't create processor |
| `--list` | List existing extraction processors |

### create_classifier.py

Creates a **classifier** processor that categorizes documents into defined classes.

**List existing classifiers:**
```bash
uv run python scripts/create_classifier.py --list
```

**Create a binary classifier:**
```bash
uv run python scripts/create_classifier.py \
  --name "Lipid Panel Classifier" \
  --classifications \
    "lipid_panel:Lipid Panel Lab Report" \
    "other:Not a Lipid Panel"
```

**Create with classification rules:**
```bash
uv run python scripts/create_classifier.py \
  --name "Lipid Panel Classifier" \
  --classifications \
    "lipid_panel:Lipid Panel Lab Report" \
    "other:Not a Lipid Panel" \
  --rules "Classify as lipid_panel if the document contains lab results for cholesterol, LDL, HDL, or triglycerides."
```

**Create from a config file:**
```bash
uv run python scripts/create_classifier.py \
  --name "Document Classifier" \
  --config-file classifier_config.json
```

Config file format:
```json
{
  "classifications": [
    {"type": "lipid_panel", "description": "Lipid Panel Lab Report"},
    {"type": "cbc", "description": "Complete Blood Count"},
    {"type": "other", "description": "Other document type"}
  ]
}
```

#### Options

| Option | Description |
|--------|-------------|
| `--name` | Name for the processor (required) |
| `--classifications` | Classifications in `key:description` format |
| `--config-file` | JSON file with classifications config |
| `--rules` | Natural language classification rules |
| `--dry-run` | Show config but don't create processor |
| `--list` | List existing classifier processors |

### upload_pdf.py

Uploads a PDF to the inbound fax endpoint for testing.

```bash
uv run python scripts/upload_pdf.py <pdf_file> [--host <host>]
```

### debug_run_lipid_panel_extractor.py

Debug script to run the lipid panel extractor against an existing intake document.

```bash
uv run python scripts/debug_run_lipid_panel_extractor.py <intake_id>
```

Requires environment variables: `EXTEND_AI_KEY`, `EXTEND_AI_PROCESSOR_TREE`, `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`

---

## Schema Format

Extend AI uses JSON Schema with some specific requirements:

### Primitive Types (nullable)
```json
{
  "field_name": {
    "type": ["string", "null"],
    "description": "Field description"
  }
}
```

Supported primitive types: `string`, `number`, `integer`, `boolean`

### Arrays (not nullable)
```json
{
  "items": {
    "type": "array",
    "items": {
      "type": "object",
      "properties": { ... }
    }
  }
}
```

### Special Extend Types

**Date** (ISO format yyyy-mm-dd):
```json
{
  "date_field": {
    "type": ["string", "null"],
    "extend:type": "date",
    "description": "A date field"
  }
}
```

**Currency**:
```json
{
  "amount": {
    "type": ["object", "null"],
    "extend:type": "currency",
    "description": "Monetary amount"
  }
}
```

---

## Building the Processor Tree

After creating a classifier and extractor(s), build the processor tree JSON:

```json
{
    "dp_M69JkcrxCTM-VSn2XMO_j": {
        "name": "Lipid Panel Classifier",
        "type": "CLASSIFY",
        "extractors": {
            "lipid_panel": {
                "processor_id": "dp_vniDOpbx4iYxzoTYRKGa6",
                "name": "Lab Report Extractor",
                "type": "EXTRACT"
            }
        }
    }
}
```

- The top-level key (`dp_M69JkcrxCTM-VSn2XMO_j`) is the classifier processor ID
- Each key under `extractors` matches a classification output (e.g., `lipid_panel`)
- `processor_id` is the extractor processor ID to use for that classification

Set this JSON as the `EXTEND_AI_PROCESSOR_TREE` secret in the Canvas plugin settings.

## Extraction Output Format

Extend AI returns extraction results in the following structure:

```json
{
  "value": {
    "patient_name": "John Doe",
    "date_of_birth": "1980-01-15",
    "test_results": [
      {
        "test_name": "Total Cholesterol",
        "result_value": "195",
        "unit": "mg/dL",
        "reference_range": "<200"
      }
    ]
  },
  "metadata": {
    "patient_name": { "logprobsConfidence": 1.0 },
    "date_of_birth": { "logprobsConfidence": 0.98 },
    "test_results[0].test_name": { "logprobsConfidence": 1.0 }
  }
}
```

- `value` contains the extracted data
- `metadata` contains confidence scores for each field path via `logprobsConfidence`
