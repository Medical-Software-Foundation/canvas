-- Rose Clinic Intake Agent Database Schema

-- Patient table: Core demographic information
CREATE TABLE IF NOT EXISTS patient (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    first_name TEXT,
    last_name TEXT,
    date_of_birth TEXT,  -- Stored as ISO format YYYY-MM-DD
    sex TEXT,  -- Biological sex (e.g., "Male", "Female", "Intersex")
    gender TEXT,  -- Gender identity
    current_health_concerns TEXT,  -- Free text for patient's health concerns
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Condition table: Medical conditions and diagnoses
CREATE TABLE IF NOT EXISTS condition (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    patient_id INTEGER NOT NULL,
    name TEXT NOT NULL,
    status TEXT CHECK(status IN ('improving', 'stable', 'deteriorating')),
    comment TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (patient_id) REFERENCES patient(id) ON DELETE CASCADE
);

-- Medication table: Current medications
CREATE TABLE IF NOT EXISTS medication (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    patient_id INTEGER NOT NULL,
    name TEXT NOT NULL,
    dose TEXT,  -- e.g., "10mg", "5ml"
    form TEXT,  -- e.g., "tablet", "capsule", "liquid"
    sig TEXT,  -- Signature/instructions: e.g., "Take once daily"
    indications TEXT,  -- What the medication is for
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (patient_id) REFERENCES patient(id) ON DELETE CASCADE
);

-- Allergy table: Known allergies
CREATE TABLE IF NOT EXISTS allergy (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    patient_id INTEGER NOT NULL,
    name TEXT NOT NULL,  -- Allergen name (e.g., "Penicillin", "Peanuts")
    comment TEXT,  -- Reaction details
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (patient_id) REFERENCES patient(id) ON DELETE CASCADE
);

-- Goal table: Patient health goals
CREATE TABLE IF NOT EXISTS goal (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    patient_id INTEGER NOT NULL,
    name TEXT NOT NULL,  -- Short goal name/title
    comment TEXT,  -- Detailed description
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (patient_id) REFERENCES patient(id) ON DELETE CASCADE
);

-- Message table: Chat conversation history
CREATE TABLE IF NOT EXISTS message (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    patient_id INTEGER NOT NULL,
    participant TEXT NOT NULL CHECK(participant IN ('patient', 'agent')),
    content TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (patient_id) REFERENCES patient(id) ON DELETE CASCADE
);

-- Indexes for performance
CREATE INDEX IF NOT EXISTS idx_condition_patient ON condition(patient_id);
CREATE INDEX IF NOT EXISTS idx_medication_patient ON medication(patient_id);
CREATE INDEX IF NOT EXISTS idx_allergy_patient ON allergy(patient_id);
CREATE INDEX IF NOT EXISTS idx_goal_patient ON goal(patient_id);
CREATE INDEX IF NOT EXISTS idx_message_patient ON message(patient_id);
CREATE INDEX IF NOT EXISTS idx_message_created ON message(patient_id, created_at);
