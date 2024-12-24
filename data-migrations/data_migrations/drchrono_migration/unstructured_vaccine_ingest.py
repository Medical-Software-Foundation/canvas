import json
from django.contrib.contenttypes.models import ContentType
from api.models.consolidated_immunization import ConsolidatedImmunization, ImmunizationStatus
from api.models.immunization import ImmunizationStatement, ImmunizationStatementCoding
from builtin_content.core_types import commands

"""
This script needs to be run ssh'd into the instance since you can't 
ingest unstructured immunization statements via API. In the Canvas UI, you 
can create Immunization Statements with unstructured data, so on a historical
data migration we may want to use this script to ingest all historical records
that did not have the correct codings. 

This will require a Canvas Engineer to run

get vaccine_objs from "PHI/unstructured_vaccine_records.json" after running 
 create_historical_data_imports.py with 
    loader = DataImportLoader(environment='juno')
    loader.fetch_records_and_maps()
    loader.find_vaccines_to_ingest_as_unstructured()

Future work is to be able to perform this in the Commands API
"""


def ingest_unstructed_immunization_command(obj):
        note = Note.objects.get(externally_exposable_id=obj['note_key'])
        kwargs = {
            "patient": Patient.objects.get(key=obj['patient']),
            "committer_id": 1, # Canvas Bot
            "originator_id": 1, # Canvas Bot
            "editors": [1], # Canvas Bot
            "date": obj['date'],
            "date_original": obj['date'],
            "note": note,
            "comment": obj['note'],
        }

        immunization_statement = ImmunizationStatement.objects.create(**kwargs)
        ImmunizationStatementCoding.objects.create(
            system='unstructured',
            version='',
            code='',
            display='HPAP',
            immunization_statement=immunization_statement,
        )

        consolidated_immunization = ConsolidatedImmunization.objects.filter(
            object_id=immunization_statement.id,
            content_type=ContentType.objects.get_for_model(immunization_statement),
        ).get()
        consolidated_immunization.status = ImmunizationStatus.STATUS_COMPLETED
        consolidated_immunization.primary_source = False
        consolidated_immunization.save()

        note.insert_command(commands.ImmunizationStatement.key, immunization_statement.id)

        with open("done_vaccines.csv", 'a') as done_vaccines:
            done_vaccines.write(f"{obj['drchrono_vaccine_id']},{obj['drchrono_patient_id']},{obj['patient']},{consolidated_immunization.externally_exposable_id}\n")

with open('unstructured_vaccine_records.json') as json_data:
    vaccine_objs = json.load(json_data)

count = len(vaccine_objs)
for i, obj in enumerate(vaccine_objs):
    print(f'Trying for {obj} ({i}/{count})')
    ingest_unstructed_immunization_command(obj)
    print('  Done')

print('COMPLETELY DONE')
