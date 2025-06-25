import csv
import re
from pprint import pprint
from customer_migrations.utils import read_json_file

"""
Athena drops JSON files that we need to analyze and eventually
convert to the data migration template CSV format. 

This file will loop through the JSON given and spit out CSV
to put in a google drive to work with the customer on creating mappings
for during the migration. 
"""


def create_unique_mapping_csv(path_to_output_file, data, list_attribute, columns):
	""" Loop through the data set to find a unique list of all the column attributes
	needed for a mapping"""

	mapping = set()
	for _, records in data.items():
		if list_attribute in records:
			for item in records.get(list_attribute, []):
				values = []
				for c in columns:
					value = item
					for i in c.split('.'):
						value = value.get(i)
					values.append(str(value))

				mapping.add("|".join(values))
		else:
			for record in records:
				values = []
				for c in columns:
					value = record
					for i in c.split('.'):
						if re.match(r'\d', i):
							value = value[int(i)]
						else:
							value = value.get(i)
					values.append(str(value))

				mapping.add("|".join(values))


	# output to a CSV
	with open(path_to_output_file, 'w') as output:
		output.write("|".join(columns) + '\n')
		for m in sorted(mapping, key=str.casefold):
			output.write(f'{m}\n')


"""
For Allergies, the JSON structure is like 
	{
	    "lastmodifiedby": "username",
	    "lastupdated": "08/13/2024",
	    "allergies":
	    [
	        {
	            "lastmodifiedby": "username",
	            "allergenname": "Penicillins",
	            "allergenid": "12449",
	            "categories":
	            [
	                "medication"
	            ],
	            "translations":
	            [
	                {
	                    "codesystem": "2.16.840.1.113883.3.26.1.5",
	                    "codesystemdisplayname": "VA NDF-RT",
	                    "displayname": "Penicillins",
	                    "value": "N0000011281"
	                },
	                {
	                    "codesystem": "2.16.840.1.113883.6.96",
	                    "codesystemdisplayname": "IHTSDO SNOMED-CT",
	                    "displayname": "Medicinal product containing penicillin and acting as antibacterial agent (product)",
	                    "value": "6369005"
	                }
	            ],
	            "reactions":
	            [
	                {
	                    "snomedcode": "74964007",
	                    "reactionname": "other"
	                }
	            ],
	            "lastmodifieddatetime": "2024-08-13T09:47:30-04:00",
	            "id": "3625",
	            "rxnormdescription": "Medicinal product containing penicillin and acting as antibacterial agent (product)"
	        }
	    ],
	    "lastmodifieddatetime": "2024-08-13T09:47:30-04:00",
	    "nkda": "false",
	    "patientdetails":
	    {
	        "state": "CA",
	        "lastname": "Test",
	        "firstname": "Test",
	        "homephone": "1234567890",
	        "mobilephone": "1234567890",
	        "zip": "11111",
	        "enterpriseid": "0000",
	        "address1": "123 Test Dr",
	        "dob": "01/01/2000",
	        "city": "Test",
	        "athenapatientid": "0000"
	    }
	}

	We want to find all the unique allergies used based on these fields
		allergenname
		allergenid
		rxnormdescription

	export to a CSV for manually mapping
"""

def create_allergy_map():
	allergy_records = read_json_file("PHI/allergy.json")
	create_unique_mapping_csv(
		"mappings/allergy_mapping.csv", 
		allergy_records, 
		list_attribute='allergies',
		columns=[
			"allergenname",
			"allergenid",
			"rxnormdescription",
		])

"""
For Prescriptions, the JSON structure is like 
{
    "prescriptions":
    [
        {
            "dispenseaswritten": "false",
            "dosagefrequencyunit": "per day",
            "quantityndc": "29300011605",
            "status": "CLOSED",
            "documentdescription": "topiramate 50 mg tablet",
            "ordertype": "PRESCRIPTION",
            "documentclass": "PRESCRIPTION",
            "priority": "2",
            "documenttypeid": "246318",
            "providernpi": "1902253362",
            "ndcs":
            [
                "50090346101",
                "68382013905",
            ],
            "documentroute": "INTERFACE",
            "futuresubmitdate": "08/13/2024",
            "lastmodifieddatetime": "2024-08-13T13:04:16-04:00",
            "medid": "283936",
            "dosagedurationunit": "day",
            "departmentid": "2",
            "providerid": "1",
            "rxnorm": "151227",
            "prescriptionid": "131910",
            "createddatetime": "2024-08-13T12:57:33-04:00",
            "actionnote": "Surescripts has verified that the prescription was received by the pharmacy.",
            "diagnosislist":
            [
                {
                    "snomedicdcodes":
                    [
                        {
                            "description": "Obesity, unspecified",
                            "code": "E669",
                            "unstrippeddiagnosiscode": "E66.9",
                            "codeset": "ICD10"
                        }
                    ],
                    "imodiagnosislist":
                    [],
                    "diagnosiscode":
                    {
                        "description": "Obesity",
                        "code": "414916001",
                        "codeset": "SNOMED"
                    }
                }
            ],
            "refillsallowed": "1",
            "quantityunit": "tablet",
            "sig": "Take 1/2 tab nightly for 2 weeks then 1 full tab thereafter",
            "facilityid": "11872810",
            "isstructuredsig": "false",
            "orderingmode": "PRESCRIBE",
            "quantityvalue": 42,
            "encounterid": "64320",
            "lastmodifieduser": "ATHENA",
            "pages":
            [],
            "createduser": "malbert26",
            "documentsubclass": "PRESCRIPTION_NEW",
            "documentsource": "ENCOUNTER"
        }
    ],
    "totalcount": 3,
    "patientdetails":
    {
		"state": "AZ",
	    "lastname": "last name",
	    "firstname": "first name",
	    "homephone": "1234567890",
	    "mobilephone": "1234567890",
	    "zip": "00000",
	    "enterpriseid": "YYYY",
	    "address1": "123 Test Lane",
	    "dob": "01/01/1900",
	    "city": "city",
	    "athenapatientid": "XXXX"
    }
}

	We want to find all the unique medications used based on these fields
		documentdescription
		medid
		rxnorm

	export to a CSV for manually mapping
"""

def create_prescription_map():
	prescription_records = read_json_file("PHI/prescription.json")
	create_unique_mapping_csv(
		"mappings/prescription_mapping.csv", 
		prescription_records, 
		list_attribute='prescriptions',
		columns=[
			"documentdescription",
			"medid",
			"rxnorm",
		])

"""
For MedRequests, the JSON structure is like (actually FHIR)

		{
	    	"medicationrequests":
	    	[{	
	            "identifier":
	            [
	                {
	                    "value": "a-25828.historicalmedrequest-91245",
	                    "system": "https://fhir.athena.io/sid/ah-medicationrequest"
	                }
	            ],
	            "requester":
	            {
	                "extension":
	                [
	                    {
	                        "valueCode": "unknown",
	                        "url": "http://hl7.org/fhir/StructureDefinition/data-absent-reason"
	                    }
	                ]
	            },
	            "reportedBoolean": true,
	            "intent": "order",
	            "meta":
	            {
	                "lastUpdated": "2024-06-04T11:30:07.000-04:00"
	            },
	            "resourceType": "MedicationRequest",
	            "status": "active",
	            "id": "a-25828.historicalmedrequest-91245",
	            "dosageInstruction":
	            [
	                {
	                    "text": "INHALE 2 INHALATION BY MOUTH EVERY 4 TO 6 HOURS AS NEEDED FOR WHEEZING"
	                }
	            ],
	            "authoredOn": "2024-06-04T11:30:07-04:00",
	            "medicationReference":
	            {
	                "display": "albuterol sulfate HFA 90 mcg/actuation aerosol inhaler",
	                "reference": "Medication/a-25828.medication-215721"
	            },
	            "extension":       
	            [
	                {
	                    "url": "https://fhir.athena.io/StructureDefinition/ah-practice",
	                    "valueReference":
	                    {
	                        "reference": "Organization/a-1.Practice-25828"
	                    }
	                },
	                {
	                    "url": "https://fhir.athena.io/StructureDefinition/ah-chart-sharing-group",
	                    "valueReference":
	                    {
	                        "reference": "Organization/a-25828.CSG-41"
	                    }
	                }
	            ],
	            "subject":
	            {
	                "reference": "Patient/a-25828.E-4163"
	            }
	        }], "total": 1}


	We want to find all the unique medications used based on these fields
		medicationReference.display
		medicationReference.reference

	export to a CSV for manually mapping

"""
def create_medication_request_map():
	med_request_records = read_json_file("PHI/medicationrequest.json", is_fhir=True, list_attribute='medicationrequests')
	create_unique_mapping_csv(
		"mappings/medicationrequest_mapping.csv", 
		med_request_records, 
		list_attribute='medicationrequests',
		columns=[
			"medicationReference.display",
			"medicationReference.reference",
		])

"""
For Immunizagtion, the JSON structure is like (actually FHIR)

        {
		    "immunizations":
		    [{
	            "identifier":
	            [
	                {
	                    "value": "a-25828.historical-74",
	                    "system": "https://fhir.athena.io/sid/ah-immunization"
	                }
	            ],
	            "vaccineCode":
	            {
	                "text": "Td(adult) unspecified formulation",
	                "coding":
	                [
	                    {
	                        "display": "Td(adult) unspecified formulation",
	                        "code": "139",
	                        "system": "http://hl7.org/fhir/sid/cvx"
	                    }
	                ]
	            },
	            "isSubpotent": false,
	            "meta":
	            {
	                "lastUpdated": "2022-07-27T13:57:20.000-04:00"
	            },
	            "doseQuantity":
	            {
	                "value": 999
	            },
	            "status": "completed",
	            "id": "a-25828.historical-74",
	            "primarySource": false,
	            "occurrenceDateTime": "2013-09-19",
	            "resourceType": "Immunization",
	            "patient":
	            {
	                "reference": "Patient/a-25828.E-1244"
	            },
	            "extension":
	            [
	                {
	                    "url": "https://fhir.athena.io/StructureDefinition/ah-practice",
	                    "valueReference":
	                    {
	                        "reference": "Organization/a-1.Practice-25828"
	                    }
	                },
	                {
	                    "url": "https://fhir.athena.io/StructureDefinition/ah-chart-sharing-group",
	                    "valueReference":
	                    {
	                        "reference": "Organization/a-25828.CSG-1"
	                    }
	                }
	            ]
	        },
	        {
	            "recorded": "2022-07-27T13:57:20.000-04:00",
	            "id": "a-25828.im.historical.acs-74",
	            "agent":
	            [
	                {
	                    "who":
	                    {
	                        "reference": "Organization/a-1.Org-ATHENA"
	                    },
	                    "type":
	                    {
	                        "text": "Author",
	                        "coding":
	                        [
	                            {
	                                "display": "Author",
	                                "code": "author",
	                                "system": "http://terminology.hl7.org/CodeSystem/provenance-participant-type"
	                            }
	                        ]
	                    }
	                }
	            ],
	            "target":
	            [
	                {
	                    "reference": "Immunization/a-25828.historical-74"
	                }
	            ],
	            "resourceType": "Provenance"
	        }
	      ], "total": 2}

       We want to find all the unique vaccines used based on these fields
       	medicationReference.display
       	medicationReference.reference

       export to a CSV for manually mapping

"""
def create_immunization_map():
	immunization_records = read_json_file("PHI/immunization.json", is_fhir=True, list_attribute='immunizations')
	create_unique_mapping_csv(
		"mappings/immunizations_mapping.csv", 
		immunization_records, 
		list_attribute='immunizations',
		columns=[
			"vaccineCode.coding.0.display",
			"vaccineCode.coding.0.code",
    ])

"""
For Appointments, the JSON structure is like 
{
    "appointmenttype": "Initial MD Visit",
    "cancelleddatetime": "12/27/2023 13:24:02",
    "date": "02/02/2024",
    "patientid": "XXX",
    "cancelreasonnoshow": "false",
    "rescheduledappointmentid": "134279",
    "cancelreasonslotavailable": "true",
    "coordinatorenterprise": "false",
    "lastmodified": "12/27/2023 13:24:03",
    "cancelledby": "dberk2",
    "copay": 0,
    "patient": {...},
    "cancelreasonid": "11",
    "appointmentcopay":
    {
        "collectedforappointment": 0,
        "collectedforother": 0,
        "insurancecopay": 0
    },
    "appointmenttypeid": "1",
    "appointmentid": "113540",
    "appointmentstatus": "x",
    "lastmodifiedby": "dberk2",
    "departmentid": "19",
    "templateappointmentid": "113540",
    "providerid": "1",
    "chargeentrynotrequired": "false",
    "appointmentconfirmationid": "2",
    "startcheckoutdatetime": "08/13/2024 13:10:55",
    "duration": "45",
    "cancelreasonname": "PATIENT RESCHEDULED",
     "claims":[...]
    "starttime": "08:30",
    "scheduleddatetime": "12/27/2023 13:16:03",
    "hl7providerid": "14",
    "encounterstatus": "CHECKEDOUT",
    "encounterid": "64320",
    "checkindatetime": "08/13/2024 09:46:36",
    "stopexamdatetime": "08/13/2024 12:30:13",
    "scheduledby": "PORTAL",
    "templateappointmenttypeid": "121",
    "supervisingproviderid": "1",
    "patientappointmenttypename": "Initial Visit Medical"
}

We need to find the unique items to understand what to do or mappings to have:
- Status
- Cancel reasons
- Appointemnt types

"""
def create_appointments_map(columns):
	records = read_json_file("PHI/appointment.json")
	create_unique_mapping_csv(
		f"mappings/{'_'.join(columns)}.csv", 
		records, 
		list_attribute='appointments',
		columns=columns
	)
# create_appointments_map(['appointmentstatus'])
# create_appointments_map(['cancelreasonid', 'cancelreasonname'])
# create_appointments_map(['appointmenttype', 'appointmenttypeid'])
# create_appointments_map(['appointmentstatus', 'cancelreasonname'])
# create_appointments_map(['date', 'starttime'])

