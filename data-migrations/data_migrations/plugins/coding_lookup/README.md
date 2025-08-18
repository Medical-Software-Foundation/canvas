# 🏥 Coding Lookup Plugin

> **Standardized medical coding lookup services for Canvas**

[![Canvas SDK](https://img.shields.io/badge/Canvas-SDK-blue.svg)](https://canvasmedical.com)
[![Python](https://img.shields.io/badge/Python-3.8+-green.svg)](https://python.org)
[![License](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

---

## 📋 Description

The **Coding Lookup** plugin provides standardized medical coding lookup services for Canvas. It offers APIs to search and retrieve medical codes from various coding systems, supporting **allergy**, **medication**, and **condition** coding lookups through First DataBank (FDB) and other standard coding systems.

---

## ✨ Features

| Feature | Description | Status |
|---------|-------------|---------|
| 🔍 **Allergy Coding Lookup** | Search for allergy codes by text description OR RxNorm code (mutually exclusive) | ✅ |
| 💊 **Medication Coding Lookup** | Search for medication codes by text description AND/OR RxNorm code (flexible combination) | ✅ |
| 🩺 **Condition Coding Lookup** | Search for condition codes by text description OR ICD-10 code (mutually exclusive) | ✅ |
| 🔗 **FDB Integration** | Direct integration with First DataBank's medical coding databases | ✅ |
| 📊 **Standardized Response Format** | Consistent JSON response structure for all coding lookups | ✅ |
| 🔎 **Multiple Search Methods** | Support for both text-based and code-based searches | ✅ |
| 🚫 **Automatic Deduplication** | Removes duplicate results when searching multiple parameters (medications only) | ✅ |

---

## ⚠️ Important Note!

When installing there is a plugin secret to create a `simpleapi-api-key`. 

**🔑 Generate your API key:**
```bash
python -c "import secrets; print(secrets.token_hex(16))"
```

You will then use this key as the header.authorization in the examples below.

**🌐 Make sure to use the correct URL based on the instance you are pointing to.**

---

## 🚀 API Endpoints

### 1. 🔍 Allergy Search

Search for allergy codes using either text description or RxNorm code.

**📍 Endpoint**: `GET /plugin-io/api/coding_lookup/allergy_search`

**📝 Query Parameters**:
- `text` (optional): Text description to search for (e.g., "penicillin", "aspirin")
- `rxnorm_code` (optional): RxNorm code to look up (e.g., "7980", "1191")

> **💡 Note**: Provide either `text` OR `rxnorm_code`, not both.

### 2. 💊 Medication Search

Search for medication codes using text description and/or RxNorm code.

**📍 Endpoint**: `GET /plugin-io/api/coding_lookup/medication_search`

**📝 Query Parameters**:
- `text` (optional): Text description to search for (e.g., "aspirin", "metformin")
- `rxnorm_code` (optional): RxNorm code to look up (e.g., "1191", "6809")

> **💡 Note**: Provide at least one parameter. Both can be used together for enhanced search precision.

### 3. 🩺 Condition Search

Search for condition codes using either text description or ICD-10 code.

**📍 Endpoint**: `GET /plugin-io/api/coding_lookup/condition_search`

**📝 Query Parameters**:
- `text` (optional): Text description to search for (e.g., "diabetes", "hypertension")
- `icd10_code` (optional): ICD-10 code to look up (e.g., "E11.9", "I10")

> **💡 Note**: Provide either `text` OR `icd10_code`, not both.

---

## 🔄 Search Parameter Behavior

Each API has different rules for search parameters:

| API | 🎯 Parameter Usage | 🔍 Search Behavior |
|-----|-------------------|-------------------|
| **🔍 Allergies API** | `text` OR `rxnorm_code` | Mutually exclusive |
| **💊 Medications API** | `text` AND/OR `rxnorm_code` | Flexible combination |
| **🩺 Conditions API** | `text` OR `icd10_code` | Mutually exclusive |

### **🔍 Allergies API** - Mutually Exclusive
- Use either `text` OR `rxnorm_code`
- Cannot use both parameters simultaneously
- Returns error if both are provided

### **💊 Medications API** - Flexible Combination  
- Use `text` AND/OR `rxnorm_code`
- Can search with one or both parameters
- Enhanced precision when both are used together

### **🩺 Conditions API** - Mutually Exclusive
- Use either `text` OR `icd10_code`
- Cannot use both parameters simultaneously
- Returns error if both are provided

---

## 💻 Example Usage

### 1. Text-based Allergy Search

Search for allergies by text description:

```python
import requests

url = "http://example.canvasmedical.com/plugin-io/api/coding_lookup/allergy_search"

# Search by text description
params = {
    "text": "penicillin"
}

headers = {
    "authorization": "your-api-key-here",
    "content-type": "application/json"
}

response = requests.get(url, params=params, headers=headers)
print(response.json())
```

**Response Example**:
```json
{
    "count": 2,
    "results": [
        {
            "display": "Penicillin G",
            "concept_type": "medication",
            "concept_id": "12345",
            "code": "2-12345",
            "system": "http://www.fdbhealth.com/"
        },
        {
            "display": "Penicillin V",
            "concept_type": "medication",
            "concept_id": "12346",
            "code": "2-12346",
            "system": "http://www.fdbhealth.com/"
        }
    ]
}
```

### 2. RxNorm Code-based Allergy Search

Search for allergies by RxNorm code:

```python
import requests

url = "http://example.canvasmedical.com/plugin-io/api/coding_lookup/allergy_search"

# Search by RxNorm code
params = {
    "rxnorm_code": "7980"
}

headers = {
    "authorization": "your-api-key-here",
    "content-type": "application/json"
}

response = requests.get(url, params=params, headers=headers)
print(response.json())
```

### 3. Text-based Medication Search

Search for medications by text description:

```python
import requests

url = "http://example.canvasmedical.com/plugin-io/api/coding_lookup/medication_search"

# Search by text description
params = {
    "text": "aspirin"
}

headers = {
    "authorization": "your-api-key-here",
    "content-type": "application/json"
}

response = requests.get(url, params=params, headers=headers)
print(response.json())
```

### 4. RxNorm Code-based Medication Search

Search for medications by RxNorm code:

```python
import requests

url = "http://example.canvasmedical.com/plugin-io/api/coding_lookup/medication_search"

# Search by RxNorm code
params = {
    "rxnorm_code": "1191"
}

headers = {
    "authorization": "your-api-key-here",
    "content-type": "application/json"
}

response = requests.get(url, params=params, headers=headers)
print(response.json())
```

### 5. Text-based Condition Search

Search for conditions by text description:

```python
import requests

url = "http://example.canvasmedical.com/plugin-io/api/coding_lookup/condition_search"

# Search by text description
params = {
    "text": "diabetes"
}

headers = {
    "authorization": "your-api-key-here",
    "content-type": "application/json"
}

response = requests.get(url, params=params, headers=headers)
print(response.json())
```

### 6. ICD-10 Code-based Condition Search

Search for conditions by ICD-10 code:

```python
import requests

url = "http://example.canvasmedical.com/plugin-io/api/coding_lookup/condition_search"

# Search by ICD-10 code
params = {
    "icd10_code": "E11.9"
}

headers = {
    "authorization": "your-api-key-here",
    "content-type": "application/json"
}

response = requests.get(url, params=params, headers=headers)
print(response.json())
```

---

## 📊 Response Format

All API responses follow a consistent structure:

### Success Response
- **Status Code**: 200 OK
- **Content-Type**: application/json

**Response Fields**:
- `count`: Number of results returned
- `results`: Array of coding results

**Result Object Fields**:
- `text`: Human-readable description of the code
- `value`: Unique identifier for the code
- `coding`: Array of coding objects with different systems

**Coding Object Fields**:
- `code`: The actual code value
- `display`: Human-readable description
- `system`: Coding system identifier

---

## 📚 Response Examples

### Allergies API Response Examples

```json
{
  "count": 2,
  "results": [
    {
      "display": "Penicillins",
      "concept_type": "allergy group",
      "concept_id": "476",
      "code": "1-476",
      "system": "http://www.fdbhealth.com/"
    },
    {
      "display": "penicillin G sodium",
      "concept_type": "medication",
      "concept_id": "8228",
      "code": "2-8228",
      "system": "http://www.fdbhealth.com/"
    }
  ]
}
```

### Medications API Response Example
```json
{
  "count": 2,
  "results": [
    {
      "text": "metformin 500 mg tablet",
      "value": 155744,
      "coding": [
        {
          "code": 155744,
          "display": "metformin 500 mg tablet",
          "system": "http://www.fdbhealth.com/"
        },
        {
          "code": "861007",
          "display": "metformin 500 mg tablet",
          "system": "http://www.nlm.nih.gov/research/umls/rxnorm"
        }
      ]
    },
    {
      "text": "metformin 625 mg tablet",
      "value": 611122,
      "coding": [
        {
          "code": 611122,
          "display": "metformin 625 mg tablet",
          "system": "http://www.fdbhealth.com/"
        },
        {
          "code": "861021",
          "display": "metformin 625 mg tablet",
          "system": "http://www.nlm.nih.gov/research/umls/rxnorm"
        }
      ]
    }
  ]
}
```

### Conditions API Response Examples

```json
{
  "count": 2,
  "results": [
    {
      "text": "Vomiting of pregnancy, unspecified",
      "value": "O219",
      "coding": [
        {
          "code": "O219",
          "display": "Vomiting of pregnancy, unspecified",
          "system": "ICD-10"
        },
        {
          "code": "90325002",
          "display": "Vomiting of pregnancy, unspecified",
          "system": "http://snomed.info/sct"
        }
      ]
    },
    {
      "text": "Bilious vomiting",
      "value": "R1114",
      "coding": [
        {
          "code": "R1114",
          "display": "Bilious vomiting",
          "system": "ICD-10"
        },
        {
          "code": "78104003",
          "display": "Bilious vomiting",
          "system": "http://snomed.info/sct"
        }
      ]
    }
  ]
}
```

#### Error Response
```json
{
  "error": "Invalid search parameters. Provide either 'text' OR 'icd10_code', not both.",
  "status": "error"
}
```

### Common Response Fields

All API responses include these standard fields:

| Field | Type | Description |
|-------|------|-------------|
| `count` | Integer | Number of results returned |
| `results` | Array | List of matching concepts (empty if no matches) |

### API-Specific Response Fields

#### Allergies API Fields
| Field | Type | Description |
|-------|------|-------------|
| `display` | String | Human-readable display text |
| `concept_type` | String | Type of concept (medication, ingredient, allergy group) |
| `concept_id` | String | Primary identifier from FDB |
| `code` | String | Formatted code (type-id format, e.g., "1-476") |
| `system` | String | Coding system URI (http://www.fdbhealth.com/) |

#### Medications API Fields
| Field | Type | Description |
|-------|------|-------------|
| `text` | String | Primary text representation |
| `value` | String | Unique identifier for the concept |
| `coding` | Array | Array of coding systems and codes |

#### Conditions API Fields
| Field | Type | Description |
|-------|------|-------------|
| `text` | String | Primary text representation |
| `value` | String | Unique identifier for the concept |
| `coding` | Array | Array of coding systems and codes |

> **⚠️ Important Note**: The Allergies API uses a different response structure than Medications and Conditions APIs. When integrating with multiple endpoints (FHIR vs SDK), handle the field differences accordingly:
> - **Allergies**: Use `display`, `concept_type`, `code`, `system`
> - **Medications/Conditions**: Use `text`, `value`, `coding`

### Coding System Details

Each result includes multiple coding systems for maximum interoperability:

- **Allergies**: FDB Health system with concept type categorization
- **Medications**: FDB Health system + RxNorm codes
- **Conditions**: ICD-10-CM + SNOMED CT codes

---

## 🤔 Use Cases

| Use Case | Description | 🎯 Benefit |
|----------|-------------|-------------|
| 🏥 **Clinical Decision Support** | Look up allergy, medication, and condition codes during patient assessment | Better patient care |
| 🔄 **Data Migration** | Standardize medical coding when migrating from other systems | Consistent data |
| 🔗 **EHR Integration** | Provide comprehensive coding services for external EHR systems | Seamless integration |
| ✅ **Quality Assurance** | Validate medical codes against standard databases | Data accuracy |
| 💊 **Medication Management** | Look up proper medication codes for prescriptions and orders (supports combined text + RxNorm searches) | Enhanced precision |
| 🩺 **Diagnosis Coding** | Find appropriate ICD-10 and SNOMED CT codes for conditions | Standard compliance |
| ⚠️ **Allergy Documentation** | Standardize allergy coding for patient safety | Patient safety |
| 🎯 **Flexible Search Strategies** | Multiple search approaches for different needs | User experience |

### **🔍 Search Strategy Examples:**
- **🚀 Simple searches**: Use single parameter for quick lookups
- **🎯 Precise searches**: Use multiple parameters for enhanced accuracy (medications only)
- **✅ Code validation**: Verify existing codes against standard databases

---

## 🛠️ Development

### **🔧 Adding New Coding Systems**

To extend the plugin with additional coding systems:

1. **📁 Create a new protocol class** in the `protocols/` directory
2. **⚙️ Implement the required search methods**
3. **📋 Add the new protocol** to `CANVAS_MANIFEST.json`
4. **📚 Update this README** with new endpoint documentation


</div>

