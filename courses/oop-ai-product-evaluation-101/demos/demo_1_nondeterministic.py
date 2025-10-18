#!/usr/bin/env python3
"""
Demo 1: Nondeterministic LLM Outputs

This script demonstrates the variability in LLM outputs across different vendors
and models when given the same prompt. We ask each model to recommend medications
for hypertension and compare the results.

Usage:
    python demos/demo_1_nondeterministic.py
    # or
    uv run python demos/demo_1_nondeterministic.py
"""

from __future__ import annotations

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

NUM_WORKERS = 6  # Number of parallel workers for ThreadPoolExecutor
NUM_REPLICATIONS = 3  # Number of times to run each model


# ============================================================================
# PROMPT AND JSON SCHEMA
# ============================================================================

SYSTEM_PROMPT = """You are a clinical decision support assistant.
You provide evidence-based medication recommendations for common medical conditions.
You must respond with valid JSON in a markdown code block."""

USER_PROMPT = """What are the 5 most appropriate medications, in order of appropriateness, for a patient with hypertension?

Please respond with a JSON object following this exact schema:

```json
{
  "condition": "hypertension",
  "medications": [
    {
      "drug": "medication name",
      "dose": "dose with unit (e.g., 10mg, 5mg)",
      "form": "medication form (e.g., tablet, capsule)"
    }
  ]
}
```

Provide exactly 5 medications in your response. Be specific with doses and forms."""


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


def test_model(vendor: str, model: str, llm_class, api_key: str, tracker: ProgressTracker, run_number: int = 1) -> dict:
    """Test a single model and return results."""
    tracker.start_task(vendor, model)

    try:
        llm = llm_class(api_key=api_key, model=model)
        start_time = time.time()
        result = llm.chat_with_json(
            system_prompt=SYSTEM_PROMPT,
            user_prompt=USER_PROMPT,
            max_retries=3,
        )
        elapsed_time = time.time() - start_time

        if result["success"]:
            medications = result["data"].get("medications", [])
            # Create display names: "{dose} {drug} {form}"
            med_display_names = []
            for med in medications:
                drug = med.get("drug", "Unknown")
                dose = med.get("dose", "")
                form = med.get("form", "")
                display_name = f"{dose} {drug} {form}".strip()
                med_display_names.append(display_name)

            tracker.complete_task(vendor, model, True, elapsed_time)

            return {
                "vendor": vendor,
                "model": model,
                "run_number": run_number,
                "success": True,
                "medications": med_display_names,
                "num_medications": len(medications),
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
                "medications": [],
                "num_medications": 0,
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
            "medications": [],
            "num_medications": 0,
            "elapsed_time": 0,
            "error": str(e),
        }


def print_header():
    """Print demo header."""
    print("=" * 80)
    print("DEMO 1: Nondeterministic LLM Outputs")
    print("=" * 80)
    print()
    print("Testing: Medication recommendations for hypertension")
    print("Expected: 5 medications per model")
    print()


def print_summary(results: list[dict], total_time: float = None):
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

        # Create ASCII table for successful results (3 columns: Model | Rank | Medication)
        print(f"Medication Recommendations by Model ({NUM_REPLICATIONS} runs each):\n")
        print("(Rows in red indicate variation across replications)\n")

        # Determine max medications
        max_meds = 5  # We expect 5 medications

        # Calculate column widths
        model_col_width = 30  # Width for model name column
        rank_col_width = 6    # Width for rank column
        med_col_width = 50    # Width for medication column

        # Print header row
        header = f" {'Model':^{model_col_width}} | {'Rank':^{rank_col_width}} | {'Medication':^{med_col_width}} |"
        print(header)

        # Print separator
        separator = f"-{'-' * model_col_width}-+-{'-' * rank_col_width}-+-{'-' * med_col_width}-+"
        print(separator)

        # Print each model with 5 rows (one per rank), sorted by model name
        for model_key, model_runs in sorted(model_results.items()):
            vendor = model_runs[0]["vendor"]
            model = model_runs[0]["model"]
            model_short = model.split("/")[-1]
            vendor_short = vendor[:3].upper()
            model_name = f"{vendor_short}/{model_short}"

            # Truncate model name if too long
            if len(model_name) > model_col_width:
                model_name = model_name[:model_col_width-3] + "..."

            # Print 5 rows (one per rank) for this model
            for rank_idx in range(max_meds):
                # Collect unique medications across runs for this rank
                unique_meds = []
                for run in model_runs:
                    if rank_idx < len(run["medications"]):
                        med = run["medications"][rank_idx].strip()
                        # Only add if not already in list (case-insensitive comparison)
                        if not any(m.lower() == med.lower() for m in unique_meds):
                            unique_meds.append(med)

                # Format medication display
                if unique_meds:
                    if len(unique_meds) == 1:
                        med_display = unique_meds[0]
                    else:
                        # Show all variants separated by " | "
                        med_display = " | ".join(unique_meds)

                    # Truncate if too long
                    if len(med_display) > med_col_width:
                        med_display = med_display[:med_col_width-3] + "..."
                else:
                    med_display = ""

                # Build the row
                rank_display = str(rank_idx + 1)
                row = f" {model_name:<{model_col_width}} | {rank_display:^{rank_col_width}} | {med_display:<{med_col_width}} |"

                # Apply red color to entire row if there are multiple unique meds
                if len(unique_meds) > 1:
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
            print(f"  ✓ {vendor_short}/{model_short}: {avg_time:.2f}s (avg of {len(model_runs)} runs)")

    if failed:
        print(f"\n\nFailed Models ({len(failed)}):")
        print("-" * 80)
        for result in failed:
            model_short = result["model"].split("/")[-1]
            vendor_short = result["vendor"][:3].upper()
            error_preview = result["error"][:60] + "..." if len(result["error"]) > 60 else result["error"]
            print(f"  ✗ {vendor_short}/{model_short}: {error_preview}")

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
            # For each rank, check if there are multiple unique medications across runs
            for rank_idx in range(5):  # Check all 5 ranks
                unique_meds = []
                for run in model_runs:
                    if rank_idx < len(run["medications"]):
                        med = run["medications"][rank_idx].strip()
                        if not any(m.lower() == med.lower() for m in unique_meds):
                            unique_meds.append(med)

                # If this rank has variation, mark this model as nondeterministic
                if len(unique_meds) > 1:
                    if model_key not in nondeterministic_models:
                        nondeterministic_models.append(model_key)
                    break  # No need to check other ranks for this model

        if nondeterministic_models:
            print(f"\nNONDETERMINISM DETECTED: {len(nondeterministic_models)} model(s) returned different medications across runs")
            for model_key in nondeterministic_models:
                vendor = model_key.split("/")[0]
                model_short = model_key.split("/")[1].split("/")[-1]
                vendor_short = vendor[:3].upper()
                print(f"  - {vendor_short}/{model_short}")
        else:
            print(f"\nAll models were deterministic across {NUM_REPLICATIONS} runs")

    # Common medications across all successful responses
    if successful:
        from collections import Counter

        all_medications = []
        for result in successful:
            all_medications.extend(result["medications"])

        med_counts = Counter(all_medications)
        print(f"\nMost common medications (across {len(successful)} successful responses):")
        for med, count in med_counts.most_common(5):
            percentage = (count / len(successful)) * 100
            print(f"  • {med}: {count}/{len(successful)} ({percentage:.0f}%)")

    print("\n" + "=" * 80)


def main():
    """Main demo execution."""
    print_header()

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
        print("\n❌ No API keys found. Please set at least one API key environment variable.")
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
            executor.submit(test_model, vendor, model, llm_class, api_key, tracker, run_number): (vendor, model, run_number)
            for vendor, model, llm_class, api_key, run_number in tasks
        }

        # Collect results as they complete
        for future in as_completed(future_to_task):
            result = future.result()
            results.append(result)

    total_time = time.time() - start_time

    # Print summary
    print_summary(results, total_time)


if __name__ == "__main__":
    main()
