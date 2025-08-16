from data_migrations.utils import load_fhir_settings

fumage_helper = load_fhir_settings("phi-iconhealth-test")
fumage_helper.build_patient_external_identifier_map("Elation", "PHI/patient_id_map.json")