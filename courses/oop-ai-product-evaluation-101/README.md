# Out-of-Pocket Health AI Product Evaluation 101

A course on evaluating AI products, created in partnership with Out-of-Pocket Health (OOP).

## Overview

This course teaches how to build and test LLM wrappers for different AI providers using object-oriented programming best practices.

## Course Structure

### Core Modules

- `llm_openai.py` - OpenAI GPT wrapper
- `llm_google.py` - Google Gemini wrapper
- `llm_anthropic.py` - Anthropic Claude wrapper

### Intake Agent Application

The `intake_agent/` directory contains a complete medical intake web application used for demonstrations and evaluation exercises:

- **Split-screen interface** - Real-time chat with AI agent alongside structured medical record
- **AI-powered data extraction** - Automatically extracts demographics, conditions, medications, allergies, and goals from natural conversation
- **Configurable agent** - Customize personality (professional to meme_lord), verbosity, and model
- **Automated evaluation system** - Playwright-based patient simulator for testing extraction accuracy

See `intake_agent/README.md` for setup and usage instructions.

The intake agent demonstrates real-world AI product evaluation concepts including:
- Black-box testing with decoupled evaluation agents
- Precision/recall metrics for information extraction
- Nondeterminism detection in conversational AI
- Ground truth comparison and validation

## Installation

```bash
# Install dependencies using uv
uv sync
```

## Running Tests

```bash
# Run all tests
uv run pytest tests/

# Run specific test file
uv run pytest tests/test_llm_openai.py

# Run with verbose output
uv run pytest tests/ -v

# Run with coverage report
uv run pytest tests/ --cov=.

# Generate HTML coverage report
uv run pytest tests/ --cov=. --cov-report=html
# Open htmlcov/index.html in your browser
```

## Running Demos

The `demos/` directory contains example scripts demonstrating LLM evaluation techniques.

### Demo 1: Nondeterministic Outputs

Tests variability in LLM outputs across vendors and models for the same medical prompt.

```bash
# Set up API keys first
# Edit env/set_env_vars.sh with your keys, then:

source env/set_env_vars.sh && uv run python demos/demo_1_nondeterministic.py
```

This demo:
- Tests 9 models across OpenAI, Google, and Anthropic
- Runs each model 3 times to detect nondeterminism (27 total requests)
- Uses 6 parallel workers for faster execution
- Shows real-time progress with start/completion logging
- Displays results in an ASCII table showing unique medications at each rank
- Compares medication recommendations for hypertension (preserves order)
- Detects nondeterminism both within models (across runs) and across different models
- Provides detailed statistics and summary

## Usage

Each LLM wrapper provides a consistent interface:

```python
from llm_openai import LlmOpenai

# Initialize
llm = LlmOpenai(api_key="your-key", model="gpt-4")

# Simple chat
result = llm.chat(
    system_prompt="You are a helpful assistant.",
    user_prompt="Hello!"
)

# Chat with JSON response
result = llm.chat_with_json(
    system_prompt="Return JSON only.",
    user_prompt="Give me a list of 3 colors."
)
```
