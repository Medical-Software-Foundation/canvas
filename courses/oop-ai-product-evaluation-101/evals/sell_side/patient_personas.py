"""
Pre-defined patient personas for testing the intake agent.

Each persona represents a "ground truth" - what information the agent should extract.
"""

PERSONAS = {
    "simple_hypertension": {
        "first_name": "John",
        "last_name": "Smith",
        "date_of_birth": "1985-06-15",
        "sex": "male",
        "gender": "male",
        "current_health_concerns": "High blood pressure",
        "conditions": [
            {"name": "Hypertension", "status": "stable", "comment": "Diagnosed 2 years ago"}
        ],
        "medications": [
            {"name": "Lisinopril", "dose": "10mg", "form": "tablet", "sig": "once daily", "indications": "blood pressure"}
        ],
        "allergies": [
            {"name": "Penicillin", "comment": "causes rash"}
        ],
        "goals": [
            {"name": "Reduce blood pressure medication", "comment": "Hope to manage through lifestyle changes"}
        ]
    },

    "complex_chronic": {
        "first_name": "Maria",
        "last_name": "Garcia",
        "date_of_birth": "1972-03-22",
        "sex": "female",
        "gender": "female",
        "current_health_concerns": "Managing multiple chronic conditions, occasional dizziness",
        "conditions": [
            {"name": "Type 2 Diabetes", "status": "stable", "comment": "Diagnosed 10 years ago"},
            {"name": "Hypertension", "status": "stable", "comment": "Well controlled with medication"},
            {"name": "Hypothyroidism", "status": "stable", "comment": "On replacement therapy"},
            {"name": "Osteoarthritis", "status": "stable", "comment": "Mainly in knees and hands"}
        ],
        "medications": [
            {"name": "Metformin", "dose": "1000mg", "form": "tablet", "sig": "twice daily with meals", "indications": "diabetes"},
            {"name": "Amlodipine", "dose": "5mg", "form": "tablet", "sig": "once daily", "indications": "blood pressure"},
            {"name": "Levothyroxine", "dose": "75mcg", "form": "tablet", "sig": "once daily in morning", "indications": "thyroid"},
            {"name": "Ibuprofen", "dose": "400mg", "form": "tablet", "sig": "as needed", "indications": "arthritis pain"}
        ],
        "allergies": [
            {"name": "Sulfa drugs", "comment": "severe rash and difficulty breathing"},
            {"name": "Codeine", "comment": "nausea and vomiting"}
        ],
        "goals": [
            {"name": "Better glucose control", "comment": "Want HbA1c below 7%"},
            {"name": "Increase mobility", "comment": "Walk 30 minutes daily without knee pain"}
        ]
    },

    "young_healthy": {
        "first_name": "Emily",
        "last_name": "Chen",
        "date_of_birth": "1998-11-08",
        "sex": "female",
        "gender": "female",
        "current_health_concerns": "Just want a general checkup, occasional anxiety",
        "conditions": [
            {"name": "Generalized Anxiety Disorder", "status": "improving", "comment": "Started therapy 6 months ago"}
        ],
        "medications": [
            {"name": "Sertraline", "dose": "50mg", "form": "tablet", "sig": "once daily", "indications": "anxiety"},
            {"name": "Birth control pill", "dose": "", "form": "tablet", "sig": "daily", "indications": "contraception"}
        ],
        "allergies": [],
        "goals": [
            {"name": "Manage anxiety without medication", "comment": "Eventually want to taper off SSRI"},
            {"name": "Better sleep", "comment": "Get 8 hours consistently"}
        ]
    },

    "elderly_polypharmacy": {
        "first_name": "Robert",
        "last_name": "Johnson",
        "date_of_birth": "1945-07-12",
        "sex": "male",
        "gender": "male",
        "current_health_concerns": "Memory issues, fatigue, multiple medications to manage",
        "conditions": [
            {"name": "Coronary Artery Disease", "status": "stable", "comment": "Stent placed 5 years ago"},
            {"name": "Atrial Fibrillation", "status": "stable", "comment": "Rate controlled"},
            {"name": "Chronic Kidney Disease", "status": "stable", "comment": "Stage 3"},
            {"name": "Benign Prostatic Hyperplasia", "status": "stable", "comment": "Mild symptoms"},
            {"name": "Osteoporosis", "status": "stable", "comment": "Previous compression fracture"}
        ],
        "medications": [
            {"name": "Aspirin", "dose": "81mg", "form": "tablet", "sig": "once daily", "indications": "heart"},
            {"name": "Atorvastatin", "dose": "40mg", "form": "tablet", "sig": "once daily at bedtime", "indications": "cholesterol"},
            {"name": "Metoprolol", "dose": "25mg", "form": "tablet", "sig": "twice daily", "indications": "heart rate and blood pressure"},
            {"name": "Apixaban", "dose": "5mg", "form": "tablet", "sig": "twice daily", "indications": "blood thinner for AFib"},
            {"name": "Tamsulosin", "dose": "0.4mg", "form": "capsule", "sig": "once daily", "indications": "prostate"},
            {"name": "Alendronate", "dose": "70mg", "form": "tablet", "sig": "once weekly", "indications": "bone strength"}
        ],
        "allergies": [
            {"name": "ACE inhibitors", "comment": "severe cough"}
        ],
        "goals": [
            {"name": "Maintain independence", "comment": "Want to continue living alone"},
            {"name": "Reduce fall risk", "comment": "Had a close call last month"}
        ]
    },

    "minimal_info": {
        "first_name": "Alex",
        "last_name": "Williams",
        "date_of_birth": "1990-01-15",
        "sex": "non-binary",
        "gender": "non-binary",
        "current_health_concerns": "Routine visit",
        "conditions": [],
        "medications": [],
        "allergies": [],
        "goals": [
            {"name": "Preventive care", "comment": "Stay healthy"}
        ]
    }
}


def get_persona(name: str) -> dict:
    """Get a persona by name."""
    return PERSONAS.get(name, PERSONAS["simple_hypertension"])


def list_personas() -> list:
    """List all available persona names."""
    return list(PERSONAS.keys())
