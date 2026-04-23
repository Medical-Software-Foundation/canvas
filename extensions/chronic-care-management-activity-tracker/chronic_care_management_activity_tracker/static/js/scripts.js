const patientId = "{{ patient_id }}";

// Timer state
let timerInterval = null;
let elapsedSeconds = 0;
let isRunning = false;
let sessionLog = [];

// DOM elements
let timerDisplay;
let timerBtn;
let logEntriesContainer;
let notesTextarea;
let clearBtn;
let saveBtn;

// Initialize the app when DOM is loaded
document.addEventListener('DOMContentLoaded', function() {
    // Get DOM elements
    timerDisplay = document.getElementById('timer-display');
    timerBtn = document.getElementById('timer-btn');
    logEntriesContainer = document.getElementById('log-entries');
    notesTextarea = document.getElementById('notes');
    clearBtn = document.getElementById('clear-btn');
    saveBtn = document.getElementById('save-btn');

    saveBtn.disabled = true;

    // Attach event listeners
    timerBtn.addEventListener('click', toggleTimer);
    clearBtn.addEventListener('click', clearSession);
    saveBtn.addEventListener('click', saveSession);

    // Update display
    updateTimerDisplay();
    renderLog();
});

// Format seconds into MM:SS format
function formatTime(seconds) {
    const mins = Math.floor(seconds / 60);
    const secs = seconds % 60;
    return `${String(mins).padStart(2, '0')}:${String(secs).padStart(2, '0')}`;
}

// Update the timer display
function updateTimerDisplay() {
    timerDisplay.textContent = formatTime(elapsedSeconds);
}

// Toggle timer start/stop
function toggleTimer() {
    if (!isRunning) {
        startTimer();
    } else {
        stopTimer();
    }
}

// Start the timer
function startTimer() {
    isRunning = true;
    const startTime = Date.now() - (elapsedSeconds * 1000);

    timerInterval = setInterval(() => {
        elapsedSeconds = Math.floor((Date.now() - startTime) / 1000);
        updateTimerDisplay();
    }, 1000);

    saveBtn.disabled = true;

    // Update button
    timerBtn.textContent = 'Stop';
    timerBtn.classList.remove('resume');
    timerBtn.classList.add('stop');

    // Log the event
    if (elapsedSeconds === 0) {
        addLogEntry('Timer started');
    } else {
        addLogEntry('Timer resumed');
    }
}

// Stop the timer
function stopTimer() {
    if (timerInterval) {
        clearInterval(timerInterval);
        timerInterval = null;
    }
    isRunning = false;
    saveBtn.disabled = false;

    // Update button
    timerBtn.textContent = 'Start';
    timerBtn.classList.remove('stop');
    timerBtn.classList.add('resume');

    // Log the event
    addLogEntry(`Timer stopped - Total: ${formatTime(elapsedSeconds)}`);
}

// Add an entry to the session log
function addLogEntry(message) {
    const timestamp = new Date();
    const entry = {
        timestamp: timestamp,
        message: message
    };
    sessionLog.push(entry);
    renderLog();
}

// Format timestamp for display
function formatTimestamp(date) {
    const month = date.getMonth() + 1;
    const day = date.getDate();
    const year = date.getFullYear();
    const hours = date.getHours();
    const minutes = String(date.getMinutes()).padStart(2, '0');
    const seconds = String(date.getSeconds()).padStart(2, '0');
    const ampm = hours >= 12 ? 'PM' : 'AM';
    const displayHours = hours % 12 || 12;

    return `${month}/${day}/${year}, ${displayHours}:${minutes}:${seconds} ${ampm}`;
}

// Render the session log
function renderLog() {
    logEntriesContainer.innerHTML = '';

    sessionLog.forEach(entry => {
        const logEntry = document.createElement('div');
        logEntry.className = 'log-entry';

        const timestamp = document.createElement('span');
        timestamp.className = 'timestamp';
        timestamp.textContent = formatTimestamp(entry.timestamp);

        const message = document.createElement('span');
        message.className = 'message';
        message.textContent = ` - ${entry.message}`;

        logEntry.appendChild(timestamp);
        logEntry.appendChild(message);
        logEntriesContainer.appendChild(logEntry);
    });
}

// Reset the form and timer state
function resetForm() {
    // Stop timer if running
    if (isRunning) {
        if (timerInterval) {
            clearInterval(timerInterval);
            timerInterval = null;
        }
        isRunning = false;
    }

    // Reset everything
    elapsedSeconds = 0;
    sessionLog = [];
    isRunning = false;

    // Clear form
    notesTextarea.value = '';
    const checkboxes = document.querySelectorAll('input[name="activity"]');
    checkboxes.forEach(checkbox => {
        checkbox.checked = false;
    });

    // Update UI
    updateTimerDisplay();
    renderLog();
    timerBtn.textContent = 'Start';
    timerBtn.classList.remove('stop', 'resume');
    saveBtn.disabled = true;
}

// Clear the session (with confirmation)
function clearSession() {
    if (sessionLog.length === 0 && elapsedSeconds === 0) {
        return;
    }

    const confirmed = confirm('Are you sure you want to clear the current session? This will reset the timer and clear all data.');
    if (!confirmed) {
        return;
    }

    resetForm();
}

// Save the session
function saveSession() {
    // Get selected activities
    const checkboxes = document.querySelectorAll('input[name="activity"]:checked');
    const activities = Array.from(checkboxes).map(cb => cb.value);

    // Get notes
    const notes = notesTextarea.value.trim();

    // Prepare session data
    const sessionData = {
        totalTime: elapsedSeconds,
        activities: activities,
        notes: notes,
        timeLogs: sessionLog,
        savedAt: new Date()
    };

    // In a real application, this would send data to the backend
    console.log('Saving session:', sessionData);

    return fetch(`/plugin-io/api/chronic_care_management_activity_tracker/${patientId}/sessions`, {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json'
        },
        body: JSON.stringify(sessionData)
    }).then(response => {
        if (!response.ok) {
            throw new Error('Network response was not ok');
        }
        return response.json();
    }).then(data => {
        console.log('Session saved successfully:', data);

        // return createQuestionnaire(activities);
    }).then(() => {
        alert('Session saved successfully!');
        resetForm();  // Clear form without confirmation after successful save
    }).catch(error => {
        console.error('Error saving session:', error);
        alert('There was an error saving the session. Please try again.');
    });
}

function createQuestionnaire(activities) {
    return fetch(`/plugin-io/api/chronic_care_management_activity_tracker/${patientId}/questionnaire`, {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json'
        },
        body: JSON.stringify({ activities })
    });
}