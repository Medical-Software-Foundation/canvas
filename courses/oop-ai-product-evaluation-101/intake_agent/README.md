# EZGrow Patient Intake Agent

A Flask-based web application for medical intake with an AI agent assistant.

## Quick Start

```bash
# Set API key
export ANTHROPIC_API_KEY="your-key-here"

# Initialize database (first time only)
cd intake_agent
uv run python database.py

# Start the application
uv run python app.py
```

Open http://localhost:5000 in your browser.

## Configuration

Edit `config.py` to customize:
- `MODEL` - Claude model to use
- `AGENT_NAME` - Agent's display name
- `VERBOSITY` (1-5) - Response length/detail level
- `PERSONALITY` - Agent personality: 'professional', 'friendly', 'empathetic', 'quirky', 'meme_lord'

---

## Database Setup

To initialize the database:

```bash
uv run python database.py
```

This will create `intake_agent.db` with all required tables and indexes.

## Connecting to the Database

To query the database directly using SQLite CLI:

```bash
sqlite3 intake_agent.db
```

Useful commands once connected:
```sql
.tables                    -- List all tables
.schema patient            -- View schema for a specific table
.headers on                -- Show column headers in query results
.mode column               -- Display results in column format
SELECT * FROM patient;     -- Query patient data
.quit                      -- Exit SQLite CLI
```

## Application Routes

- `/` - Home page with list of patients and "Intake New Patient" button
- `/patient/new` - Creates a new patient and redirects to their page
- `/patient/<patient_id>` - Individual patient intake page with split-screen interface
- `/messages/<patient_id>` - API endpoint to get all messages for a patient

## WebSocket Events

- `connect` - Client connects to server
- `join` - Client joins a patient's chat room
- `send_message` - Send a message (triggers LLM response)
- `new_message` - Receive a new message (patient or agent)

## Features

- **Split-screen interface** - Medical record on left, chat on right
- **Real-time chat** - WebSocket-based bidirectional communication
- **AI-powered extraction** - Automatically extracts structured data from conversation
- **Smart updates** - Updates medical record dynamically without page reload
- **Duplicate prevention** - Checks for existing records, updates instead of creating duplicates
- **Configurable personality** - 5 personality types from professional to meme_lord
- **Configurable verbosity** - Control response length and detail (1-5 scale)
- **Async greeting** - Initial greeting generated asynchronously for fast page load
- **Record completeness** - Visual indicators showing completion status by category
- **Auto-expanding input** - Chat input grows with longer messages
