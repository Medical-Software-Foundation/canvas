#!/usr/bin/env python3
"""
Demo 2: Nondeterministic LLM Outputs - Clinician Grading

This script demonstrates the variability in LLM outputs when grading clinician
performance across different vendors and models. We load a conversation and ask
each model to rate the clinician on a scale of 1-5.

Usage:
    python demos/demo_2_nondeterministic.py
    # or
    uv run python demos/demo_2_nondeterministic.py
"""

from __future__ import annotations

import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from threading import Lock

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from llm_openai import LlmOpenai
from llm_google import LlmGoogle
from llm_anthropic import LlmAnthropic


# ============================================================================
# CONFIGURATION
# ============================================================================

NUM_WORKERS = 8  # Number of parallel workers for ThreadPoolExecutor
NUM_REPLICATIONS = 10  # Number of times to run each model
CONVERSATION_NUMBER = 1
RUBRIC = "simple"  # "simple" (1-5 scale) or "complex" (dimensional % scores) 


# ============================================================================
# LOAD CONVERSATION
# ============================================================================

def load_conversation(conversation_number: int) -> list[dict]:
    """Load conversation from conversation_1.json."""
    conversation_path = Path(__file__).parent / f"conversation_{conversation_number}.json"
    with open(conversation_path, "r") as f:
        return json.load(f)


# ============================================================================
# PROMPT AND JSON SCHEMA
# ============================================================================

SYSTEM_PROMPT = """You are a clinical quality evaluator.
You assess clinician performance based on conversation transcripts.
You must respond with valid JSON in a markdown code block."""


def build_user_prompt(conversation: list[dict], rubric: str) -> str:
    """Build user prompt with conversation."""
    conv_text = "\n\n".join([
        f"{turn['speaker'].upper()}: {turn['content']}"
        for turn in conversation
    ])

    if rubric == "simple":
        return f"""Please evaluate the clinician's performance in the following conversation.

{conv_text}

Rate the clinician on a scale of 1-5, where:
1 = Very poor (unprofessional, harmful, or negligent)
2 = Poor (significant deficiencies in care or communication)
3 = Adequate (meets minimum standards but room for improvement)
4 = Good (competent care with minor areas for improvement)
5 = Excellent (exemplary care and communication)

Please respond with a JSON object following this exact schema:

```json
{{
  "score": <your score>
}}
```

Provide only the score as an integer from 1 to 5."""

    else:  # complex rubric
        return f"""Please evaluate the clinician's performance in the following conversation across four dimensions.

{conv_text}

Rate the clinician on each of these dimensions as a percentage (0-100):

1. LISTENING: How well did the clinician listen to and acknowledge patient/family concerns?
2. INVESTIGATION: How thoroughly did the clinician gather relevant medical history and information?
3. SYNTHESIS: How well did the clinician integrate information and explain medical concepts?
4. ACTION: How clear and appropriate were the clinician's recommendations and next steps?

Please respond with a JSON object following this exact schema:

```json
{{
  "listening": <percentage 0-100>,
  "investigation": <percentage 0-100>,
  "synthesis": <percentage 0-100>,
  "action": <percentage 0-100>
}}
```

Provide only integer percentages for each dimension."""


# ============================================================================
# MODEL CONFIGURATIONS
# ============================================================================

MODEL_CONFIG = {
    "openai": {
        "class": LlmOpenai,
        "models": [
            "gpt-4o",
            "gpt-4o-mini",
            "gpt-4-turbo",
        ],
        "env_var": "OPENAI_API_KEY",
    },
    "google": {
        "class": LlmGoogle,
        "models": [
            "models/gemini-2.0-flash",
            "models/gemini-2.0-flash-lite",
            "models/gemini-2.5-flash",
        ],
        "env_var": "GOOGLE_API_KEY",
    },
    "anthropic": {
        "class": LlmAnthropic,
        "models": [
            "claude-haiku-4-5-20251001",
            "claude-sonnet-4-5-20250929",
        ],
        "env_var": "ANTHROPIC_API_KEY",
    },
}


# ============================================================================
# PROGRESS TRACKING
# ============================================================================

class ProgressTracker:
    """Thread-safe progress tracker for parallel execution."""

    def __init__(self, total: int):
        self.total = total
        self.completed = 0
        self.lock = Lock()

    def start_task(self, vendor: str, model: str):
        """Log task start."""
        with self.lock:
            model_short = model.split("/")[-1]
            print(f"  → Starting {vendor}/{model_short}...")

    def complete_task(self, vendor: str, model: str, success: bool, elapsed: float):
        """Log task completion."""
        with self.lock:
            self.completed += 1
            model_short = model.split("/")[-1]
            status = "✓" if success else "✗"
            print(f"  {status} Completed {vendor}/{model_short} in {elapsed:.2f}s ({self.completed}/{self.total})")


# ============================================================================
# MAIN DEMO LOGIC
# ============================================================================

def get_api_key(env_var: str) -> str | None:
    """Get API key from environment variable."""
    return os.environ.get(env_var)


def test_model(vendor: str, model: str, llm_class, api_key: str, tracker: ProgressTracker, user_prompt: str, rubric: str, run_number: int = 1) -> dict:
    """Test a single model and return results."""
    tracker.start_task(vendor, model)

    try:
        llm = llm_class(api_key=api_key, model=model)
        start_time = time.time()
        result = llm.chat_with_json(
            system_prompt=SYSTEM_PROMPT,
            user_prompt=user_prompt,
            max_retries=3,
        )
        elapsed_time = time.time() - start_time

        if result["success"]:
            if rubric == "simple":
                score = result["data"].get("score")
                score_data = {"score": score}
            else:  # complex
                score_data = {
                    "listening": result["data"].get("listening"),
                    "investigation": result["data"].get("investigation"),
                    "synthesis": result["data"].get("synthesis"),
                    "action": result["data"].get("action"),
                }

            tracker.complete_task(vendor, model, True, elapsed_time)

            return {
                "vendor": vendor,
                "model": model,
                "run_number": run_number,
                "success": True,
                "score_data": score_data,
                "elapsed_time": elapsed_time,
                "error": None,
            }
        else:
            tracker.complete_task(vendor, model, False, elapsed_time)

            return {
                "vendor": vendor,
                "model": model,
                "run_number": run_number,
                "success": False,
                "score_data": None,
                "elapsed_time": elapsed_time,
                "error": result["error"],
            }

    except Exception as e:
        tracker.complete_task(vendor, model, False, 0)

        return {
            "vendor": vendor,
            "model": model,
            "run_number": run_number,
            "success": False,
            "score_data": None,
            "elapsed_time": 0,
            "error": str(e),
        }


def print_header(rubric: str):
    """Print demo header."""
    print("=" * 80)
    print("DEMO 2: Nondeterministic LLM Outputs - Clinician Grading")
    print("=" * 80)
    print()
    if rubric == "simple":
        print("Testing: Clinician performance evaluation (scale 1-5)")
        print("Expected: Integer score from 1 to 5")
    else:
        print("Testing: Clinician performance evaluation (dimensional scores)")
        print("Expected: Percentage scores (0-100) for Listening, Investigation, Synthesis, Action")
    print()


def print_summary(results: list[dict], rubric: str, total_time: float = None):
    """Print concise summary of results."""
    print("\n" + "=" * 80)
    print("RESULTS TABLE")
    print("=" * 80)
    print()

    # Separate successful and failed results
    successful = [r for r in results if r["success"]]
    failed = [r for r in results if not r["success"]]

    if successful:
        # Group results by model
        model_results = {}
        for result in successful:
            model_key = f"{result['vendor']}/{result['model']}"
            if model_key not in model_results:
                model_results[model_key] = []
            model_results[model_key].append(result)

        # Create ASCII table for successful results (Model | Scores)
        print(f"Clinician Scores by Model ({NUM_REPLICATIONS} runs each):\n")
        print("(Rows in red indicate variation across replications)\n")

        # Calculate column widths based on rubric type
        model_col_width = 30  # Width for model name column
        if rubric == "simple":
            scores_col_width = 20  # Width for simple scores column
        else:
            scores_col_width = 50  # Wider for complex format

        # Print header row
        header = f" {'Model':^{model_col_width}} | {f'Scores ({NUM_REPLICATIONS} runs)':^{scores_col_width}} |"
        print(header)

        # Print separator
        separator = f"-{'-' * model_col_width}-+-{'-' * scores_col_width}-+"
        print(separator)

        # Print each model with comma-separated scores
        for model_key, model_runs in sorted(model_results.items()):
            vendor = model_runs[0]["vendor"]
            model = model_runs[0]["model"]
            model_short = model.split("/")[-1]
            vendor_short = vendor[:3].upper()
            model_name = f"{vendor_short}/{model_short}"

            # Truncate model name if too long
            if len(model_name) > model_col_width:
                model_name = model_name[:model_col_width-3] + "..."

            # Format scores based on rubric type
            if rubric == "simple":
                # Simple: just the score value
                scores = [str(run["score_data"]["score"]) for run in model_runs]
                scores_display = ", ".join(scores)
                unique_scores = set(scores)
                has_variation = len(unique_scores) > 1
            else:
                # Complex: L##/I##/S##/A## format
                score_strs = []
                for run in model_runs:
                    sd = run["score_data"]
                    score_str = f"L{sd['listening']}/I{sd['investigation']}/S{sd['synthesis']}/A{sd['action']}"
                    score_strs.append(score_str)
                scores_display = ", ".join(score_strs)

                # Check for variation across any dimension
                has_variation = False
                for dim in ["listening", "investigation", "synthesis", "action"]:
                    dim_scores = [run["score_data"][dim] for run in model_runs]
                    if len(set(dim_scores)) > 1:
                        has_variation = True
                        break

            # Build the row
            row = f" {model_name:<{model_col_width}} | {scores_display:^{scores_col_width}} |"

            # Check if scores vary (apply red if they do)
            if has_variation:
                row = f"\033[91m{row}\033[0m"

            print(row)

        # Print bottom separator
        print(separator)

        # Print timing info below table
        print("\nModel Performance (avg across runs):")
        for model_key, model_runs in sorted(model_results.items()):
            vendor = model_runs[0]["vendor"]
            model = model_runs[0]["model"]
            model_short = model.split("/")[-1]
            vendor_short = vendor[:3].upper()
            avg_time = sum(r["elapsed_time"] for r in model_runs) / len(model_runs)
            print(f"  {vendor_short}/{model_short}: {avg_time:.2f}s (avg of {len(model_runs)} runs)")

    if failed:
        print(f"\n\nFailed Models ({len(failed)}):")
        print("-" * 80)
        for result in failed:
            model_short = result["model"].split("/")[-1]
            vendor_short = result["vendor"][:3].upper()
            error_preview = result["error"][:60] + "..." if len(result["error"]) > 60 else result["error"]
            print(f"  {vendor_short}/{model_short}: {error_preview}")

    # Statistics
    print("\n" + "=" * 80)
    print("STATISTICS")
    print("=" * 80)

    # Count unique models
    unique_models = set()
    for result in results:
        unique_models.add(f"{result['vendor']}/{result['model']}")

    print(f"\nTotal requests: {len(results)} ({len(unique_models)} unique models × {NUM_REPLICATIONS} runs)")
    print(f"Successful: {len(successful)}")
    print(f"Failed: {len(failed)}")

    if total_time:
        print(f"Total execution time: {total_time:.2f}s (parallelized with {NUM_WORKERS} workers)")

    if successful:
        avg_time = sum(r["elapsed_time"] for r in successful) / len(successful)
        print(f"Average response time per request: {avg_time:.2f}s")

        # Check for nondeterminism within models (same model, different runs)
        nondeterministic_models = []
        for model_key, model_runs in sorted(model_results.items()):
            if rubric == "simple":
                # Check if simple scores vary across runs
                scores = [run["score_data"]["score"] for run in model_runs]
                if len(set(scores)) > 1:
                    nondeterministic_models.append(model_key)
            else:
                # Check if any dimension varies across runs
                has_variation = False
                for dim in ["listening", "investigation", "synthesis", "action"]:
                    dim_scores = [run["score_data"][dim] for run in model_runs]
                    if len(set(dim_scores)) > 1:
                        has_variation = True
                        break
                if has_variation:
                    nondeterministic_models.append(model_key)

        if nondeterministic_models:
            print(f"\nNONDETERMINISM DETECTED: {len(nondeterministic_models)} model(s) returned different scores across runs")
            for model_key in nondeterministic_models:
                vendor = model_key.split("/")[0]
                model_short = model_key.split("/")[1].split("/")[-1]
                vendor_short = vendor[:3].upper()
                print(f"  - {vendor_short}/{model_short}")
        else:
            print(f"\nAll models were deterministic across {NUM_REPLICATIONS} runs")

    # Score distribution
    if successful:
        from collections import Counter

        if rubric == "simple":
            all_scores = [r["score_data"]["score"] for r in successful]
            score_counts = Counter(all_scores)

            print(f"\nScore distribution (across {len(successful)} successful responses):")
            for score in sorted(score_counts.keys()):
                count = score_counts[score]
                percentage = (count / len(successful)) * 100
                print(f"  Score {score}: {count}/{len(successful)} ({percentage:.0f}%)")

            avg_score = sum(all_scores) / len(all_scores)
            print(f"\nAverage score: {avg_score:.2f}")
        else:
            # Complex rubric: show average for each dimension
            print(f"\nAverage scores by dimension (across {len(successful)} successful responses):")
            for dim in ["listening", "investigation", "synthesis", "action"]:
                dim_scores = [r["score_data"][dim] for r in successful]
                avg_dim_score = sum(dim_scores) / len(dim_scores)
                print(f"  {dim.capitalize()}: {avg_dim_score:.1f}%")

    print("\n" + "=" * 80)


def main():
    """Main demo execution."""
    print_header(RUBRIC)

    # Load conversation
    print(f"Loading conversation from conversation_{CONVERSATION_NUMBER}.json...")
    conversation = load_conversation(CONVERSATION_NUMBER)
    print(f"  Loaded conversation with {len(conversation)} turns\n")

    # Build user prompt
    user_prompt = build_user_prompt(conversation, RUBRIC)

    # Check for API keys
    print("Checking API keys...")
    available_vendors = []
    for vendor, config in MODEL_CONFIG.items():
        api_key = get_api_key(config["env_var"])
        if api_key:
            print(f"  ✓ {vendor.upper()}: API key found")
            available_vendors.append(vendor)
        else:
            print(f"  ✗ {vendor.upper()}: API key not found (set {config['env_var']})")

    if not available_vendors:
        print("\nNo API keys found. Please set at least one API key environment variable.")
        print("   Example: export OPENAI_API_KEY='your-key-here'")
        sys.exit(1)

    # Build task queue - run each model NUM_REPLICATIONS times
    tasks = []
    for vendor in available_vendors:
        config = MODEL_CONFIG[vendor]
        api_key = get_api_key(config["env_var"])
        for model in config["models"]:
            for run_number in range(1, NUM_REPLICATIONS + 1):
                tasks.append((vendor, model, config["class"], api_key, run_number))

    num_unique_models = sum(len(MODEL_CONFIG[v]["models"]) for v in available_vendors)
    print(f"\nTesting {num_unique_models} unique models × {NUM_REPLICATIONS} runs = {len(tasks)} total requests")
    print(f"Using {NUM_WORKERS} parallel workers...\n")

    # Run tests in parallel
    tracker = ProgressTracker(total=len(tasks))
    results = []
    start_time = time.time()

    with ThreadPoolExecutor(max_workers=NUM_WORKERS) as executor:
        # Submit all tasks
        future_to_task = {
            executor.submit(test_model, vendor, model, llm_class, api_key, tracker, user_prompt, RUBRIC, run_number): (vendor, model, run_number)
            for vendor, model, llm_class, api_key, run_number in tasks
        }

        # Collect results as they complete
        for future in as_completed(future_to_task):
            result = future.result()
            results.append(result)

    total_time = time.time() - start_time

    # Print summary
    print_summary(results, RUBRIC, total_time)


if __name__ == "__main__":
    main()
