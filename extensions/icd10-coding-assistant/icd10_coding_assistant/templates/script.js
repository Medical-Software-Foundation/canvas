// Global state - read from context passed via HTML
const patientId = window.ICD10Context.patientId;
const apiBase = '//' + window.ICD10Context.host + '/plugin-io/api/icd10_coding_assistant/api';
let conditionsData = [];

// Load conditions on page load
async function loadConditions() {
    try {
        const response = await fetch(
            apiBase + '/conditions-missing-icd10?patient_id=' + patientId,
            { credentials: 'include' }
        );

        if (!response.ok) {
            throw new Error('Failed to load conditions: ' + response.statusText);
        }

        const data = await response.json();
        conditionsData = data.conditions || [];

        document.getElementById('loading').style.display = 'none';

        if (conditionsData.length === 0) {
            showNoConditionsMessage();
            return;
        }

        document.getElementById('app').style.display = 'block';
        renderConditions();
    } catch (error) {
        console.error('Error loading conditions:', error);
        document.getElementById('loading').style.display = 'none';
        showError('Error loading conditions: ' + error.message);
    }
}

function renderConditions() {
    const tbody = document.getElementById('conditions-body');
    tbody.innerHTML = '';

    conditionsData.forEach(condition => {
        const row = createConditionRow(condition);
        tbody.appendChild(row);
        // Populate recommendations after row is in the DOM
        populateRecommendations(condition);
    });
}

function createConditionRow(condition) {
    const tr = document.createElement('tr');
    tr.id = 'row-' + condition.id;

    // If condition has pending command, gray out the row
    const isDisabled = condition.has_pending_command === true;
    if (isDisabled) {
        tr.style.opacity = '0.5';
        tr.style.background = '#f5f5f5';
    }

    // Condition name cell
    const tdName = document.createElement('td');
    let nameHtml = "<div class='condition-name'>" + escapeHtml(condition.name) + '</div>';
    if (isDisabled) {
        nameHtml += "<div style='color:#ff6b6b;font-size:11px;font-style:italic;margin-top:4px;'>Pending update in chart review note</div>";
    }
    tdName.innerHTML = nameHtml;
    tr.appendChild(tdName);

    // Current code system cell
    const tdSystem = document.createElement('td');
    tdSystem.innerHTML = "<div class='code-system'>" + escapeHtml(condition.current_system) + '</div>';
    tr.appendChild(tdSystem);

    // Current code cell
    const tdCode = document.createElement('td');
    tdCode.innerHTML = "<div class='code-system'>" + escapeHtml(condition.current_code || '') + '</div>';
    tr.appendChild(tdCode);

    // Recommended ICD-10 cell
    const tdRec = document.createElement('td');
    if (condition.recommendations && condition.recommendations.length > 0) {
        if (condition.recommendations.length === 1) {
            // Show single recommendation
            const rec = condition.recommendations[0];
            tdRec.innerHTML = "<div class='recommendation'>" +
                "<div class='rec-code'>" + escapeHtml(rec.code) + '</div>' +
                "<div class='rec-display'>" + escapeHtml(rec.display || '') + '</div>' +
                '</div>';
        } else {
            // Show count of multiple recommendations
            tdRec.innerHTML = "<div class='recommendation'>" +
                "<div class='rec-code'>" + condition.recommendations.length + " options found</div>" +
                "<div class='rec-display'>See dropdown below</div>" +
                '</div>';
        }
    } else {
        tdRec.innerHTML = "<div style='color:#999;font-size:12px;'>No recommendation</div>";
    }
    tr.appendChild(tdRec);

    // Search/Select cell
    const tdSearch = document.createElement('td');
    const disabledAttr = isDisabled ? " disabled" : "";
    tdSearch.innerHTML =
        "<input type='text' class='search-box' id='search-" + condition.id + "' " +
        "value='" + escapeHtml(condition.name) + "' " +
        "placeholder='Type to search ICD-10...'" + disabledAttr + " />" +
        "<select class='select-box' id='select-" + condition.id + "'" + disabledAttr + ">" +
        "<option value=''>-- Select alternative --</option>" +
        '</select>' +
        "<div id='searching-" + condition.id + "' class='searching' style='display:none;'>Searching...</div>";
    tr.appendChild(tdSearch);

    // Add event listener after the element is in the DOM (only if not disabled)
    if (!isDisabled) {
        setTimeout(() => {
            const searchBox = document.getElementById('search-' + condition.id);
            if (searchBox) {
                searchBox.addEventListener('input', function(e) {
                    searchICD10(condition.id, e.target.value);
                });
            }
        }, 0);
    }

    // Action cell
    const tdAction = document.createElement('td');
    tdAction.className = 'actions-cell';
    if (isDisabled) {
        tdAction.innerHTML =
            "<button class='btn btn-disabled' id='btn-" + condition.id + "' disabled>Pending</button>";
    } else {
        tdAction.innerHTML =
            "<button class='btn btn-primary' id='btn-" + condition.id + "' " +
            "onclick='approveCoding(\"" + condition.id + "\")'>Approve</button>";
    }
    tr.appendChild(tdAction);

    return tr;
}

function populateRecommendations(condition) {
    const select = document.getElementById('select-' + condition.id);
    if (!select) {
        console.error('Could not find select element for condition', condition.id);
        return;
    }

    // Add all recommended ICD-10 codes if available
    if (condition.recommendations && condition.recommendations.length > 0) {
        console.log('Adding', condition.recommendations.length, 'recommendations to dropdown for condition', condition.id);

        condition.recommendations.forEach((rec, index) => {
            const option = document.createElement('option');
            option.value = JSON.stringify({
                code: rec.code,
                display: rec.display || ''
            });
            option.textContent = rec.code + ' - ' + rec.display;

            // Pre-select the first recommendation
            if (index === 0) {
                option.selected = true;
            }

            select.appendChild(option);
        });

        console.log('Added', condition.recommendations.length, 'recommendation(s) for condition', condition.id);
    } else {
        console.log('No recommendations available for condition', condition.id);
    }
}

let searchTimeout = null;
async function searchICD10(conditionId, query) {
    console.log('searchICD10 called for condition', conditionId, 'with query:', query);

    // Clear previous timeout
    if (searchTimeout) clearTimeout(searchTimeout);

    // Don't search for very short queries
    if (query.length < 3) {
        const select = document.getElementById('select-' + conditionId);
        select.innerHTML = "<option value=''>-- Select alternative --</option>";
        console.log('Query too short, cleared dropdown');
        return;
    }

    // Show searching indicator
    const searchingDiv = document.getElementById('searching-' + conditionId);
    searchingDiv.style.display = 'block';

    // Debounce the search
    searchTimeout = setTimeout(async () => {
        console.log('Executing search for:', query);
        try {
            const response = await fetch(
                apiBase + '/search-icd10?query=' + encodeURIComponent(query),
                { credentials: 'include' }
            );

            if (!response.ok) {
                throw new Error('Search failed');
            }

            const data = await response.json();
            console.log('Search results received:', data);

            const select = document.getElementById('select-' + conditionId);
            select.innerHTML = "<option value=''>-- Select alternative --</option>";

            if (data.results && data.results.length > 0) {
                console.log('Adding', data.results.length, 'results to dropdown');
                data.results.forEach(result => {
                    const option = document.createElement('option');
                    option.value = JSON.stringify({code: result.value, display: result.text});
                    option.textContent = result.value + ' - ' + result.text;
                    select.appendChild(option);
                });
            } else {
                console.log('No results found');
                const option = document.createElement('option');
                option.value = '';
                option.textContent = 'No results found';
                select.appendChild(option);
            }

            searchingDiv.style.display = 'none';
        } catch (error) {
            console.error('Search error:', error);
            searchingDiv.style.display = 'none';
        }
    }, 300);
}

async function approveCoding(conditionId) {
    const select = document.getElementById('select-' + conditionId);
    const btn = document.getElementById('btn-' + conditionId);

    // Determine which code to use (selected dropdown value or first recommendation)
    let icd10Code, icd10Display;

    if (select.value) {
        // User selected from dropdown (either pre-populated recommendation or search result)
        const selected = JSON.parse(select.value);
        icd10Code = selected.code;
        icd10Display = selected.display;
    } else {
        // Fall back to first recommendation from the conditions data array
        const condition = conditionsData.find(c => c.id === conditionId);
        if (!condition || !condition.recommendations || condition.recommendations.length === 0) {
            alert('No ICD-10 code selected or recommended');
            return;
        }
        // Use recommendations[0] — the API returns a "recommendations" list, not "recommended_icd10"
        icd10Code = condition.recommendations[0].code;
        icd10Display = condition.recommendations[0].display;
    }

    // Disable button and show loading
    btn.disabled = true;
    btn.textContent = 'Approving...';

    try {
        const response = await fetch(
            apiBase + '/approve-coding',
            {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                credentials: 'include',
                body: JSON.stringify({
                    patient_id: patientId,
                    condition_id: conditionId,
                    icd10_code: icd10Code,
                    icd10_display: icd10Display
                })
            }
        );

        if (!response.ok) {
            const error = await response.json();
            throw new Error(error.error || 'Failed to update condition');
        }

        // Success - update UI to show pending state
        const row = document.getElementById('row-' + conditionId);
        row.style.opacity = '0.5';
        row.style.background = '#f5f5f5';

        // Add "Pending update" message to condition name
        const nameCell = row.querySelector('td:first-child');
        const existingContent = nameCell.querySelector('.condition-name');
        if (existingContent && !nameCell.querySelector('.pending-message')) {
            const pendingMsg = document.createElement('div');
            pendingMsg.className = 'pending-message';
            pendingMsg.style.cssText = 'color:#ff6b6b;font-size:11px;font-style:italic;margin-top:4px;';
            pendingMsg.textContent = 'Pending update in chart review note';
            nameCell.appendChild(pendingMsg);
        }

        // Update button to show Pending state
        btn.textContent = 'Pending';
        btn.className = 'btn btn-disabled';
        btn.disabled = true;

        // Disable search and select inputs
        const searchBox = document.getElementById('search-' + conditionId);
        const selectBox = document.getElementById('select-' + conditionId);
        if (searchBox) searchBox.disabled = true;
        if (selectBox) selectBox.disabled = true;

        // Update condition in data array to mark as pending
        const condition = conditionsData.find(c => c.id === conditionId);
        if (condition) {
            condition.has_pending_command = true;
        }

        // Check if all conditions are now pending
        const remainingToApprove = conditionsData.filter(c => !c.has_pending_command);
        if (remainingToApprove.length === 0) {
            showCompletionMessage();
        } else {
            showStatus('Condition update staged in chart review note!', 'success');
        }
    } catch (error) {
        console.error('Approve error:', error);
        btn.disabled = false;
        btn.textContent = 'Approve';
        showStatus('Error: ' + error.message, 'error');
    }
}

async function approveAll() {
    const allBtn = document.getElementById('approve-all-btn');

    if (conditionsData.length === 0) {
        alert('No conditions to approve');
        return;
    }

    // Collect all conditions with their selected or recommended codes (skip disabled ones)
    const conditions = [];
    for (const condition of conditionsData) {
        // Skip conditions with pending commands
        if (condition.has_pending_command === true) {
            console.log('Skipping condition with pending command:', condition.id);
            continue;
        }

        const select = document.getElementById('select-' + condition.id);
        let icd10Code, icd10Display;

        if (select && select.value) {
            // User selected an alternative from the dropdown
            const selected = JSON.parse(select.value);
            icd10Code = selected.code;
            icd10Display = selected.display;
        } else if (condition.recommendations && condition.recommendations.length > 0) {
            // Use first recommended code from the recommendations list
            icd10Code = condition.recommendations[0].code;
            icd10Display = condition.recommendations[0].display;
        } else {
            console.warn('No code available for condition', condition.id);
            continue;
        }

        conditions.push({
            condition_id: condition.id,
            icd10_code: icd10Code,
            icd10_display: icd10Display
        });
    }

    if (conditions.length === 0) {
        alert('No conditions with available ICD-10 codes to approve');
        return;
    }

    if (!confirm('Approve all ' + conditions.length + ' condition(s) with their ICD-10 codes in a single Chart Review Note?')) {
        return;
    }

    allBtn.disabled = true;
    allBtn.textContent = 'Approving...';

    try {
        const response = await fetch(
            apiBase + '/approve-all',
            {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                credentials: 'include',
                body: JSON.stringify({
                    patient_id: patientId,
                    conditions: conditions
                })
            }
        );

        if (!response.ok) {
            const error = await response.json();
            throw new Error(error.error || 'Failed to update conditions');
        }

        // Success - update UI for all approved conditions to show pending state
        for (const conditionUpdate of conditions) {
            const conditionId = conditionUpdate.condition_id;
            const btn = document.getElementById('btn-' + conditionId);
            const row = document.getElementById('row-' + conditionId);

            if (row) {
                row.style.opacity = '0.5';
                row.style.background = '#f5f5f5';

                // Add "Pending update" message
                const nameCell = row.querySelector('td:first-child');
                if (nameCell && !nameCell.querySelector('.pending-message')) {
                    const pendingMsg = document.createElement('div');
                    pendingMsg.className = 'pending-message';
                    pendingMsg.style.cssText = 'color:#ff6b6b;font-size:11px;font-style:italic;margin-top:4px;';
                    pendingMsg.textContent = 'Pending update in chart review note';
                    nameCell.appendChild(pendingMsg);
                }
            }

            if (btn) {
                btn.textContent = 'Pending';
                btn.className = 'btn btn-disabled';
                btn.disabled = true;
            }

            // Disable search and select inputs
            const searchBox = document.getElementById('search-' + conditionId);
            const selectBox = document.getElementById('select-' + conditionId);
            if (searchBox) searchBox.disabled = true;
            if (selectBox) selectBox.disabled = true;

            // Update condition in data array to mark as pending
            const condition = conditionsData.find(c => c.id === conditionId);
            if (condition) {
                condition.has_pending_command = true;
            }
        }

        allBtn.disabled = false;
        allBtn.textContent = 'Approve All';

        // Check if all conditions are now pending (nothing left to approve)
        const remainingToApprove = conditionsData.filter(c => !c.has_pending_command);

        if (remainingToApprove.length === 0) {
            showCompletionMessage();
        } else {
            showStatus('All conditions staged in chart review note!', 'success');
        }

    } catch (error) {
        console.error('Approve all error:', error);
        allBtn.disabled = false;
        allBtn.textContent = 'Approve All';
        showStatus('Error: ' + error.message, 'error');
    }
}

function showError(message) {
    const container = document.getElementById('error-container');
    container.innerHTML = "<div class='error'>" + escapeHtml(message) + '</div>';
}

function showStatus(message, type) {
    const statusMsg = document.getElementById('status-msg');
    statusMsg.textContent = message;
    statusMsg.className = 'status-msg status-' + type;
    statusMsg.style.display = 'inline-block';

    setTimeout(() => {
        statusMsg.style.display = 'none';
    }, 5000);
}

function showCompletionMessage() {
    // Hide the table and batch actions
    document.getElementById('app').style.display = 'none';

    // Show completion message
    const container = document.getElementById('error-container');
    container.innerHTML =
        "<div style='text-align:center;padding:60px 40px;'>" +
        "<div style='font-size:48px;margin-bottom:20px;'>&#10003;</div>" +
        "<h2 style='color:#28a745;margin-bottom:15px;'>All Conditions Staged!</h2>" +
        "<p style='color:#666;font-size:16px;margin-bottom:10px;'>All condition updates have been staged in a chart review note.</p>" +
        "<p style='color:#999;font-size:14px;'>The ICD-10 codes will be applied when the commands are recorded in the chart review note.</p>" +
        "<p style='color:#999;font-size:14px;margin-top:20px;'>You can close this window.</p>" +
        "</div>";
}

function showNoConditionsMessage() {
    // Show nice message when no conditions need coding
    const container = document.getElementById('error-container');
    container.innerHTML =
        "<div style='text-align:center;padding:60px 40px;'>" +
        "<div style='font-size:48px;margin-bottom:20px;'>&#10003;</div>" +
        "<h2 style='color:#28a745;margin-bottom:15px;'>All Set!</h2>" +
        "<p style='color:#666;font-size:16px;margin-bottom:10px;'>All active conditions already have ICD-10 codes.</p>" +
        "<p style='color:#999;font-size:14px;margin-top:20px;'>You can close this window.</p>" +
        "</div>";
}

function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

// Initialize
loadConditions();
