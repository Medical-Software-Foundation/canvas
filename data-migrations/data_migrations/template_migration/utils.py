import arrow 

def validate_date(value, field_name):
    try:
        return True, arrow.get(value).format("YYYY-MM-DD")
    except:
        for format in ["MM/DD/YYYY", "M/D/YYYY", "M/DD/YYYY", "MM-DD-YYYY", "M-D-YYYY", "M-DD-YYYY", "MM.DD.YYYY", "M.D.YYYY", "M.DD.YYYY"]:
            try: 
                return True, arrow.get(value, format).format("YYYY-MM-DD")
            except:
                pass

    return False, f"Invalid {field_name} format: {value}"

def validate_datetime(value, field_name):
    try:
        return True, arrow.get(value).isoformat()
    except:
        return False, f"Invalid {field_name} format: {value}"

def validate_required(value, field_name):
    """ validates a required field is not empty """
    if not value:
        return False, f"Data is missing {field_name}"
    return True, value

def validate_header(headers, accepted_headers):
    # confirms the csv's headers are the expected list          
    if missing_headers := [h for h in accepted_headers if h not in headers]:
        raise ValueError(f"Incorrect headers! These headers were missing {missing_headers} from the supplied csv with headers: {headers}")

def validate_state_code(value, field_name):
    """ accept only the 2 character state codes """
    if not value:
        return True, value
    
    accepted_states = ["AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "DC", "FL", "GA", "HI", "ID", "IL", "IN", "IA", "KS", "KY", "LA", "ME", "MD", "MA", "MI", "MN", "MS", "MO", "MT", "NE", "NV", "NH", "NJ", "NM", "NY", "NC", "ND", "OH", "OK", "OR", "PA", "RI", "SC", "SD", "TN", "TX", "UT", "VT", "VA", "WA", "WV", "WI", "WY"]
    if value in accepted_states:
        return True, value
    return False, f"Invalid {field_name}: {value}"

def validate_postal_code(value, field_name):
    """ finds the first 5 digits for postal code """
    if not value:
        return True, value
        
    first_five_digits = [i for i in value if i.isdigit()][:5]
    if len(first_five_digits) == 5:
        return True, "".join(first_five_digits)
    return False, f"Invalid {field_name}: {value}"

def validate_phone_number(value, field_name):
    """ removes any non digits and validates the length is 10 """
    if not value:
        return True, value

    if value.startswith('+1'):
        value = value[2:]
        
    number = [i for i in value if i.isdigit()]
    if len(number) == 10:
        return True, "".join(number)
    return False, f"Invalid {field_name}: {value}"

def validate_boolean(value, field_name):
    """ Validates a boolean fields 

        accept TRUE, FALSE, true, false, T, F, t, f
    """

    if not value:
        return True, False
        
    mapping = {
        "TRUE": True,
        "T": True,
        "FALSE": False,
        "F": False,
        "Y": True,
        "N": False,
        "YES": True,
        "FALSE": False
    }
    try:
        return True, mapping[value.upper()]
    except KeyError:
        return False, f"Invalid boolean {field_name} given: {value}"


def validate_email(value, field_name):
    """ Validate an email format """
    if not value:
        return True, value
        
    match = re.match(r"^(?!\.)[\w!#$%&'*+/=?^`{|}~.-]+(?<!\.)@[a-zA-Z\d.-]+\.[a-zA-Z]{2,}$", value.lower())
   
    if not match:
      return False, f"Invalid {field_name}: {value}"
    return True, value

def validate_timezone(value, field_name):
    """ Validate a timezone value """
    if not value:
        return True, value

    # accept EST, EDT, ET, America/New_York, CST, CDT, CT, America/Chicago, MST, MDT, MT, America/Denver, PDT, PST, PT
    mapping = {
        "EST": 'America/New_York',
        "EDT": 'America/New_York',
        "ET": 'America/New_York',
        "CST": 'America/Chicago',
        "CDT": 'America/Chicago',
        "CT": 'America/Chicago',
        "MST": 'America/Denver',
        "MDT": 'America/Denver',
        "MT": 'America/Denver',
        "PST": 'America/Los_Angeles',
        "PDT": 'America/Los_Angeles',
        "PT": 'America/Los_Angeles'
    }

    try:
        return True, mapping[value.upper()]
    except KeyError:
        pass
        
    # if its not part of the expected values, just make sure it is a valid timezone with the pytz library
    if value in pytz.all_timezones:
        return True, value
    return False, f"Invalid {field_name} given: {value}"

def validate_address(row):
    """ Validate address elements """

    # if at least one address field is supplied, we need all 
    required_fields = ["Address Line 1", "City", "State", "Postal Code"]
    if any([row[i] for i in ["Address Line 1",
                            "Address Line 2",
                            "City",
                            "State",
                            "Postal Code"]]):                
        if missing_fields := [f for f in ["Address Line 1", "City", "State", "Postal Code"] if not row[f]]:
            return f"Address detected for row but missing some required fields ({missing_fields})"

def validate_enum(value, possible_options):
    if not value:
        return True, value

    value = value.lower()

    return value in possible_options, value

class MappingMixin:

    def map_patient(self, patient):
        # make sure patient is in the mapped patients
        if not patient_key := self.patient_map.get(patient):
            raise Exception(f'    Ignoring due no patient map with {patient}')

        return patient_key

    def map_provider(self, provider):
        # map the provider if needed
        if not provider:
            return

        if hasattr(self, doctor_map):
            practitioner_key = self.doctor_map.get(str(practitioner_key))

            if not practitioner_key:
                raise Exception(f'    Ignoring due no doctor map with {provider}')

            return practitioner_key
        return provider

    def map_location(self, location):
        # map the location if needed
        if hasattr(self, location_map):
            location_key = self.location_map.get(str(location))

            if not location_key:
                raise Exception(f'    Ignoring due no location map with {location}')

            return location_key
        return location