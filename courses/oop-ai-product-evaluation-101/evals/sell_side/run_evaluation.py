"""
Run a complete evaluation of the intake agent.

This script:
1. Starts with a patient persona (ground truth)
2. Simulates a patient conversation using Playwright
3. Evaluates the extracted data against ground truth
4. Generates a report
"""

import os
import sys
import time
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from evals.sell_side.patient_simulator import PatientSimulator
from evals.sell_side.patient_personas import get_persona, list_personas
from evals.sell_side.evaluator import IntakeEvaluator
from intake_agent import database


def run_evaluation(persona_name: str, headless: bool = False, base_url: str = "http://localhost:5000"):
    """
    Run a complete evaluation cycle.

    Args:
        persona_name: Name of persona from patient_personas.py
        headless: Whether to run browser in headless mode
        base_url: Base URL of the application

    Returns:
        Evaluation results dictionary
    """
    print("\n" + "=" * 70)
    print(f"RUNNING EVALUATION: {persona_name}")
    print("=" * 70 + "\n")

    # Get API key
    api_key = os.environ.get('ANTHROPIC_API_KEY')
    if not api_key:
        print("Error: ANTHROPIC_API_KEY environment variable not set")
        sys.exit(1)

    # Load persona
    persona = get_persona(persona_name)
    print(f"Loaded persona: {persona['first_name']} {persona['last_name']}")
    print(f"Conditions: {len(persona.get('conditions', []))}")
    print(f"Medications: {len(persona.get('medications', []))}")
    print(f"Allergies: {len(persona.get('allergies', []))}")
    print(f"Goals: {len(persona.get('goals', []))}")

    # Get initial patient count to find the new patient
    initial_patients = database.get_all_patients()
    initial_count = len(initial_patients)
    print(f"\nCurrent patient count: {initial_count}")

    # Run simulation
    print("\n" + "-" * 70)
    print("Starting patient simulation...")
    print("-" * 70 + "\n")

    simulator = PatientSimulator(persona=persona, api_key=api_key, headless=headless)

    try:
        simulator.run_conversation(base_url=base_url, max_turns=20)
    except Exception as e:
        print(f"\nError during simulation: {e}")
        import traceback
        traceback.print_exc()
        return None

    # Find the new patient ID
    time.sleep(1)  # Give database a moment
    all_patients = database.get_all_patients()
    new_patients = [p for p in all_patients if p['id'] > (initial_patients[-1]['id'] if initial_patients else 0)]

    if not new_patients:
        print("\nError: Could not find newly created patient")
        return None

    patient_id = new_patients[0]['id']
    print(f"\n\nEvaluating patient ID: {patient_id}")

    # Run evaluation
    print("\n" + "-" * 70)
    print("Running evaluation...")
    print("-" * 70)

    evaluator = IntakeEvaluator(patient_id=patient_id, ground_truth=persona)
    results = evaluator.evaluate_all()
    evaluator.print_report()

    return results


def run_all_personas(headless: bool = True):
    """
    Run evaluation on all available personas.

    Args:
        headless: Whether to run browser in headless mode
    """
    personas = list_personas()
    print(f"\nRunning evaluations for {len(personas)} personas...")

    all_results = {}

    for persona_name in personas:
        results = run_evaluation(persona_name, headless=headless)
        if results:
            all_results[persona_name] = results
        print("\n" + "=" * 70 + "\n")
        time.sleep(2)  # Brief pause between runs

    # Summary report
    print("\n" + "=" * 70)
    print("SUMMARY REPORT")
    print("=" * 70 + "\n")

    for persona_name, results in all_results.items():
        print(f"{persona_name:30s} {results['overall_score']:.2%}")

    avg_score = sum(r['overall_score'] for r in all_results.values()) / len(all_results)
    print(f"\n{'Average':30s} {avg_score:.2%}")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Run intake agent evaluation")
    parser.add_argument("--persona", type=str, help="Persona name to evaluate (or 'all')")
    parser.add_argument("--headless", action="store_true", help="Run browser in headless mode")
    parser.add_argument("--url", type=str, default="http://localhost:5000", help="Base URL of application")
    parser.add_argument("--list", action="store_true", help="List available personas")

    args = parser.parse_args()

    if args.list:
        print("\nAvailable personas:")
        for name in list_personas():
            persona = get_persona(name)
            print(f"  - {name}: {persona['first_name']} {persona['last_name']}")
        sys.exit(0)

    if args.persona == "all":
        run_all_personas(headless=args.headless)
    else:
        persona_name = args.persona or "simple_hypertension"
        run_evaluation(persona_name, headless=args.headless, base_url=args.url)
