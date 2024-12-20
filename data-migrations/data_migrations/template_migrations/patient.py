import re, pytz, arrow
from collections import defaultdict

from customer_migrations.utils import fetch_from_json, write_to_json

def validate_date(value):
    try:
        return True, arrow.get(value).format("YYYY-MM-DD")
    except:
        for format in ["MM/DD/YYYY", "M/D/YYYY", "M/DD/YYYY", "MM-DD-YYYY", "M-D-YYYY", "M-DD-YYYY", "MM.DD.YYYY", "M.D.YYYY", "M.DD.YYYY"]:
            try: 
                return True, arrow.get(value, format).format("YYYY-MM-DD")
            except:
                pass

    return False, None

class PatientLoaderMixin:
    def validate_header(self, headers):
        # confirms the csv's headers are the expected list
        accepted_headers = {
            "First Name",
            "Middle Name",
            "Last Name",
            "Date of Birth",
            "Sex at Birth",
            "Preferred Name",
            "Address Line 1",
            "Address Line 2",
            "City",
            "State",
            "Postal Code",
            "Country",
            "Mobile Phone Number",
            "Mobile Text Consent",
            "Home Phone Number"
            "Email",
            "Email Consent",
            "Timezone",
            "Clinical Note",
            "Administrative Note",
        }            
        if missing_headers := [h for h in accepted_headers if h not in headers]:
            raise ValueError(f"Incorrect headers! These headers were missing {missing_headers} from the supplied csv with headers: {headers}")

    def validate_required(self, value, field_name):
        # validates a required field is not empty
        if not value:
            return False, f"Patient is missing {field_name}"
        return True, value

    def validate_required_sex_at_birth(self, value, _):
        """ Validate the correct sex at birth options"""
        # accept M, Male, F, Female, Unk, UNK, Unknown, m, male, f, female, unk, unknown, OTH, Other, Oth

        if not value:
            return False, f"Patient is missing sex at birth"
            
        mapping = {
            "M": "M",
            "MALE": "M",
            "F": "F",
            "FEMALE": "F",
            "OTH": "OTH",
            "OTHER": "OTH",
            "UNK": "UNK",
            "UNKNOWN": "UNK"
        }

        try:
            return True, mapping[value.upper()]
        except KeyError:
            return False, f"Invalid sex_at_birth given: {value}"
        
        pass

    def validate_required_birth_date(self, value, _):
        # accept YYYY-MM-DD, YYYY-M-DD, YYYY-M-D, YYYY/MM/DD, YYYY/M/DD, YYYY/M/D, YYYY.MM.DD, YYYY.M.DD, YYYY.M.D, 
        # MM/DD/YYYY", "M/D/YYYY", "M/DD/YYYY", "MM-DD-YYYY", "M-D-YYYY", "M-DD-YYYY", "MM.DD.YYYY", "M.D.YYY", "M.DD.YYYY
        if not value:
            return False, f"Patient is missing birth date"
        
        valid, date_value = validate_date(value)

        if not valid:
            return False, f"Invalid birth date format: {value}"
        return valid, date_value

    def validate_state_code(self, value, _):
        # accept only the 2 character state codes
        if not value:
            return True, value
        
        accepted_states = ["AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "DC", "FL", "GA", "HI", "ID", "IL", "IN", "IA", "KS", "KY", "LA", "ME", "MD", "MA", "MI", "MN", "MS", "MO", "MT", "NE", "NV", "NH", "NJ", "NM", "NY", "NC", "ND", "OH", "OK", "OR", "PA", "RI", "SC", "SD", "TN", "TX", "UT", "VT", "VA", "WA", "WV", "WI", "WY"]
        if value in accepted_states:
            return True, value
        return False, f"Invalid state code: {value}"

    def validate_postal_code(self, value, _):
        # finds the first 5 digits for postal code
        if not value:
            return True, value
            
        first_five_digits = [i for i in value if i.isdigit()][:5]
        if len(first_five_digits) == 5:
            return True, "".join(first_five_digits)
        return False, f"Invalid postal code: {value}"

    def validate_phone_number(self, value, _):
        # removes any non digits and validates the length is 10
        if not value:
            return True, value
            
        number = [i for i in value if i.isdigit()]
        if len(number) == 10:
            return True, "".join(number)
        return False, f"Invalid phone number: {value}"

    def validate_consent(self, value, field):
        # accept TRUE, FALSE, true, false, T, F, t, f
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
            return False, f"Invalid true/false {field} given: {value}"

    def validate_email(self, value, _):
        if not value:
            return True, value
            
        match = re.match(r"^(?!\.)[\w!#$%&'*+/=?^`{|}~.-]+(?<!\.)@[a-zA-Z\d.-]+\.[a-zA-Z]{2,}$", value.lower())
       
        if not match:
          return False, f"Invalid email: {value}"
        return True, value

    def validate_timezone(self, value, _):
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
            
        if value in pytz.all_timezones:
            return True, value
        return False, f"Invalid timezone given: {value}"

    def validate_address(self, row):
        # if at least one address field is supplied, we need all 
        required_fields = ["Address Line 1", "City", "State", "Postal Code"]
        if any([row[i] for i in ["Address Line 1",
                                "Address Line 2",
                                "City",
                                "State",
                                "Postal Code"]]):                
            if missing_fields := [f for f in ["Address Line 1", "City", "State", "Postal Code"] if not row[f]]:
                return f"Address detected for patient but missing some required fields ({missing_fields})"

    def validate(self, filename, delimiter='|'):
        """ Loop throw the CSV file to validate each row has the correct columns and values

            Required Formats/Values (Case Insensitive):  
            Date of Birth: YYYY-MM-DD, YYYY-M-DD, YYYY-M-D, YYYY/MM/DD, YYYY/M/DD, YYYY/M/D, YYYY.MM.DD, YYYY.M.DD, YYYY.M.D, 
                           MM/DD/YYYY", M/D/YYYY, M/DD/YYYY, MM-DD-YYYY, M-D-YYYY, M-DD-YYYY, MM.DD.YYYY, M.D.YYY, M.DD.YYYY
            Sex at Birth: Male, M, Female, F, Unknown, UNK, Other, OTH  
            State Code: 2 letter state code  
            Postal Code: 5 digit US postal code  
            Mobile & Home Number: 10 digit US phone number  
            Mobile & Email Consent: Yes, Y, No, N, True, T, False, F
            Email: Letter/Number/SpecialCharacter@domain (e.g., email-1273@email.io)  
            Timezone: EST,EDT,ET,America/New_York,CST,CDT,CT,America/Chicago,MST,MDT,MT,America/Denver,PDT,PST,PT

        """
        validated_rows = []
        errors = defaultdict(list)
        with open(filename, "r") as patient_file:
            reader = csv.DictReader(patient_file, delimiter=delimiter)

            validate_header(reader.fieldnames)

            validations = {
                "First Name": validate_required,
                "Last Name": validate_required,
                "Date of Birth": validate_required_birth_date,
                "Sex at Birth": validate_required_sex_at_birth,
                "State": validate_state_code,
                "Postal Code": validate_postal_code,
                "Home Phone Numer": validate_phone_number,
                "Mobile Phone Number": validate_phone_number,
                "Mobile Text Consent": validate_consent,
                "Email": validate_email,
                "Email Consent": validate_consent,
                "Timezone": validate_timezone,
            }
            
            for row in reader:

                error_msg = validate_address(row)
                if error_msg:
                    errors[f"{row['First Name']} {row['Last Name']}"].append(error_msg)
                
                
                for field, validator_func in validations.items():
                    valid, value = validator_func(row[field].strip(), field)
                    if valid:
                        row[field] = value
                    else:
                        errors[f"{row['First Name']} {row['Last Name']}"].append(value)

                validated_rows.append(row)

        if errors:
            print(json.dumps(errors, indent=4))
        else:
            print('All rows have passed validation!')




    def load(self, validated_rows, system_unique_identifier):
        """
            Takes the validated rows from self.validate() and 
            loops through to send them off the FHIR Patient Create

            Outputs a JSON map of the patient identifier to canvas key
        """

        patient_map = fetch_from_json(self.patient_map_file) 

        for i, row in enumerate(validated_rows):
            patient_identifier = ""
            identifiers = []
            for j in range(1, 4):
                system = row.get(f'Identifier System {j}')
                value = row.get(f'Identifier Value {j}')
                if system and row:
                    identifiers.append(
                        {
                            "system": row[f'Identifier System {j}'],
                            "value": row[f'Identifier Value {j}']
                        }
                    )
                    if system == system_unique_identifier:
                        patient_identifier = value
                else:
                    break

            if patient_identifier and patient_identifier in patient_map:
                print('  Skipping...patient already ingested')
                continue

            payload = {
                "resourceType": "Patient",
                "extension":(
                    [{ 
                        "url": "http://hl7.org/fhir/us/core/StructureDefinition/us-core-birthsex",
                        "valueCode": row["Sex at Birth"]
                    }] + 
                    ([{
                        "url": "http://hl7.org/fhir/StructureDefinition/tz-code",
                        "valueCode": row['Timezone']
                    }] if row['Timezone'] else []) + 
                    ([{
                        "url": "http://schemas.canvasmedical.com/fhir/extensions/clinical-note",
                        "valueString": row['Clinical Note']
                    }] if row['Clinical Note'] else []) +
                    ([{
                        "url": "http://schemas.canvasmedical.com/fhir/extensions/administrative-note",
                        "valueString": row['Administrative Note']
                    }] if row['Administrative Note'] else [])
                ),
                "active": True,
                "name": (
                    [{
                        "use": "official",
                        "family": row['Last Name'],
                        "given": [x for x in [row['First Name'], row['Middle Name']] if x],
                    }] +
                    ([{
                        "use": "nickname",
                        "given":[
                            row["Preferred Name"]
                        ]
                    }] if row["Preferred Name"] else [])
                ),
                "telecom": ([{
                    "extension":[{
                        "url": "http://schemas.canvasmedical.com/fhir/extensions/has-consent",
                        "valueBoolean": row["Mobile Text Consent"]
                    }],
                    "system": "phone",
                    "value": row['Mobile Phone Number'],
                    "use": "mobile",
                    "rank": 1
                }] if row['Mobile Phone Number'] else []) + 
                ([{
                    "system": "phone",
                    "value": row['Home Phone Number'],
                    "use": "home",
                    "rank": 2
                }] if row['Home Phone Number'] else []) + 
                ([{                
                    "extension":[{
                        "url": "http://schemas.canvasmedical.com/fhir/extensions/has-consent",
                        "valueBoolean": row["Email Consent"]
                    }],
                    "system": "email",
                    "value": row['Email'],
                    "use": "home",
                    "rank": 1
                }] if row['Email'] else []),
                "birthDate": row['Date of Birth'],
                "gender": {
                    "F": "female", "M": "male", "OTH": "other", "UNK": "unknown"
                }.get(row['Sex at Birth']),
                "address": ([{
                    "city": row['City'],
                    "country": row['Country'] or "us",
                    "line": [x for x in [row['Address Line 1'], row['Address Line 2']] if x],
                    "postalCode": row['Postal Code'],
                    "state": row['State'],
                    "type": "both",
                    "use": "home"
                }] if row['Address Line 1'] else []),
            }

            if identifiers:
                payload['identifier'] = identifiers

            # print(json.dumps(payload, indent=2))
            
            patient_key = self.fumage_helper.perform_create("Patient", payload)
            print(f"Successfully made ({i+1} {row['First Name']} {row['Last Name']}: https://{fumage_helper.environment}.canvasmedical.com/patient/{patient_key}")    

            if patient_identifier:
                patient_map[patient_identifier] = patient_key
                write_to_json(self.patient_map_file, patient_map)

