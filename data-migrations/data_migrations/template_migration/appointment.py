import re, pytz, arrow, csv, json
from collections import defaultdict

from data_migrations.utils import fetch_from_json, write_to_json
from utils import validate_header, validate_required, validate_datetime, MappingMixin

class AppointmentLoaderMixin(MappingMixin):
    """
        Canvas has outlined a CSV template for ideal data migration that this Mixin will follow. 
        It will confirm the headers it expects as outlined in the template and validate each column.
        Trying to convert or confirm the formats are what we expect:

        Required Formats/Values (Case Insensitive):  
            Patient Identifier: Canvas key, unique identifier defined on the demographics page
            Appointment Type: Active, Resolved
            Location:  Location ID configured in Canvas. 
            Start / End Date/time: YYYY-MM-DDTHH:mm:ssZZ
            Duration: Time in minutes
            Recorded Provider: Staff Canvas key. 
    """

    def validate_end_time(self, row):
        """ Confirm there is an end date set for the appointment, 
        It is confirmed that Start Date / Time is already there. 
        Need to ensure duration or End Date Time is there
        """

        if end_date := row['End Date/Time']:
            return validate_datetime(end_date, 'End Date/Time')

        if duration := row['Duration']:
            try:
                return True, arrow.get(row['Start Date / Time']).shift(minutes=duration).isoformat()
            except:
                pass

        return False, "Unable to calculate appointment end date/time"

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

            validate_header(reader.fieldnames, 
                accepted_headers = {
                    "ID",
                    "Patient Identifier",
                    "Appointment Type",
                    "Reason for Visit Code",
                    "Reason for Visit Text",
                    "Location",
                    "Meeting Link",
                    "Start Date / Time",
                    "End Date/Time",
                    "Duration",
                    "Provider"

                }  
            )

            validations = {
                "Patient Identifier": validate_required,
                "Location": validate_required,
                "Provider": validate_required,
                "Start Date / Time": validate_datetime,
            }
            
            for row in reader:
                error = False
                key = f"{row['ID']} {row['Patient Identifier']}"
                
                for field, validator_func in validations.items():
                    kwargs = {}
                    if isinstance(validator_func, tuple): 
                        validator_func, kwargs = validator_func
                    
                    valid, value = validator_func(row[field].strip(), field, **kwargs)
                    if valid:
                        row[field] = value
                    else:
                        errors[key].append(value)
                        error = True

                valid, field_or_error_msg = validate_end_time(row)
                if not valid:
                    errors[key].append(field_or_error_msg)
                    error = True
                else:
                    row['End Date/Time'] = field_or_error_msg

                if not error:
                    validated_rows.append(row)

        if errors:
            print(f"Some rows contained errors, please see {self.validation_error_file}.")
            write_to_json(self.validation_error_file, errors)
        else:
            print('All rows have passed validation!')

        return validated_rows

    def map_rfv(self, row):
        """ Create the FHIR reasonCode object. Since Canvas supports both
        structured RFV and free text
        """
        rfv_code = row['Reason for Visit Code']
        free_text = row['Reason for Visit Text']
        reason_code = {}

        if hasattr(self, rfv_map):
            rfv = self.rfv_map.get(str(rfv_code))

        if rfv_code:
            system, code = rfv.split('|')
            reason_code['coding'] = [{
                "system": system,
                "code": code
            }]

        if free_text:
            reason_code['text'] = free_text

        if not rfv_code and not free_text:
            reason_code['text'] = "No Reason Given"

        return reason_code


    def load(self, validated_rows, system_unique_identifier):
        """
            Takes the validated rows from self.validate() and 
            loops through to send them off the FHIR Create

            Outputs to CSV to keep track of records 
            If any  error, the error message will output to the errored file
        """

        patient_map = fetch_from_json(self.patient_map_file) 

        total_count = len(validated_rows)
        print(f'      Found {len(validated_rows)} records')
        for i, row in enumerate(validated_rows):
            print(f'Ingesting ({i+1}/{total_count})')

            if row['id'] in self.done_records:
                print(' Already did record')
                continue

            patient = row['Patient Identifier']
            patient_key = ""
            try:
                # try mapping required Canvas identifiers
                patient_key = self.map_patient(patient)
                practitioner_key = self.map_provider(row['Provider'])
                location = self.map_location(row['Location'])
            except BaseException as e:
                e = str(e).replace('\n', '')
                with open(self.errored_file, 'a') as errored:
                    print(f' {e}')
                    errored.write(f"{row['id']}|{row['patient']}|{patient_key}|{e}\n")
                    continue


            payload = {
                "resourceType": "Appointment",
                "identifier": [
                    {
                        "system": system_unique_identifier,
                        "value": row['ID'],
                    }
                ],
                "status": "fulfilled",
                "appointmentType": {
                    "coding": [{
                            "system": "INTERNAL",
                            "code": f"{system_unique_identifier}_historical_note",
                    }]
                },
                "reasonCode":[self.map_rfv(row)],
                "supportingInformation":[
                    {"reference": f"Location/{location}"}
                ],
                "start": arrow.get("Start Date / Time"),
                "end": arrow.get("End Date/Time"),
                "participant":[
                    {
                        "actor": {"reference": f"Patient/{patient_key}"},
                        "status": "accepted"
                    },
                    {
                        "actor": {"reference": f"Practitioner/{practitioner_key}"},
                        "status": "accepted"
                    }
                ]
            }


            # Add meeting link if provided
            if meeting_link := row['Meeting Link']:
                payload['supportingInformation'].append({
                    "reference": "#appointment-meeting-endpoint",
                    "type": "Endpoint"
                })
                payload['contained'] = {
                    "resourceType": "Endpoint",
                    "id": "appointment-meeting-endpoint",
                    "address": meeting_link
                }

            # print(json.dumps(payload, indent=2))

            try:
                canvas_id = self.fumage_helper.perform_create(payload)
                with open(self.done_file, 'a') as done:
                    print(' Complete Apt')
                    done.write(f"{row['ID']}|{patient}|{patient_key}|{canvas_id}\n")
            except BaseException as e:            
                e = str(e).replace('\n', '')
                with open(self.errored_file, 'a') as errored:
                    print(' Errored Apt')
                    errored.write(f"{row['ID']}|{patient}|{patient_key}|{e}\n")
                continue 


            # need to check in and lock the appointment if appointment is historical
            if payload['status'] == 'fulfilled':
                try:                
                    self.fumage_helper.check_in_and_lock_appointment(canvas_id)
                except BaseException as e:
                    e = str(e).replace('\n', '')
                    with open(self.errored_note_state_event_file, 'a') as errored_state:
                        print(' Errored NSCE')
                        errored_state.write(f"{row['ID']}|{patient}|{patient_key}|{e}\n")
        
        