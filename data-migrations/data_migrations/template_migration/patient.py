import re, pytz, arrow, csv, json
from collections import defaultdict

from data_migrations.utils import fetch_from_json, write_to_json
from utils import (
    validate_date, 
    validate_required, 
    validate_header,
    validate_state_code,
    validate_postal_code,
    validate_phone_number,
    validate_boolean,
    validate_email,
    validate_timezone,
    validate_address
)

class PatientLoaderMixin:
    """
        Canvas has outlined a CSV template for ideal data migration that this Mixin will follow. 
        It will confirm the headers it expects as outlined in the template and validate each column.
        Trying to convert or confirm the formats are what we expect:

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
        """ Validate a date"""

        # accept YYYY-MM-DD, YYYY-M-DD, YYYY-M-D, YYYY/MM/DD, YYYY/M/DD, YYYY/M/D, YYYY.MM.DD, YYYY.M.DD, YYYY.M.D, 
        # MM/DD/YYYY", "M/D/YYYY", "M/DD/YYYY", "MM-DD-YYYY", "M-D-YYYY", "M-DD-YYYY", "MM.DD.YYYY", "M.D.YYY", "M.DD.YYYY
        if not value:
            return False, f"Patient is missing birth date"
        
        return validate_date(value, field_name='birth date')

    def validate(self, delimiter='|'):
        """ 
            Loop throw the CSV file to validate each row has the correct columns and values
            Append validated rows to a list to use to load. 
            Export errors to a file/console
            
        """
        validated_rows = []
        errors = defaultdict(list)
        with open(self.csv_file, "r") as file:
            reader = csv.DictReader(file, delimiter=delimiter)

            self.validate_header(reader.fieldnames, 
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
                    "Home Phone Number",
                    "Email",
                    "Email Consent",
                    "Timezone",
                    "Clinical Note",
                    "Administrative Note",
                }  
            )

            validations = {
                "First Name": validate_required,
                "Last Name": validate_required,
                "Date of Birth": self.validate_required_birth_date,
                "Sex at Birth": self.validate_required_sex_at_birth,
                "State": validate_state_code,
                "Postal Code": validate_postal_code,
                "Home Phone Number": validate_phone_number,
                "Mobile Phone Number": validate_phone_number,
                "Mobile Text Consent": validate_boolean,
                "Email": validate_email,
                "Email Consent": validate_boolean,
                "Timezone": validate_timezone,
            }
            
            for row in reader:
                error = False

                error_msg = validate_address(row)
                if error_msg:
                    errors[f"{row['First Name']} {row['Last Name']}"].append(error_msg)
                    error = True
                
                for field, validator_func in validations.items():
                    valid, value = validator_func(row[field].strip(), field)
                    if valid:
                        row[field] = value
                    else:
                        errors[f"{row['First Name']} {row['Last Name']}"].append(value)
                        error = True

                if not error:
                    validated_rows.append(row)

        if errors:
            print(f"Some rows contained errors, please see {self.validation_error_file}.")
            write_to_json(self.validation_error_file, errors)
        else:
            print('All rows have passed validation!')

        return validated_rows


    def load(self, validated_rows, system_unique_identifier):
        """
            Takes the validated rows from self.validate() and 
            loops through to send them off the FHIR Create

            Outputs to CSV to keep track of records 
            If any  error, the error message will output to the errored file
        """

        patient_map = fetch_from_json(self.patient_map_file) 

        total_count = len(validated_rows)
        for i, row in enumerate(validated_rows):
            print(f'Ingesting Patient ({i+1}/{total_count})')

            patient_identifier = ""
            identifiers = []
            for j in range(1, 4):
                system = row.get(f'Identifier System {j}')
                value = row.get(f'Identifier Value {j}')
                if system and value:
                    identifiers.append(
                        {
                            "system": row[f'Identifier System {j}'],
                            "value": row[f'Identifier Value {j}']
                        }
                    )
                    if system == system_unique_identifier:
                        patient_identifier = value

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
            
            try:
                patient_key = self.fumage_helper.perform_create(payload)
                print(f"    Successfully made {row['First Name']} {row['Last Name']}: https://{self.environment}.canvasmedical.com/patient/{patient_key}")    
                
                if patient_identifier:
                    patient_map[patient_identifier] = patient_key
                    write_to_json(self.patient_map_file, patient_map)
            except Exception as e:
                # if any FHIR request failed, output to file to go back and fix
                e = str(e).replace('\n', '')
                with open(self.error_file, 'a') as errored:
                    print(' Errored patient outputing error message to file...')
                    errored.write(f"{patient_identifier}|{row['First Name']}|{row['Last Name']}|{e}\n")


