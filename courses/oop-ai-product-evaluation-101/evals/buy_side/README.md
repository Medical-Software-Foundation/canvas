# Buy-Side Evaluation Tools

This directory contains tools and analysis for evaluating the intake agent from a **buyer's perspective** - operating purely through the web interface with no access to server internals or databases.

## Directory Structure

```
buy_side/
├── README.md                # This file
├── run_case.py              # Script to replay and analyze test cases
└── cases/                   # Test case files
    ├── case_1.html          # Original Case 1 HTML snapshot (baseline)
    ├── case_1_transcript.json # Case 1 transcript (JSON format)
    ├── case_1_2025-10-27T12-17-52.html         # Timestamped HTML output
    ├── case_1_analysis_2025-10-27T12-17-52.md  # Automated analysis report
    ├── case_2_transcript.json # Case 2: Testing medication completeness
    └── ...                   # Additional cases
```

## Files

- **`run_case.py`** - Automated script to replay conversations through the browser
- **`cases/`** - Directory containing all test cases and their outputs
  - **`case_{n}.html`** - Original test case HTML snapshot (baseline)
  - **`case_{n}_transcript.json`** - Test case transcript in JSON format (see format below)
  - **`case_{n}_analysis.md`** - Manual analysis (for case 1 only, identifying issues/themes)
  - **`case_{n}_{timestamp}.html`** - Timestamped HTML output from script runs
  - **`case_{n}_analysis_{timestamp}.md`** - Timestamped automated analysis reports

### Transcript JSON Format

Each transcript file must be valid JSON with the following structure:

```json
{
  "case_number": 1,
  "created_timestamp": "2025-10-27T12:00:00-07:00",
  "case_name": "Baseline Duplicate Detection",
  "case_description": "Tests for duplicate conditions and missing data fields",
  "messages": [
    "patient message 1",
    "patient message 2",
    "..."
  ]
}
```

**Required Fields:**
- `case_number` (int) - The case number
- `created_timestamp` (string) - ISO 8601 timestamp with timezone (e.g., "2025-10-27T12:00:00-07:00")
- `case_name` (string) - Short descriptive name
- `case_description` (string) - Detailed description of what this case tests
- `messages` (array of strings) - Patient messages in order

## Usage

### 1. Setup

Install dependencies and Playwright browsers:

```bash
# Install Python dependencies
uv sync

# Install Playwright browsers (first time only)
playwright install chromium
```

### 2. Start the Intake Agent

In one terminal, start the Flask app:

```bash
cd intake_agent
python app.py
```

The app should be running at `http://127.0.0.1:5000`

### 3. Run a Test Case

In another terminal, run the test case by number:

```bash
# Run case 1
python evals/buy_side/run_case.py 1

# Run case 2 (when created)
python evals/buy_side/run_case.py 2
```

This will:
1. Read patient messages from `cases/case_{n}_transcript.json`
2. Open a browser window (visible, not headless)
3. Navigate to create a new patient
4. Send each message and wait for agent responses
5. Save the final HTML to `cases/case_{n}_{timestamp}.html`
6. **Analyze the HTML output for data quality issues**
7. **Generate analysis report:** `cases/case_{n}_analysis_{timestamp}.md` (includes case metadata)

### 4. Review Analysis Report

The script automatically generates a data quality analysis report that checks for:

**Critical Issues:**
- Duplicate conditions (exact and semantic matches)
- Duplicate allergies (e.g., "penicillin" vs "penicillins")
- Incomplete medication data (missing dose/form, instructions, indication)

**Quality Scores:**
- Medication Completeness % - tracks if all required fields are captured
- Data Quality % - overall score based on duplicates and missing data

**Example output:**
```
Quality Scores:
  • Medication Completeness: 62.5%
  • Data Quality: 65%

🚨 Critical Issues: 2
  • INCOMPLETE MEDICATION DATA
  • POTENTIAL DUPLICATE ALLERGY
```

### 5. Compare Results

Open the timestamped files:
- **HTML file** - Review the full patient record in browser
- **Analysis report** - Read automated findings and scores
- Compare with other timestamped runs to check consistency
- Compare with baseline `case_{n}.html` if available

## Creating New Test Cases

To create a new evaluation case:

1. **Manual Testing**:
   - Start the intake agent
   - Open browser DevTools (F12)
   - Go to Network tab → WS (WebSocket)
   - Perform your test interaction
   - Record the patient messages you sent

2. **Create Transcript**:
   - Create a new file: `cases/case_3_transcript.json`
   - Follow the JSON format (see Transcript JSON Format section above)
   - Include case metadata: number, date, name, description
   - List patient messages in the `messages` array

3. **Optionally Save Baseline**:
   - Save the original HTML: `cases/case_2.html`
   - This serves as the baseline for comparison

4. **Run Replay**:
   - Execute: `python evals/buy_side/run_case.py 2`
   - Review the timestamped output HTML
   - Compare with baseline or other runs

## Buyer's Perspective Constraints

These tools operate under the following constraints to simulate a real buyer evaluation:

- ✅ **CAN USE**: Browser, DevTools, Network tab, WebSocket inspection, HTML snapshots
- ✅ **CAN AUTOMATE**: Browser interactions, form submissions, message sending
- ❌ **CANNOT ACCESS**: Server code, database, internal APIs, log files
- ❌ **CANNOT MODIFY**: Backend logic, database records, server configuration

## Evaluation Workflow

1. **Baseline Capture** - Save HTML snapshot of initial test (case1.html)
2. **Issue Identification** - Analyze HTML to find problems (cases/case_1_analysis.md)
3. **Theme Development** - Create evaluation themes from issues found
4. **Test Case Design** - Write conversation transcripts targeting each theme
5. **Automated Replay** - Use replay script to re-test scenarios
6. **Comparison Analysis** - Compare outputs to identify patterns
7. **Verdict** - Determine if product meets quality standards

## Tips

- **Timing**: The script includes realistic delays between messages. Adjust `time.sleep()` values if needed.
- **Debugging**: Run with browser visible (`headless=False`) to watch the interaction
- **Screenshots**: Modify the script to capture screenshots at key moments
- **Network Logs**: Use browser DevTools during replay to inspect WebSocket messages
- **Multiple Runs**: Run the same case multiple times to check consistency (different timestamps show variations)

## Example: Testing Duplicate Detection

Create `cases/case_3_transcript.json`:

```json
{
  "case_number": 3,
  "created_timestamp": "2025-10-27T14:00:00-07:00",
  "case_name": "Duplicate Condition Detection",
  "case_description": "Tests whether the agent properly deduplicates semantically similar conditions like 'back pain' and 'lower back pain'",
  "messages": [
    "my name is john smith",
    "1/1/1990",
    "m/m",
    "I have back pain",
    "I also have lower back pain that's been bothering me",
    "that's all",
    "yes"
  ]
}
```

Then run:
```bash
python evals/buy_side/run_case.py 3
```

Inspect the output to see if the system creates duplicate conditions.

## Known Issues from Case 1

See `cases/case_1_analysis.md` for detailed findings:
- Duplicate conditions (back pain + lower back pain)
- Missing medication indications
- Unclear allergy collection status
- Poor sex/gender display format

## Next Steps

1. Create test cases for each evaluation theme in cases/case_1_analysis.md
2. Build a test harness to run multiple cases automatically
3. Create comparison tools to diff HTML outputs
4. Develop metrics scoring system for automated evaluation
