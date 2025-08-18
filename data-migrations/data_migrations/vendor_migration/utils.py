import requests, os
from decouple import Config, RepositoryIni

class VendorHelper:
    """
    Helper class for interacting with Vendor EMR API.
    
    This class handles authentication, API calls, and data transformation
    specific to your vendor's EMR system. Customize the methods below
    to match your vendor's API endpoints and data format.
    """
    
    def __init__(self, environment):
        self.environment = environment
        self.config = self._load_config()
        self.base_url = self._get_config_value("vendor_base_url", "https://api.example-vendor.com")
        self.api_key = self._get_config_value("vendor_api_key", "your-api-key-here")
        self.headers = self._get_auth_headers()
    
    def _load_config(self):
        """Load configuration from config.ini with graceful fallback"""
        try:
            # Try to load from config.ini
            config_path = os.path.join(os.path.dirname(__file__), '../', 'config.ini')
            ini = RepositoryIni(config_path)
            ini.SECTION = self.environment
            return Config(ini)
        except FileNotFoundError:
            print(f"Warning: config.ini not found for environment '{self.environment}'. Using default values.")
            return None
        except Exception as e:
            print(f"Warning: Error loading config.ini: {e}. Using default values.")
            return None
    
    def _get_config_value(self, key, default_value):
        """Safely get a config value with fallback to default"""
        if self.config is None:
            return default_value
        
        try:
            return self.config(key, default=default_value, cast=str)
        except Exception as e:
            print(f"Warning: Could not load config value '{key}': {e}. Using default: {default_value}")
            return default_value
    
    def _get_auth_headers(self):
        """Get authentication headers for vendor API calls"""
        # TODO: Customize authentication method for your vendor
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json"
        }
    
    def _make_api_call(self, endpoint, params=None):
        """Make a generic API call to the vendor system"""
        url = f"{self.base_url}{endpoint}"
        try:
            response = requests.get(url, headers=self.headers, params=params)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            print(f"API call failed to {endpoint}: {e}")
            return []
    
    def fetch_patients(self):
        """Fetch all patients from vendor system"""
        # TODO: Replace with your vendor's patient endpoint
        endpoint = "/api/patients"
        return self._make_api_call(endpoint)
    
    def fetch_appointments(self):
        """Fetch all appointments from vendor system"""
        # TODO: Replace with your vendor's appointment endpoint
        endpoint = "/api/appointments"
        return self._make_api_call(endpoint)
    
    def fetch_conditions(self):
        """Fetch all conditions from vendor system"""
        # TODO: Replace with your vendor's condition endpoint
        endpoint = "/api/conditions"
        return self._make_api_call(endpoint)
    
    def fetch_medications(self):
        """Fetch all medications from vendor system"""
        # TODO: Replace with your vendor's medication endpoint
        endpoint = "/api/medications"
        return self._make_api_call(endpoint)
    
    def fetch_immunizations(self):
        """Fetch all immunizations from vendor system"""
        # TODO: Replace with your vendor's immunization endpoint
        endpoint = "/api/immunizations"
        return self._make_api_call(endpoint)
    
    def fetch_lab_reports(self):
        """Fetch all lab reports from vendor system"""
        # TODO: Replace with your vendor's lab report endpoint
        endpoint = "/api/lab_reports"
        return self._make_api_call(endpoint)
    
    def fetch_vitals(self):
        """Fetch all vitals from vendor system"""
        # TODO: Replace with your vendor's vitals endpoint
        endpoint = "/api/vitals"
        return self._make_api_call(endpoint)
    
    def fetch_allergies(self):
        """Fetch all allergies from vendor system"""
        # TODO: Replace with your vendor's allergy endpoint
        endpoint = "/api/allergies"
        return self._make_api_call(endpoint)
    
    def fetch_coverages(self):
        """Fetch all coverages from vendor system"""
        # TODO: Replace with your vendor's coverage endpoint
        endpoint = "/api/coverages"
        return self._make_api_call(endpoint)
    
    def fetch_documents(self):
        """Fetch all documents from vendor system"""
        # TODO: Replace with your vendor's document endpoint
        endpoint = "/api/documents"
        return self._make_api_call(endpoint)
    
    def fetch_consents(self):
        """Fetch all consents from vendor system"""
        # TODO: Replace with your vendor's consent endpoint
        endpoint = "/api/consents"
        return self._make_api_call(endpoint)
    
    def fetch_family_history(self):
        """Fetch all family history from vendor system"""
        # TODO: Replace with your vendor's family history endpoint
        endpoint = "/api/family_history"
        return self._make_api_call(endpoint)
    
    def fetch_messages(self):
        """Fetch all messages from vendor system"""
        # TODO: Replace with your vendor's message endpoint
        endpoint = "/api/messages"
        return self._make_api_call(endpoint)
    
    def fetch_notes(self):
        """Fetch all notes from vendor system"""
        # TODO: Replace with your vendor's note endpoint
        endpoint = "/api/notes"
        return self._make_api_call(endpoint)
    
    def fetch_prescriptions(self):
        """Fetch all prescriptions from vendor system"""
        # TODO: Replace with your vendor's prescription endpoint
        endpoint = "/api/prescriptions"
        return self._make_api_call(endpoint)
    
    def fetch_hpi(self):
        """Fetch all HPI from vendor system"""
        # TODO: Replace with your vendor's HPI endpoint
        endpoint = "/api/hpi"
        return self._make_api_call(endpoint)
    
    def transform_date(self, vendor_date):
        """Transform vendor date format to Canvas expected format"""
        # TODO: Customize date transformation for your vendor's format
        # Example: "MM/DD/YYYY" -> "YYYY-MM-DD"
        return vendor_date
    
    def transform_code(self, vendor_code, code_type):
        """Transform vendor codes to standard coding systems"""
        # TODO: Customize code transformation for your vendor
        # This should use the mapping files in the mappings/ folder
        return vendor_code
    
    def get_patient_mapping(self, vendor_patient_id):
        """Get Canvas patient ID from vendor patient ID"""
        # TODO: Load and use patient mapping from PHI/patient_id_map.json
        return None
