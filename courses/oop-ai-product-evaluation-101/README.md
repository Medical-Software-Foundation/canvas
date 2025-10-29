# OOP AI Product Evaluation 101

A hands-on course for evaluating AI products from both builder and buyer perspectives.

## Project Overview

This project has two main parts:

### 1. **Builder Perspective** → `intake_agent/`
The **EZGrow** AI medical intake agent - the product we're evaluating. This is a Flask web application that uses an LLM to conduct patient intake interviews and extract structured medical data.

### 2. **Buyer Perspective** → `buyer_evals/`
Black-box evaluation tools that test the intake agent from an external perspective. These simulate real patients having conversations with the agent and analyze the quality of extracted data.

---

## Quickstart

### Prerequisites
- Python 3.10+
- [uv](https://docs.astral.sh/uv/) package manager
- Anthropic API key

### Part 1: Setup the Product

**1. Install dependencies:**
```bash
uv sync
```

**2. Set environment variables:**

Create an environment file or export directly:
```bash
# Option A: Export directly
export ANTHROPIC_API_KEY="your-api-key-here"

# Option B: Use the provided script (edit it first with your key)
# Edit env/set_env_vars.sh to add your API key
source env/set_env_vars.sh
```

**Required environment variable:**
- `ANTHROPIC_API_KEY` - Your Anthropic API key for Claude

**3. Initialize the database:**
```bash
cd intake_agent
python app.py
```

The app will automatically create `intake_agent.db` on first run.

**4. Verify it's working:**

Open your browser and go to: **http://localhost:5000**

You should see the EZGrow intake interface with:
- Left side: Chat interface
- Right side: Structured medical record

**5. Do a manual test intake:**

Click "Start New Patient" and try a conversation:
```
You: "Hi, my name is John Smith"
Agent: "Thank you, Mr. Smith. What is your date of birth?"
You: "January 15, 1985"
... (continue the conversation)
```

Watch as the agent extracts structured data and displays it in real-time on the right panel.

---

### Part 2: Run Buyer Evaluations

Now that the product is running, test it from the buyer perspective.

**1. Keep the intake agent running** (from Part 1)

**2. In a new terminal, run a test case:**
```bash
# Run case 001 (Marcus - young male with anxiety)
python buyer_evals/case_runner_bilateral.py 001
```

This will:
- Launch a browser window (you can watch the conversation)
- Simulate a patient with the personality and characteristics from `case_001.json`
- Use an LLM to generate realistic responses to the agent's questions
- Save the conversation and extracted data to `case_001_result.json`

**3. Review the results:**
```bash
# View the conversation and extracted data
cat buyer_evals/cases_bilateral/case_001_result.json

# View the analysis comparing expected vs actual data
cat buyer_evals/cases_bilateral/case_001_analysis.json
```

---

## What's Next?

### For Builders
- Explore `intake_agent/` to see how the product works
- Modify the agent's behavior in `intake_agent/config.py`
- Review `intake_agent/README.md` for detailed documentation

### For Buyers
- Create new test cases in `buyer_evals/cases_bilateral/`
- Review analysis results to identify patterns in agent performance
- Compare results across different case types (elderly, complex conditions, etc.)
- See `buyer_evals/README.md` for detailed evaluation workflows

---

## Project Structure

```
.
├── intake_agent/          # The EZGrow product (builder perspective)
│   ├── app.py            # Flask application
│   ├── agent.py          # Core agent logic
│   ├── config.py         # Configuration
│   └── templates/        # Web interface
│
├── buyer_evals/          # Evaluation tools (buyer perspective)
│   ├── case_runner_bilateral.py    # LLM-driven test runner
│   ├── case_runner_unilateral.py   # Pre-scripted test runner
│   ├── analyze_all_cases.py        # Batch analysis tool
│   ├── cases_bilateral/            # LLM-driven test cases
│   └── cases_unilateral/           # Pre-scripted test cases
│
└── llms/                 # LLM wrapper classes
    └── llm_anthropic.py  # Anthropic Claude wrapper
```

---

## Troubleshooting

**Problem:** `ModuleNotFoundError` when running scripts
- **Solution:** Make sure you ran `uv sync` to install dependencies

**Problem:** "Cannot connect to database"
- **Solution:** Run `python intake_agent/app.py` once to initialize the database

**Problem:** Agent not responding
- **Solution:** Check that `ANTHROPIC_API_KEY` is set correctly

**Problem:** Browser automation fails
- **Solution:** Install Playwright browsers: `playwright install chromium`

**Problem:** "No such file or directory" when running bash scripts
- **Solution:** Make sure you're running from the project root directory

---
