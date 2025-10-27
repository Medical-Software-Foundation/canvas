# Seller-Side Evaluation System

A developer/seller-side evaluation system that uses Playwright to simulate patients interacting with the intake agent, with full access to database and internal metrics for ground-truth comparison.

**Note:** This is the **seller-side** evaluation. For **buyer-side** evaluation (no database access), see `../buy_side/README.md`.

## Setup

```bash
# Install dependencies
uv sync

# Install Playwright browsers (first time only)
uv run playwright install chromium
```

## Quick Start

```bash
# Make sure the intake agent is running
cd intake_agent
uv run python app.py

# In another terminal, run evaluation from the sell_side directory
cd evals/sell_side
uv run python run_evaluation.py
```

This will:
1. Open a browser window
2. Create a new patient
3. Simulate a patient conversation
4. Extract and compare data against ground truth
5. Generate an evaluation report

## Usage

```bash
# List available patient personas
uv run python run_evaluation.py --list

# Run specific persona
uv run python run_evaluation.py --persona simple_hypertension

# Run in headless mode (no visible browser)
uv run python run_evaluation.py --persona complex_chronic --headless

# Run all personas
uv run python run_evaluation.py --persona all --headless
```

## Architecture

### 1. Patient Simulator (`patient_simulator.py`)
- Uses Playwright to control a real browser
- Completely decoupled from internal implementation
- Interacts only through the UI (clicks, types, reads)
- Uses LLM to generate realistic patient responses

### 2. Patient Personas (`patient_personas.py`)
- Pre-defined patient profiles with known medical information
- Serves as "ground truth" for evaluation
- Includes personas ranging from simple to complex cases

### 3. Evaluator (`evaluator.py`)
- Compares extracted data against ground truth
- Calculates precision, recall, F1 scores
- Generates detailed reports

### 4. Runner (`run_evaluation.py`)
- Orchestrates the full evaluation cycle
- Can run single or multiple personas
- Aggregates results across evaluations

## Metrics

The evaluator calculates:

- **Demographics Score**: Accuracy of name, DOB, sex/gender extraction
- **Conditions F1**: Precision and recall for medical conditions
- **Medications F1**: Precision and recall for medications, plus dose accuracy
- **Allergies F1**: Precision and recall for allergies
- **Goals F1**: Precision and recall for health goals
- **Overall Score**: Weighted average of all categories

## Example Output

```
======================================================================
INTAKE AGENT EVALUATION REPORT
======================================================================

Overall Score: 87.50%

----------------------------------------------------------------------

DEMOGRAPHICS: 100.00% (6/6 correct)
  ✓ first_name
  ✓ last_name
  ✓ date_of_birth
  ✓ sex
  ✓ gender
  ✓ current_health_concerns

CONDITIONS: 100.00%
  Precision: 100.00%, Recall: 100.00%
  Extracted: 1, Expected: 1

MEDICATIONS: 100.00%
  Precision: 100.00%, Recall: 100.00%
  Dose accuracy: 100.00%
  Extracted: 1, Expected: 1

ALLERGIES: 100.00%
  Precision: 100.00%, Recall: 100.00%
  Extracted: 1, Expected: 1

GOALS: 50.00%
  Precision: 100.00%, Recall: 50.00%
  Extracted: 1, Expected: 2
  Missed: reduce blood pressure medication

======================================================================
```

## Adding New Personas

Edit `patient_personas.py` and add a new entry to the `PERSONAS` dictionary:

```python
PERSONAS = {
    "my_custom_persona": {
        "first_name": "Jane",
        "last_name": "Doe",
        "date_of_birth": "1980-05-20",
        "sex": "female",
        "gender": "female",
        "current_health_concerns": "...",
        "conditions": [...],
        "medications": [...],
        "allergies": [...],
        "goals": [...]
    }
}
```

## Why Playwright?

Playwright provides **true external decoupling** for the patient simulation:
- Patient simulator has no internal imports (no Flask, no database.py, no intake_parser.py)
- No knowledge of WebSockets, API endpoints, or database schema
- Only sees what a real user sees in the browser
- Tests the full stack including UI rendering
- Would still work even if you rewrote the backend completely

This is black-box testing at its finest.

---

## Seller-Side vs Buyer-Side Evaluation

This project includes **two complementary evaluation systems**:

### 🏢 Seller-Side (this directory)
- **Access:** Full database and internal system access
- **Purpose:** Developer testing with quantitative metrics
- **Method:** Automated patient personas with known ground truth
- **Metrics:** Precision, Recall, F1 scores
- **Use case:** Regression testing, performance tracking, CI/CD

### 🛒 Buyer-Side (`../buy_side/`)
- **Access:** Browser only, no database or server internals
- **Purpose:** Product evaluation from buyer's perspective
- **Method:** Manual test cases with HTML analysis
- **Metrics:** Data quality scores, duplicate detection, completeness
- **Use case:** Due diligence, vendor evaluation, acceptance testing

Both approaches are valuable for different stakeholders!
