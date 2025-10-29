#!/bin/bash

# Script to run bilateral case runner for all cases that don't have results yet
# Usage: ./run_all_bilateral_cases.sh

set -e  # Exit on error

# Get the directory where this script lives
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
CASES_DIR="$SCRIPT_DIR/cases_bilateral"

echo "========================================"
echo "  Bilateral Case Runner - Batch Mode"
echo "========================================"
echo ""
echo "Project root: $PROJECT_ROOT"
echo "Cases directory: $CASES_DIR"
echo ""

# Change to project root to run commands
cd "$PROJECT_ROOT"

# Count total cases and cases to run
total_cases=0
cases_to_run=0
cases_completed=0

# First pass: count cases
echo "Scanning for cases..."
for case_file in "$CASES_DIR"/case_*.json; do
    # Skip if no files found
    [ -e "$case_file" ] || continue

    # Get the basename
    basename_file=$(basename "$case_file")

    # Skip template files
    if [[ "$basename_file" == _* ]]; then
        continue
    fi

    # Skip result and analysis files - only process input case files
    # Input files match pattern: case_NNN.json (where NNN is digits only)
    if [[ "$basename_file" =~ case_([0-9]+)\.json$ ]]; then
        case_number="${BASH_REMATCH[1]}"
    else
        # Skip files like case_001_result.json, case_001_analysis.json, etc.
        continue
    fi

    total_cases=$((total_cases + 1))

    # Check if result already exists
    result_file="$CASES_DIR/case_${case_number}_result.json"
    if [ ! -f "$result_file" ]; then
        cases_to_run=$((cases_to_run + 1))
    fi
done

echo "Found $total_cases total cases"
echo "Cases needing to be run: $cases_to_run"
echo ""

if [ $cases_to_run -eq 0 ]; then
    echo "✅ All cases already have results!"
    exit 0
fi

echo "Starting case runs..."
echo ""

# Second pass: run cases
for case_file in "$CASES_DIR"/case_*.json; do
    # Skip if no files found
    [ -e "$case_file" ] || continue

    # Get the basename
    basename_file=$(basename "$case_file")

    # Skip template files
    if [[ "$basename_file" == _* ]]; then
        continue
    fi

    # Skip result and analysis files - only process input case files
    # Input files match pattern: case_NNN.json (where NNN is digits only)
    if [[ "$basename_file" =~ case_([0-9]+)\.json$ ]]; then
        case_number="${BASH_REMATCH[1]}"
    else
        # Skip files like case_001_result.json, case_001_analysis.json, etc.
        continue
    fi

    # Check if result already exists
    result_file="$CASES_DIR/case_${case_number}_result.json"

    if [ -f "$result_file" ]; then
        echo "⏭️  Case $case_number: Result already exists, skipping"
        continue
    fi

    echo "▶️  Case $case_number: Running..."
    echo "----------------------------------------"

    # Run the bilateral case runner
    if uv run python evals/buy_side/case_runner_bilateral.py "$case_number"; then
        cases_completed=$((cases_completed + 1))
        echo ""
        echo "✅ Case $case_number: Completed successfully"
        echo ""
    else
        echo ""
        echo "❌ Case $case_number: Failed"
        echo ""
        echo "Stopping batch run due to error."
        echo "Completed $cases_completed out of $cases_to_run cases."
        exit 1
    fi
done

echo "========================================"
echo "  Batch Run Complete"
echo "========================================"
echo ""
echo "Total cases processed: $cases_completed out of $cases_to_run"
echo ""
echo "Results saved in: $CASES_DIR"
echo ""
