#!/usr/bin/env python3
"""
Buyer-Side Conversation Replay Script

This script replays a conversation with the intake agent from a buyer's perspective.
It operates purely through the web interface using browser automation - no server
or database access required.

Usage:
    1. Start the intake agent Flask app manually: python intake_agent/app.py
    2. Run this script: python evals/buy_side/run_case.py <case_number>
    3. Find the output in: evals/buy_side/cases/case_{n}_{timestamp}.html

Examples:
    python evals/buy_side/run_case.py 1
    python evals/buy_side/run_case.py 2
"""

import sys
import argparse
import json
from pathlib import Path
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout
import time
from datetime import datetime
import re
from html.parser import HTMLParser

# Configuration
BASE_URL = "http://127.0.0.1:5000"
MESSAGE_TIMEOUT = 60000  # 60 seconds max wait for agent response


def load_transcript(transcript_path: Path) -> dict:
    """
    Load transcript file (JSON format).

    Returns:
        dict with keys: case_number, created_timestamp, case_name, case_description, messages
    """
    with open(transcript_path, 'r', encoding='utf-8') as f:
        data = json.load(f)

    # Validate required fields
    required_fields = ['case_number', 'created_timestamp', 'case_name', 'case_description', 'messages']
    for field in required_fields:
        if field not in data:
            raise ValueError(f"Transcript missing required field: {field}")

    return data


def wait_for_agent_response(page, timeout: int = MESSAGE_TIMEOUT) -> bool:
    """
    Wait for the agent to send a response message.
    Returns True if response received, False if timeout.
    """
    try:
        # Wait for a new agent message to appear in the chat
        # Agent messages have class 'message-agent'
        page.wait_for_selector('.message-agent', timeout=timeout)

        # Also wait for the typing indicator to disappear (agent is done typing)
        page.wait_for_selector('#typing-indicator', state='hidden', timeout=timeout)

        return True
    except PlaywrightTimeout:
        print("  ⚠️  Warning: Timeout waiting for agent response")
        return False


def send_message(page, message: str) -> bool:
    """
    Send a patient message through the browser interface.
    Returns True if sent successfully.
    """
    try:
        # Find the textarea input
        input_field = page.locator('#message-input')

        # Type the message
        input_field.fill(message)

        # Click the send button
        send_button = page.locator('#send-button')
        send_button.click()

        # Small delay to ensure message is sent
        time.sleep(0.5)

        return True
    except Exception as e:
        print(f"  ❌ Error sending message: {e}")
        return False


def replay_conversation(base_url: str, messages: list[str]) -> str:
    """
    Replay the conversation using browser automation.
    Returns the final HTML content.
    """
    print("🎬 Starting conversation replay...\n")

    with sync_playwright() as p:
        # Launch browser (headless=False to see what's happening)
        print("🌐 Launching browser...")
        browser = p.chromium.launch(headless=False)
        page = browser.new_page()

        try:
            # Navigate to new patient intake
            print(f"📍 Navigating to {base_url}/patient/new")
            page.goto(f"{base_url}/patient/new")

            # Wait for the page to load and the greeting to appear
            print("⏳ Waiting for agent greeting...")
            page.wait_for_selector('.message-agent', timeout=30000)
            print("✅ Agent greeting received\n")

            # Send each patient message
            for i, message in enumerate(messages, 1):
                print(f"📤 [{i}/{len(messages)}] Patient: {message[:50]}...")

                if not send_message(page, message):
                    print(f"  ❌ Failed to send message {i}")
                    continue

                print("  ⏳ Waiting for agent response...")

                # Wait for agent to respond
                if wait_for_agent_response(page):
                    # Get the last agent message for logging
                    agent_messages = page.locator('.message-agent .message-bubble').all_text_contents()
                    if agent_messages:
                        last_response = agent_messages[-1]
                        preview = last_response[:80].replace('\n', ' ')
                        print(f"  ✅ Agent: {preview}...\n")
                else:
                    print("  ⚠️  Proceeding despite timeout\n")

                # Brief pause between messages for more natural interaction
                time.sleep(1)

            print("✅ All messages sent!")
            print("⏳ Waiting 3 seconds for final updates to render...\n")
            time.sleep(3)

            # Get the final HTML content
            print("💾 Capturing final page HTML...")
            html_content = page.content()

            print("✅ Replay complete!\n")
            return html_content

        except Exception as e:
            print(f"\n❌ Error during replay: {e}")
            raise
        finally:
            browser.close()


def save_html(html_content: str, output_path: Path):
    """Save the captured HTML to a file."""
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(html_content)
    print(f"💾 HTML saved to: {output_path}")


def extract_medical_record_data(html_content: str) -> dict:
    """
    Extract structured medical record data from the HTML.
    Returns a dictionary with patient info, conditions, medications, allergies, goals.
    """
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html_content, 'html.parser')
    data = {
        'patient': {},
        'conditions': [],
        'medications': [],
        'allergies': [],
        'goals': []
    }

    # Extract patient header info
    header = soup.find('div', class_='record-header')
    if header:
        h2 = header.find('h2')
        if h2:
            data['patient']['name'] = h2.get_text(strip=True)

        header_info = header.find('div', class_='record-header-info')
        if header_info:
            info_text = header_info.get_text()
            # Extract DOB, Age, Sex/Gender
            dob_match = re.search(r'DOB:\s*(\S+)', info_text)
            age_match = re.search(r'Age:\s*(\S+)', info_text)
            sex_gender_match = re.search(r'(\w+)\|(\w+)', info_text)

            if dob_match:
                data['patient']['dob'] = dob_match.group(1)
            if age_match:
                data['patient']['age'] = age_match.group(1)
            if sex_gender_match:
                data['patient']['sex'] = sex_gender_match.group(1)
                data['patient']['gender'] = sex_gender_match.group(2)

    # Extract conditions
    sections = soup.find_all('div', class_='record-section')
    for section in sections:
        title = section.find('div', class_='section-title')
        if not title:
            continue

        title_text = title.get_text(strip=True)

        if 'Conditions' in title_text:
            for item in section.find_all('div', class_='record-item'):
                condition = {}
                name_div = item.find('div', class_='item-name')
                if name_div:
                    # Extract name without status badge
                    badge = name_div.find('span', class_='status-badge')
                    if badge:
                        condition['status'] = badge.get_text(strip=True)
                        badge.extract()
                    condition['name'] = name_div.get_text(strip=True)

                # Extract comment/details
                details = item.find_all('div', class_='item-detail')
                if details:
                    condition['details'] = [d.get_text(strip=True) for d in details]

                data['conditions'].append(condition)

        elif 'Medications' in title_text:
            for item in section.find_all('div', class_='record-item'):
                medication = {}
                name_div = item.find('div', class_='item-name')
                if name_div:
                    medication['name'] = name_div.get_text(strip=True)

                # Extract all details (dose/form, sig, indication)
                details = item.find_all('div', class_='item-detail')
                medication['details'] = []
                for detail in details:
                    text = detail.get_text(strip=True)
                    medication['details'].append(text)

                    # Try to parse specific fields
                    if 'For:' in text:
                        medication['indication'] = text.replace('For:', '').strip()
                    elif re.search(r'\d+\s*mg', text, re.IGNORECASE):
                        medication['dose_form'] = text
                    elif any(word in text.lower() for word in ['daily', 'twice', 'once', 'morning', 'evening']):
                        medication['sig'] = text

                data['medications'].append(medication)

        elif 'Allergies' in title_text:
            for item in section.find_all('div', class_='record-item'):
                allergy = {}
                name_div = item.find('div', class_='item-name')
                if name_div:
                    allergy['name'] = name_div.get_text(strip=True)

                details = item.find_all('div', class_='item-detail')
                if details:
                    allergy['details'] = [d.get_text(strip=True) for d in details]

                data['allergies'].append(allergy)

        elif 'Goals' in title_text:
            for item in section.find_all('div', class_='record-item'):
                goal = {}
                name_div = item.find('div', class_='item-name')
                if name_div:
                    goal['name'] = name_div.get_text(strip=True)

                details = item.find_all('div', class_='item-detail')
                if details:
                    goal['details'] = [d.get_text(strip=True) for d in details]

                data['goals'].append(goal)

    return data


def analyze_data_quality(data: dict, case_num: int) -> dict:
    """
    Analyze the extracted data for quality issues.
    Returns a dictionary with findings and scores.
    """
    findings = {
        'critical_issues': [],
        'warnings': [],
        'observations': [],
        'scores': {}
    }

    # Check for duplicate conditions
    condition_names = [c['name'].lower() for c in data['conditions']]
    if len(condition_names) != len(set(condition_names)):
        findings['critical_issues'].append(
            "DUPLICATE CONDITIONS: Multiple entries with same/similar names detected"
        )

    # Check for semantic duplicates (e.g., "back pain" vs "lower back pain")
    for i, name1 in enumerate(condition_names):
        for name2 in condition_names[i+1:]:
            if name1 in name2 or name2 in name1:
                findings['critical_issues'].append(
                    f"POTENTIAL DUPLICATE: '{name1}' and '{name2}' may be the same condition"
                )

    # Check medication completeness
    incomplete_meds = []
    for med in data['medications']:
        issues = []
        if 'indication' not in med:
            issues.append("missing indication")
        if 'dose_form' not in med:
            issues.append("missing dose/form")
        if 'sig' not in med:
            issues.append("missing instructions")

        if issues:
            incomplete_meds.append(f"{med['name']}: {', '.join(issues)}")

    if incomplete_meds:
        findings['critical_issues'].append(
            "INCOMPLETE MEDICATION DATA:\n  - " + "\n  - ".join(incomplete_meds)
        )

    # Check for duplicate allergies
    allergy_names = [a['name'].lower() for a in data['allergies']]
    if len(allergy_names) != len(set(allergy_names)):
        findings['critical_issues'].append(
            "DUPLICATE ALLERGIES: Multiple entries for same allergen"
        )

    # Check for similar allergy names (e.g., "penicillin" vs "penicillins")
    for i, name1 in enumerate(allergy_names):
        for name2 in allergy_names[i+1:]:
            if name1 in name2 or name2 in name1:
                findings['critical_issues'].append(
                    f"POTENTIAL DUPLICATE ALLERGY: '{name1}' and '{name2}'"
                )

    # Check empty sections
    if not data['conditions']:
        findings['warnings'].append("No conditions recorded")
    if not data['medications']:
        findings['warnings'].append("No medications recorded")
    if not data['allergies']:
        findings['warnings'].append("No allergies recorded (not explicitly confirmed as 'none')")
    if not data['goals']:
        findings['warnings'].append("No goals recorded")

    # Calculate scores
    total_fields = 0
    complete_fields = 0

    # Medication completeness score
    for med in data['medications']:
        total_fields += 4  # name, dose/form, sig, indication
        complete_fields += 1  # name always present
        if 'dose_form' in med:
            complete_fields += 1
        if 'sig' in med:
            complete_fields += 1
        if 'indication' in med:
            complete_fields += 1

    if total_fields > 0:
        findings['scores']['medication_completeness'] = round((complete_fields / total_fields) * 100, 1)
    else:
        findings['scores']['medication_completeness'] = 0

    # Data quality score
    duplicate_penalty = len([i for i in findings['critical_issues'] if 'DUPLICATE' in i]) * 20
    incomplete_penalty = len([i for i in findings['critical_issues'] if 'INCOMPLETE' in i or 'MISSING' in i]) * 15
    findings['scores']['data_quality'] = max(0, 100 - duplicate_penalty - incomplete_penalty)

    return findings


def generate_analysis_report(case_num: int, data: dict, findings: dict, timestamp: str, transcript_data: dict = None) -> str:
    """Generate a markdown analysis report."""

    report = f"""# Case {case_num} Analysis Report

Generated: {timestamp}

"""

    # Add case metadata if available
    if transcript_data:
        report += f"""## Case Information

**Case Name:** {transcript_data['case_name']}
**Description:** {transcript_data['case_description']}
**Created:** {transcript_data['created_timestamp']}

---

"""

    report += f"""## Summary

**Patient:** {data['patient'].get('name', 'Not recorded')}
**Conditions:** {len(data['conditions'])}
**Medications:** {len(data['medications'])}
**Allergies:** {len(data['allergies'])}
**Goals:** {len(data['goals'])}

## Quality Scores

- **Medication Completeness:** {findings['scores'].get('medication_completeness', 0)}%
- **Data Quality:** {findings['scores'].get('data_quality', 0)}%

---

## Critical Issues

"""

    if findings['critical_issues']:
        for issue in findings['critical_issues']:
            report += f"### 🚨 {issue}\n\n"
    else:
        report += "✅ No critical issues detected\n\n"

    report += "---\n\n## Warnings\n\n"

    if findings['warnings']:
        for warning in findings['warnings']:
            report += f"- ⚠️ {warning}\n"
    else:
        report += "✅ No warnings\n"

    report += "\n---\n\n## Detailed Data Extraction\n\n"

    # Conditions
    report += "### Conditions\n\n"
    if data['conditions']:
        for cond in data['conditions']:
            report += f"- **{cond['name']}**"
            if 'status' in cond:
                report += f" ({cond['status']})"
            if 'details' in cond:
                report += f"\n  - Details: {', '.join(cond['details'])}"
            report += "\n"
    else:
        report += "_None recorded_\n"

    # Medications
    report += "\n### Medications\n\n"
    if data['medications']:
        for med in data['medications']:
            report += f"- **{med['name']}**\n"
            if 'dose_form' in med:
                report += f"  - Dose/Form: {med['dose_form']}\n"
            else:
                report += f"  - ❌ Dose/Form: MISSING\n"

            if 'sig' in med:
                report += f"  - Instructions: {med['sig']}\n"
            else:
                report += f"  - ❌ Instructions: MISSING\n"

            if 'indication' in med:
                report += f"  - Indication: {med['indication']}\n"
            else:
                report += f"  - ❌ Indication: MISSING\n"
    else:
        report += "_None recorded_\n"

    # Allergies
    report += "\n### Allergies\n\n"
    if data['allergies']:
        for allergy in data['allergies']:
            report += f"- **{allergy['name']}**"
            if 'details' in allergy:
                report += f"\n  - Details: {', '.join(allergy['details'])}"
            report += "\n"
    else:
        report += "_None recorded_\n"

    # Goals
    report += "\n### Goals\n\n"
    if data['goals']:
        for goal in data['goals']:
            report += f"- **{goal['name']}**"
            if 'details' in goal:
                report += f"\n  - Details: {', '.join(goal['details'])}"
            report += "\n"
    else:
        report += "_None recorded_\n"

    report += "\n---\n\n## Buyer's Verdict\n\n"

    quality_score = findings['scores'].get('data_quality', 0)
    if quality_score >= 90:
        verdict = "✅ **ACCEPTABLE** - High data quality"
    elif quality_score >= 70:
        verdict = "⚠️ **NEEDS IMPROVEMENT** - Moderate data quality issues"
    else:
        verdict = "🚨 **UNACCEPTABLE** - Critical data quality issues"

    report += verdict + "\n"

    return report


def main():
    """Main execution function."""
    # Parse command line arguments
    parser = argparse.ArgumentParser(
        description="Replay a test case conversation with the intake agent",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python evals/buy_side/run_case.py 1    # Run case 1
  python evals/buy_side/run_case.py 2    # Run case 2
        """
    )
    parser.add_argument(
        'case_number',
        type=int,
        help='Case number to run (e.g., 1 for case_1_transcript.txt)'
    )
    args = parser.parse_args()

    case_num = args.case_number

    print("=" * 70)
    print(f"  Buyer-Side Intake Agent Case {case_num} Replay")
    print("=" * 70)
    print()

    # Construct file paths
    script_dir = Path(__file__).parent
    cases_dir = script_dir / "cases"
    transcript_file = cases_dir / f"case_{case_num}_transcript.json"

    # Check that transcript file exists
    if not transcript_file.exists():
        print(f"❌ Error: Transcript file not found: {transcript_file}")
        print(f"   Please create: cases/case_{case_num}_transcript.json")
        print()
        print("Available cases:")
        for transcript in sorted(cases_dir.glob("case_*_transcript.json")):
            case_name = transcript.stem.replace("_transcript", "")
            print(f"  - {case_name}")
        sys.exit(1)

    # Load transcript
    print(f"📄 Loading transcript: {transcript_file.name}")
    transcript_data = load_transcript(transcript_file)
    messages = transcript_data['messages']

    print(f"✅ Case: {transcript_data['case_name']}")
    print(f"   Description: {transcript_data['case_description']}")
    print(f"   Messages: {len(messages)}\n")

    # Generate ISO timestamp for output filename
    timestamp = datetime.now().isoformat(timespec='seconds').replace(':', '-')
    output_file = cases_dir / f"case_{case_num}_{timestamp}.html"

    # Check that the app is running
    print(f"🔍 Checking if intake app is running at {BASE_URL}...")
    try:
        import requests
        response = requests.get(BASE_URL, timeout=5)
        print(f"✅ App is running (status: {response.status_code})\n")
    except Exception as e:
        print(f"❌ Error: Cannot connect to {BASE_URL}")
        print("   Please start the intake app first:")
        print("   > python intake_agent/app.py")
        sys.exit(1)

    # Replay the conversation
    try:
        html_content = replay_conversation(BASE_URL, messages)

        # Save the HTML output
        save_html(html_content, output_file)

        # Analyze the HTML output
        print("🔍 Analyzing data quality...\n")

        try:
            data = extract_medical_record_data(html_content)
            findings = analyze_data_quality(data, case_num)

            # Generate analysis report
            analysis_report = generate_analysis_report(case_num, data, findings, timestamp, transcript_data)

            # Save analysis report
            analysis_file = cases_dir / f"case_{case_num}_analysis_{timestamp}.md"
            with open(analysis_file, 'w', encoding='utf-8') as f:
                f.write(analysis_report)

            print(f"📊 Analysis saved to: {analysis_file.relative_to(script_dir.parent.parent)}\n")

            # Print summary
            print("=" * 70)
            print("  ANALYSIS SUMMARY")
            print("=" * 70)
            print(f"\nQuality Scores:")
            print(f"  • Medication Completeness: {findings['scores'].get('medication_completeness', 0)}%")
            print(f"  • Data Quality: {findings['scores'].get('data_quality', 0)}%")

            if findings['critical_issues']:
                print(f"\n🚨 Critical Issues: {len(findings['critical_issues'])}")
                for issue in findings['critical_issues'][:3]:  # Show first 3
                    print(f"  • {issue.split(':')[0]}")
                if len(findings['critical_issues']) > 3:
                    print(f"  ... and {len(findings['critical_issues']) - 3} more")

            if findings['warnings']:
                print(f"\n⚠️  Warnings: {len(findings['warnings'])}")

        except ImportError:
            print("⚠️  Warning: beautifulsoup4 not installed, skipping HTML analysis")
            print("   Install with: uv add beautifulsoup4")
            analysis_file = None
        except Exception as e:
            print(f"⚠️  Warning: Analysis failed: {e}")
            analysis_file = None

        print("\n" + "=" * 70)
        print("✅ SUCCESS!")
        print("=" * 70)
        print(f"\nFiles generated:")
        print(f"  • HTML: {output_file.relative_to(script_dir.parent.parent)}")
        if analysis_file:
            print(f"  • Analysis: {analysis_file.relative_to(script_dir.parent.parent)}")

        print("\nYou can now:")
        print(f"  1. Open the HTML file in a browser to review the interaction")
        if analysis_file:
            print(f"  2. Read the analysis report for data quality findings")
        print(f"  3. Compare with other timestamped runs to check consistency")

    except Exception as e:
        print("\n" + "=" * 70)
        print("❌ FAILED")
        print("=" * 70)
        print(f"\nError: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
