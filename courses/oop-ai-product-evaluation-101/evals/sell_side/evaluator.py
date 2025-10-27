"""
Evaluator for the intake agent.

Compares extracted medical information against ground truth persona.
"""

import sys
from pathlib import Path
from typing import Dict, List

# Add parent directory to path for intake_agent imports
sys.path.insert(0, str(Path(__file__).parent.parent))
from intake_agent import database


class IntakeEvaluator:
    """
    Evaluates intake agent performance by comparing extracted data
    against ground truth patient persona.
    """

    def __init__(self, patient_id: int, ground_truth: dict):
        """
        Initialize evaluator.

        Args:
            patient_id: ID of patient record in database
            ground_truth: Ground truth persona dictionary
        """
        self.patient_id = patient_id
        self.ground_truth = ground_truth
        self.results = {}

    def evaluate_demographics(self) -> dict:
        """Evaluate demographic information extraction."""
        patient = database.get_patient(self.patient_id)

        checks = {
            'first_name': patient.get('first_name') == self.ground_truth.get('first_name'),
            'last_name': patient.get('last_name') == self.ground_truth.get('last_name'),
            'date_of_birth': patient.get('date_of_birth') == self.ground_truth.get('date_of_birth'),
            'sex': patient.get('sex') == self.ground_truth.get('sex'),
            'gender': patient.get('gender') == self.ground_truth.get('gender'),
            'current_health_concerns': bool(patient.get('current_health_concerns'))  # Just check if captured
        }

        correct = sum(checks.values())
        total = len(checks)

        return {
            'score': correct / total if total > 0 else 0,
            'correct': correct,
            'total': total,
            'details': checks,
            'extracted': patient
        }

    def evaluate_conditions(self) -> dict:
        """Evaluate medical conditions extraction."""
        extracted = database.get_patient_conditions(self.patient_id)
        expected = self.ground_truth.get('conditions', [])

        extracted_names = {c['name'].lower() for c in extracted}
        expected_names = {c['name'].lower() for c in expected}

        true_positives = extracted_names & expected_names
        false_positives = extracted_names - expected_names
        false_negatives = expected_names - extracted_names

        precision = len(true_positives) / len(extracted_names) if extracted_names else 0
        recall = len(true_positives) / len(expected_names) if expected_names else 1
        f1 = 2 * (precision * recall) / (precision + recall) if (precision + recall) > 0 else 0

        return {
            'score': f1,
            'precision': precision,
            'recall': recall,
            'true_positives': list(true_positives),
            'false_positives': list(false_positives),
            'false_negatives': list(false_negatives),
            'extracted_count': len(extracted),
            'expected_count': len(expected)
        }

    def evaluate_medications(self) -> dict:
        """Evaluate medication extraction."""
        extracted = database.get_patient_medications(self.patient_id)
        expected = self.ground_truth.get('medications', [])

        extracted_names = {m['name'].lower() for m in extracted}
        expected_names = {m['name'].lower() for m in expected}

        true_positives = extracted_names & expected_names
        false_positives = extracted_names - expected_names
        false_negatives = expected_names - extracted_names

        precision = len(true_positives) / len(extracted_names) if extracted_names else 0
        recall = len(true_positives) / len(expected_names) if expected_names else 1
        f1 = 2 * (precision * recall) / (precision + recall) if (precision + recall) > 0 else 0

        # Check dose accuracy for matched medications
        dose_accuracy = []
        for ext_med in extracted:
            for exp_med in expected:
                if ext_med['name'].lower() == exp_med['name'].lower():
                    if exp_med.get('dose'):
                        dose_accuracy.append(ext_med.get('dose') == exp_med['dose'])

        avg_dose_accuracy = sum(dose_accuracy) / len(dose_accuracy) if dose_accuracy else 0

        return {
            'score': f1,
            'precision': precision,
            'recall': recall,
            'dose_accuracy': avg_dose_accuracy,
            'true_positives': list(true_positives),
            'false_positives': list(false_positives),
            'false_negatives': list(false_negatives),
            'extracted_count': len(extracted),
            'expected_count': len(expected)
        }

    def evaluate_allergies(self) -> dict:
        """Evaluate allergy extraction."""
        extracted = database.get_patient_allergies(self.patient_id)
        expected = self.ground_truth.get('allergies', [])

        extracted_names = {a['name'].lower() for a in extracted}
        expected_names = {a['name'].lower() for a in expected}

        true_positives = extracted_names & expected_names
        false_positives = extracted_names - expected_names
        false_negatives = expected_names - extracted_names

        precision = len(true_positives) / len(extracted_names) if extracted_names else 0
        recall = len(true_positives) / len(expected_names) if expected_names else 1
        f1 = 2 * (precision * recall) / (precision + recall) if (precision + recall) > 0 else 0

        return {
            'score': f1,
            'precision': precision,
            'recall': recall,
            'true_positives': list(true_positives),
            'false_positives': list(false_positives),
            'false_negatives': list(false_negatives),
            'extracted_count': len(extracted),
            'expected_count': len(expected)
        }

    def evaluate_goals(self) -> dict:
        """Evaluate health goals extraction."""
        extracted = database.get_patient_goals(self.patient_id)
        expected = self.ground_truth.get('goals', [])

        extracted_names = {g['name'].lower() for g in extracted}
        expected_names = {g['name'].lower() for g in expected}

        true_positives = extracted_names & expected_names
        false_positives = extracted_names - expected_names
        false_negatives = expected_names - extracted_names

        precision = len(true_positives) / len(extracted_names) if extracted_names else 0
        recall = len(true_positives) / len(expected_names) if expected_names else 1
        f1 = 2 * (precision * recall) / (precision + recall) if (precision + recall) > 0 else 0

        return {
            'score': f1,
            'precision': precision,
            'recall': recall,
            'true_positives': list(true_positives),
            'false_positives': list(false_positives),
            'false_negatives': list(false_negatives),
            'extracted_count': len(extracted),
            'expected_count': len(expected)
        }

    def evaluate_all(self) -> dict:
        """Run all evaluations and return comprehensive results."""
        self.results = {
            'demographics': self.evaluate_demographics(),
            'conditions': self.evaluate_conditions(),
            'medications': self.evaluate_medications(),
            'allergies': self.evaluate_allergies(),
            'goals': self.evaluate_goals()
        }

        # Calculate overall score (weighted average)
        weights = {
            'demographics': 0.25,
            'conditions': 0.20,
            'medications': 0.25,
            'allergies': 0.15,
            'goals': 0.15
        }

        overall_score = sum(
            self.results[key]['score'] * weights[key]
            for key in weights.keys()
        )

        self.results['overall_score'] = overall_score

        return self.results

    def print_report(self):
        """Print a formatted evaluation report."""
        if not self.results:
            self.evaluate_all()

        print("\n" + "=" * 70)
        print("INTAKE AGENT EVALUATION REPORT")
        print("=" * 70)

        print(f"\nOverall Score: {self.results['overall_score']:.2%}")
        print("\n" + "-" * 70)

        # Demographics
        demo = self.results['demographics']
        print(f"\nDEMOGRAPHICS: {demo['score']:.2%} ({demo['correct']}/{demo['total']} correct)")
        for field, correct in demo['details'].items():
            status = "✓" if correct else "✗"
            print(f"  {status} {field}")

        # Conditions
        cond = self.results['conditions']
        print(f"\nCONDITIONS: {cond['score']:.2%}")
        print(f"  Precision: {cond['precision']:.2%}, Recall: {cond['recall']:.2%}")
        print(f"  Extracted: {cond['extracted_count']}, Expected: {cond['expected_count']}")
        if cond['false_positives']:
            print(f"  False positives: {', '.join(cond['false_positives'])}")
        if cond['false_negatives']:
            print(f"  Missed: {', '.join(cond['false_negatives'])}")

        # Medications
        meds = self.results['medications']
        print(f"\nMEDICATIONS: {meds['score']:.2%}")
        print(f"  Precision: {meds['precision']:.2%}, Recall: {meds['recall']:.2%}")
        print(f"  Dose accuracy: {meds['dose_accuracy']:.2%}")
        print(f"  Extracted: {meds['extracted_count']}, Expected: {meds['expected_count']}")
        if meds['false_positives']:
            print(f"  False positives: {', '.join(meds['false_positives'])}")
        if meds['false_negatives']:
            print(f"  Missed: {', '.join(meds['false_negatives'])}")

        # Allergies
        allerg = self.results['allergies']
        print(f"\nALLERGIES: {allerg['score']:.2%}")
        print(f"  Precision: {allerg['precision']:.2%}, Recall: {allerg['recall']:.2%}")
        print(f"  Extracted: {allerg['extracted_count']}, Expected: {allerg['expected_count']}")
        if allerg['false_positives']:
            print(f"  False positives: {', '.join(allerg['false_positives'])}")
        if allerg['false_negatives']:
            print(f"  Missed: {', '.join(allerg['false_negatives'])}")

        # Goals
        goals = self.results['goals']
        print(f"\nGOALS: {goals['score']:.2%}")
        print(f"  Precision: {goals['precision']:.2%}, Recall: {goals['recall']:.2%}")
        print(f"  Extracted: {goals['extracted_count']}, Expected: {goals['expected_count']}")
        if goals['false_positives']:
            print(f"  False positives: {', '.join(goals['false_positives'])}")
        if goals['false_negatives']:
            print(f"  Missed: {', '.join(goals['false_negatives'])}")

        print("\n" + "=" * 70 + "\n")


if __name__ == "__main__":
    # Example usage
    from patient_personas import get_persona

    patient_id = 1  # Replace with actual patient ID from simulation
    persona = get_persona("simple_hypertension")

    evaluator = IntakeEvaluator(patient_id=patient_id, ground_truth=persona)
    evaluator.evaluate_all()
    evaluator.print_report()
