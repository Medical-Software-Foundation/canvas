#!/usr/bin/env python3
"""
Analyze all bilateral case results by comparing input cases with detected structured data.
Generates case_{n}_analysis.json files for each case with results.
"""

import json
from pathlib import Path
from typing import Dict, List, Any


def load_json(file_path: Path) -> Dict:
    """Load a JSON file."""
    with open(file_path, 'r', encoding='utf-8') as f:
        return json.load(f)


def save_json(data: Dict, file_path: Path):
    """Save data to JSON file."""
    with open(file_path, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def analyze_demographics(case: Dict, result: Dict) -> tuple[List[str], List[Dict]]:
    """Analyze patient demographics."""
    positive = []
    negative = []

    detected = result['structured_data_detected']['patient']

    # Name
    if detected.get('name') == case['patient_name']:
        positive.append(f"Patient name correctly extracted: '{case['patient_name']}'")
    else:
        negative.append({
            "severity": "critical",
            "issue": f"Patient name incorrect or missing. Expected '{case['patient_name']}', got '{detected.get('name', 'N/A')}'"
        })

    # DOB
    expected_dob = case['patient_dob']
    detected_dob = detected.get('dob', '')
    if expected_dob in detected_dob or detected_dob == expected_dob:
        positive.append(f"Date of birth correctly identified: {expected_dob}")
    else:
        negative.append({
            "severity": "high",
            "issue": f"Date of birth incorrect or missing. Expected '{expected_dob}', got '{detected_dob}'"
        })

    # Sex and Gender
    if detected.get('sex') == case['patient_sex'] and detected.get('gender') == case['patient_gender_identity']:
        positive.append(f"Sex and gender identity properly documented: {case['patient_sex']}/{case['patient_gender_identity']}")
    else:
        if detected.get('sex') != case['patient_sex']:
            negative.append({
                "severity": "high",
                "issue": f"Sex incorrect. Expected '{case['patient_sex']}', got '{detected.get('sex', 'N/A')}'"
            })
        if detected.get('gender') != case['patient_gender_identity']:
            negative.append({
                "severity": "moderate",
                "issue": f"Gender identity incorrect. Expected '{case['patient_gender_identity']}', got '{detected.get('gender', 'N/A')}'"
            })

    return positive, negative


def analyze_conditions(case: Dict, result: Dict) -> tuple[List[str], List[Dict]]:
    """Analyze conditions detection."""
    positive = []
    negative = []

    detected_conditions = result['structured_data_detected']['conditions']
    detected_names = [c.get('name', '').lower() for c in detected_conditions]

    # Parse expected conditions from case
    expected_conditions_str = case['conditions'].lower()

    # Key conditions to check (simplified parsing)
    key_conditions = []
    if 'diabetes' in expected_conditions_str or 'diabetic' in expected_conditions_str:
        key_conditions.append('diabetes')
    if 'hypertension' in expected_conditions_str or 'blood pressure' in expected_conditions_str:
        key_conditions.append('hypertension')
    if 'anxiety' in expected_conditions_str:
        key_conditions.append('anxiety')
    if 'asthma' in expected_conditions_str:
        key_conditions.append('asthma')
    if 'depression' in expected_conditions_str:
        key_conditions.append('depression')
    if 'arthritis' in expected_conditions_str:
        key_conditions.append('arthritis')
    if 'allerg' in expected_conditions_str and 'seasonal' in expected_conditions_str:
        key_conditions.append('allergies')
    if 'cancer' in expected_conditions_str or 'breast cancer' in expected_conditions_str:
        key_conditions.append('cancer')
    if 'heart failure' in expected_conditions_str or 'chf' in expected_conditions_str:
        key_conditions.append('heart failure')
    if 'hypothyroid' in expected_conditions_str:
        key_conditions.append('hypothyroid')
    if 'migraine' in expected_conditions_str:
        key_conditions.append('migraine')
    if 'adhd' in expected_conditions_str:
        key_conditions.append('adhd')

    # Check for detected key conditions
    for condition in key_conditions:
        found = any(condition in name for name in detected_names)
        if found:
            positive.append(f"Key condition detected: {condition}")
        else:
            negative.append({
                "severity": "critical",
                "issue": f"Key condition from case file not detected: {condition}"
            })

    # Check if we detected conditions
    if len(detected_conditions) > 0:
        positive.append(f"Total conditions documented: {len(detected_conditions)}")
    else:
        negative.append({
            "severity": "critical",
            "issue": "No conditions detected despite case file listing conditions"
        })

    return positive, negative


def analyze_medications(case: Dict, result: Dict) -> tuple[List[str], List[Dict]]:
    """Analyze medications detection."""
    positive = []
    negative = []

    detected_meds = result['structured_data_detected']['medications']
    detected_names = [m.get('name', '').lower() for m in detected_meds]

    # Parse expected medications
    expected_meds_str = case['medications'].lower()

    # Key medications to check
    key_meds = []
    if 'metformin' in expected_meds_str:
        key_meds.append('metformin')
    if 'lisinopril' in expected_meds_str:
        key_meds.append('lisinopril')
    if 'albuterol' in expected_meds_str:
        key_meds.append('albuterol')
    if 'claritin' in expected_meds_str or 'loratadine' in expected_meds_str:
        key_meds.append('claritin')
    if 'atorvastatin' in expected_meds_str or 'statin' in expected_meds_str:
        key_meds.append('statin')
    if 'warfarin' in expected_meds_str:
        key_meds.append('warfarin')
    if 'levothyroxine' in expected_meds_str:
        key_meds.append('levothyroxine')
    if 'tamoxifen' in expected_meds_str:
        key_meds.append('tamoxifen')
    if 'lexapro' in expected_meds_str or 'sertraline' in expected_meds_str:
        key_meds.append('antidepressant')
    if 'adderall' in expected_meds_str:
        key_meds.append('adderall')
    if 'testosterone' in expected_meds_str:
        key_meds.append('testosterone')

    # Check detected
    for med in key_meds:
        found = any(med in name for name in detected_names)
        if found:
            positive.append(f"Key medication detected: {med}")
        else:
            negative.append({
                "severity": "high",
                "issue": f"Key medication from case file not detected: {med}"
            })

    # Check for indications
    meds_with_indication = [m for m in detected_meds if 'indication' in m]
    if meds_with_indication:
        positive.append(f"Medication indications documented for {len(meds_with_indication)} medications")

    return positive, negative


def analyze_allergies(case: Dict, result: Dict) -> tuple[List[str], List[Dict]]:
    """Analyze allergies detection."""
    positive = []
    negative = []

    detected_allergies = result['structured_data_detected']['allergies']
    expected_allergies_str = case['allergies'].lower()

    # Check for specific allergies
    if 'no known' in expected_allergies_str or 'nkda' in expected_allergies_str:
        # Should document no allergies
        if any('no known' in a.get('name', '').lower() for a in detected_allergies):
            positive.append("Allergies correctly documented as 'No known drug allergies'")
        else:
            negative.append({
                "severity": "moderate",
                "issue": "Patient stated no known allergies but this was not clearly documented"
            })
    else:
        # Specific allergies should be detected
        if 'penicillin' in expected_allergies_str:
            if any('penicillin' in a.get('name', '').lower() for a in detected_allergies):
                positive.append("Penicillin allergy correctly documented")
            else:
                negative.append({
                    "severity": "critical",
                    "issue": "Penicillin allergy from case file not detected"
                })

        if 'sulfa' in expected_allergies_str:
            if any('sulfa' in a.get('name', '').lower() for a in detected_allergies):
                positive.append("Sulfa allergy correctly documented")
            else:
                negative.append({
                    "severity": "critical",
                    "issue": "Sulfa allergy from case file not detected"
                })

        if 'latex' in expected_allergies_str:
            if any('latex' in a.get('name', '').lower() for a in detected_allergies):
                positive.append("Latex allergy correctly documented")
            else:
                negative.append({
                    "severity": "critical",
                    "issue": "Latex allergy from case file not detected"
                })

        if 'codeine' in expected_allergies_str:
            if any('codeine' in a.get('name', '').lower() for a in detected_allergies):
                positive.append("Codeine allergy correctly documented")
            else:
                negative.append({
                    "severity": "critical",
                    "issue": "Codeine allergy from case file not detected"
                })

    return positive, negative


def analyze_goals(case: Dict, result: Dict) -> tuple[List[str], List[Dict]]:
    """Analyze goals detection."""
    positive = []
    negative = []

    detected_goals = result['structured_data_detected']['goals']
    expected_goals_str = case['goals'].lower()

    if not detected_goals or len(detected_goals) == 0:
        # No goals detected
        if expected_goals_str and len(expected_goals_str) > 20:
            negative.append({
                "severity": "critical",
                "issue": f"Goals completely missing from structured data despite being discussed in case. Expected goals related to: {case['goals'][:100]}..."
            })
        else:
            negative.append({
                "severity": "high",
                "issue": "No goals documented in structured data"
            })
    else:
        positive.append(f"Goals documented: {len(detected_goals)} goal(s) captured")

        # Check if goals make sense
        goals_text = ' '.join([g.get('name', '').lower() for g in detected_goals])

        # Some basic checks for goal content alignment
        if 'travel' in expected_goals_str and 'travel' not in goals_text:
            negative.append({
                "severity": "moderate",
                "issue": "Patient mentioned travel goals but this was not captured"
            })

    return positive, negative


def analyze_conversation(case: Dict, result: Dict) -> tuple[List[str], List[Dict]]:
    """Analyze conversation quality."""
    positive = []
    negative = []

    conversation = result['conversation']
    total_turns = result['metadata']['total_turns']

    # Basic conversation metrics
    positive.append(f"Total conversational turns: {total_turns}")

    if total_turns < 5:
        negative.append({
            "severity": "high",
            "issue": f"Very short conversation ({total_turns} turns) may indicate incomplete data gathering"
        })
    elif total_turns > 30:
        negative.append({
            "severity": "low",
            "issue": f"Very long conversation ({total_turns} turns) may indicate inefficiency or confusion"
        })
    else:
        positive.append("Appropriate conversation length for thorough data gathering")

    # Check for confirmation/summary
    agent_messages = [m['content'].lower() for m in conversation if m['role'] == 'agent']
    if any('confirm' in msg or 'accurate' in msg for msg in agent_messages):
        positive.append("Agent provided confirmation summary of collected information")

    return positive, negative


def analyze_case(case_number: str, cases_dir: Path) -> Dict:
    """Analyze a single case."""

    case_file = cases_dir / f"case_{case_number}.json"
    result_file = cases_dir / f"case_{case_number}_result.json"

    # Load files
    case = load_json(case_file)
    result = load_json(result_file)

    # Collect all positive and negative observations
    all_positive = []
    all_negative = []

    # Analyze each aspect
    pos, neg = analyze_demographics(case, result)
    all_positive.extend(pos)
    all_negative.extend(neg)

    pos, neg = analyze_conditions(case, result)
    all_positive.extend(pos)
    all_negative.extend(neg)

    pos, neg = analyze_medications(case, result)
    all_positive.extend(pos)
    all_negative.extend(neg)

    pos, neg = analyze_allergies(case, result)
    all_positive.extend(pos)
    all_negative.extend(neg)

    pos, neg = analyze_goals(case, result)
    all_positive.extend(pos)
    all_negative.extend(neg)

    pos, neg = analyze_conversation(case, result)
    all_positive.extend(pos)
    all_negative.extend(neg)

    return {
        "positive": all_positive,
        "negative": all_negative
    }


def main():
    """Main function to analyze all cases."""
    script_dir = Path(__file__).parent
    cases_dir = script_dir / "cases_bilateral"

    # Find all result files
    result_files = sorted(cases_dir.glob("case_*_result.json"))

    print("=" * 70)
    print("  Bilateral Cases Analysis")
    print("=" * 70)
    print()

    for result_file in result_files:
        # Extract case number
        case_number = result_file.stem.replace("case_", "").replace("_result", "")

        # Skip if not a simple number
        if not case_number.isdigit():
            continue

        print(f"Analyzing case {case_number}...")

        try:
            analysis = analyze_case(case_number, cases_dir)

            # Save analysis
            analysis_file = cases_dir / f"case_{case_number}_analysis.json"
            save_json(analysis, analysis_file)

            print(f"  ✅ Saved: {analysis_file.name}")
            print(f"     Positive observations: {len(analysis['positive'])}")
            print(f"     Negative observations: {len(analysis['negative'])}")

            # Show critical issues
            critical = [n for n in analysis['negative'] if n['severity'] == 'critical']
            if critical:
                print(f"     🚨 Critical issues: {len(critical)}")

            print()

        except Exception as e:
            print(f"  ❌ Error: {e}")
            print()

    print("=" * 70)
    print("Analysis complete!")
    print("=" * 70)


if __name__ == "__main__":
    main()
