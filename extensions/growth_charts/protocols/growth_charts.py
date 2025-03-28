import datetime
import arrow

from canvas_sdk.effects import Effect
from canvas_sdk.effects.launch_modal import LaunchModalEffect
from canvas_sdk.handlers.action_button import ActionButton
from canvas_sdk.templates import render_to_string

from canvas_sdk.v1.data import Patient, Observation, Note

from growth_charts.graphs.who_boys_weight_age import who_boys_weight_age
from growth_charts.graphs.who_boys_length_age import who_boys_length_age
from growth_charts.graphs.who_boys_weight_length import who_boys_weight_length
from growth_charts.graphs.who_girls_weight_age import who_girls_weight_age
from growth_charts.graphs.who_girls_length_age import who_girls_length_age
from growth_charts.graphs.who_girls_weight_length import who_girls_weight_length
from growth_charts.graphs.who_boys_circumference_age import who_boys_circumference_age
from growth_charts.graphs.who_girls_circumference_age import who_girls_circumference_age
from growth_charts.graphs.cdc_boys_weight_age_24_240 import cdc_boys_weight_age_24_240
from growth_charts.graphs.cdc_boys_weight_age import cdc_boys_weight_age
from growth_charts.graphs.cdc_boys_length_age import cdc_boys_length_age
from growth_charts.graphs.cdc_boys_weight_length import cdc_boys_weight_length
from growth_charts.graphs.cdc_boys_head_age import cdc_boys_head_age
from growth_charts.graphs.cdc_boys_weight_stature import cdc_boys_weight_stature
from growth_charts.graphs.cdc_boys_stature_age import cdc_boys_stature_age
from growth_charts.graphs.cdc_boys_bmi_age import cdc_boys_bmi_age
from growth_charts.graphs.cdc_girls_weight_age import cdc_girls_weight_age
from growth_charts.graphs.cdc_girls_length_age import cdc_girls_length_age
from growth_charts.graphs.cdc_girls_weight_length import cdc_girls_weight_length
from growth_charts.graphs.cdc_girls_head_age import cdc_girls_head_age
from growth_charts.graphs.cdc_girls_weight_stature import cdc_girls_weight_stature
from growth_charts.graphs.cdc_girls_weight_age_24_240 import cdc_girls_weight_age_24_240
from growth_charts.graphs.cdc_girls_stature_age import cdc_girls_stature_age
from growth_charts.graphs.cdc_girls_bmi_age import cdc_girls_bmi_age

def convert_in_to_cm(inches: str) -> float:
    return float(inches) * 2.54

def convert_oz_to_kg(oz: str) -> float:
    return float(oz) * 0.0283495

def get_age_in_months(birth_date: datetime.date, date: datetime.date = datetime.datetime.now()) -> int:
    now = arrow.get(date)
    date = arrow.get(birth_date)
    year_difference = now.year - date.year
    month_difference = now.month - date.month

    return year_difference * 12 + month_difference

def generate_layer_data(data: dict) -> list[dict]:
    return [{"x": key, "y": data[key]} for key in sorted(data.keys())]

class GenerateVitalsGraphs(ActionButton):
    BUTTON_TITLE = "Growth Charts"
    BUTTON_KEY = "show_growth_charts"
    BUTTON_LOCATION = ActionButton.ButtonLocation.CHART_SUMMARY_VITALS_SECTION

    def handle(self) -> list[Effect]:
        graphs = []
        patient = Patient.objects.get(id=self.target)
        sex_at_birth = patient.sex_at_birth
        birth_date = patient.birth_date
        age_in_months = get_age_in_months(birth_date)

        is_less_than_24_months_old = age_in_months < 24
        is_less_than_36_months_old = age_in_months < 36

        observation_weight = Observation.objects.for_patient(self.target).filter(name="weight")
        observation_height = Observation.objects.for_patient(self.target).filter(name="height")
        observation_length = Observation.objects.for_patient(self.target).filter(name="length")
        observation_bmi = Observation.objects.for_patient(self.target).filter(name="bmi")
        observation_head_circumference = Observation.objects.for_patient(self.target).filter(name="head_circumference")

        weight_for_age = {}
        length_for_age = {}
        weight_for_length = {}
        head_for_age = {}
        bmi_for_age = {}

        for obs in observation_weight:
            if obs.value:
                note = Note.objects.get(dbid=obs.note_id)
                age_in_months = get_age_in_months(birth_date, note.datetime_of_service)
                weight_in_kg = convert_oz_to_kg(obs.value)
                weight_for_age[age_in_months] = weight_in_kg

        for obs in observation_length:
            if obs.value:
                note = Note.objects.get(dbid=obs.note_id)
                age_in_months = get_age_in_months(birth_date, note.datetime_of_service)
                length_in_cm = convert_in_to_cm(obs.value)
                length_for_age[age_in_months] = length_in_cm

        for obs in observation_height:
            if obs.value:
                note = Note.objects.get(dbid=obs.note_id)
                age_in_months = get_age_in_months(birth_date, note.datetime_of_service)
                height_in_cm = convert_in_to_cm(obs.value)
                length_for_age[age_in_months] = height_in_cm

        for obs in observation_head_circumference:
            if obs.value:
                note = Note.objects.get(dbid=obs.note_id)
                age_in_months = get_age_in_months(birth_date, note.datetime_of_service)
                head_in_cm = convert_in_to_cm(obs.value)
                head_for_age[age_in_months] = head_in_cm

        for obs in observation_bmi:
            if obs.value:
                note = Note.objects.get(dbid=obs.note_id)
                age_in_months = get_age_in_months(birth_date, note.datetime_of_service)
                bmi_for_age[age_in_months] = obs.value

        for obs_weight in observation_weight:
            note_weight = Note.objects.get(dbid=obs_weight.note_id)
            for obs_length in observation_length:
                note_length = Note.objects.get(dbid=obs_length.note_id)
                if note_length.datetime_of_service == note_weight.datetime_of_service:
                    if obs_weight.value and obs_length.value:
                        weight_in_kg = convert_oz_to_kg(obs_weight.value)
                        length_in_cm = convert_in_to_cm(obs_length.value)
                        weight_for_length[length_in_cm] = weight_in_kg


        if sex_at_birth == "M":
            if is_less_than_24_months_old:
                graphs.append(
                    {
                        "data": who_boys_weight_age,
                        "title": 'Weight for age (Boys 0 - 2 years)',
                        "xType": 'Generic',
                        "yType": 'Weight',
                        "xLabel": 'Age',
                        "yLabel": 'Weight',
                        "zLabel": 'Percentile',
                        "layerData": generate_layer_data(weight_for_age),
                        "tab": "WHO"
                    }
                )

                graphs.append(
                    {
                        "data": who_boys_length_age,
                        "title": 'Length for age (Boys 0 - 2 years)',
                        "xType": 'Generic',
                        "yType": 'Length',
                        "xLabel": 'Age',
                        "yLabel": 'Length',
                        "zLabel": 'Percentile',
                        "layerData": generate_layer_data(length_for_age),
                        "tab": "WHO"
                    }
                )

                graphs.append(
                    {
                        "data": who_boys_weight_length,
                        "title": 'Weight for Length (Boys)',
                        "xType": 'Length',
                        "yType": 'Weight',
                        "xLabel": 'Length',
                        "yLabel": 'Weight',
                        "zLabel": 'Percentile',
                        "layerData": generate_layer_data(weight_for_length),
                        "tab": "WHO"
                    }
                )

                graphs.append(
                    {
                        "data": who_boys_circumference_age,
                        "title": 'Head Circumference for age (Boys 0 - 2 years)',
                        "xType": 'Generic',
                        "yType": 'Length',
                        "xLabel": 'Age',
                        "yLabel": 'Head Circumference',
                        "zLabel": 'Percentile',
                        "layerData": generate_layer_data(head_for_age),
                        "tab": "WHO"
                    }
                )

            if is_less_than_36_months_old:
                graphs.append(
                    {
                        "data": cdc_boys_weight_age,
                        "title": 'Weight for age (Boys 0 - 36 months)',
                        "xType": 'Generic',
                        "yType": 'Weight',
                        "xLabel": 'Age',
                        "yLabel": 'Weight',
                        "zLabel": 'Percentile',
                        "layerData": generate_layer_data(weight_for_age),
                        "tab": "CDC"
                    }
                )

                graphs.append(
                    {
                        "data": cdc_boys_length_age,
                        "title": 'Length for age (Boys 0 - 36 months)',
                        "xType": 'Generic',
                        "yType": 'Length',
                        "xLabel": 'Age',
                        "yLabel": 'Length',
                        "zLabel": 'Percentile',
                        "layerData": generate_layer_data(length_for_age),
                        "tab": "CDC"
                    }
                )

                graphs.append(
                    {
                        "data": cdc_boys_weight_length,
                        "title": 'Weight for recumbent length (Boys)',
                        "xType": 'Length',
                        "yType": 'Weight',
                        "xLabel": 'Length',
                        "yLabel": 'Weight',
                        "zLabel": 'Percentile',
                        "layerData": generate_layer_data(weight_for_length),
                        "tab": "CDC"
                    }
                )

                graphs.append(
                    {
                        "data": cdc_boys_head_age,
                        "title": 'Head Circumference for age (Boys 0 - 36 months)',
                        "xType": 'Generic',
                        "yType": 'Length',
                        "xLabel": 'Age',
                        "yLabel": 'Length',
                        "zLabel": 'Percentile',
                        "layerData": generate_layer_data(head_for_age),
                        "tab": "CDC"
                    }
                )

                graphs.append(
                    {
                        "data": cdc_boys_weight_stature,
                        "title": 'Weight for stature (Boys)',
                        "xType": 'Length',
                        "yType": 'Weight',
                        "xLabel": 'Length',
                        "yLabel": 'Weight',
                        "zLabel": 'Percentile',
                        "layerData": generate_layer_data(weight_for_length),
                        "tab": "CDC"
                    }
                )

            if 24 <= age_in_months <= 240:
                graphs.append(
                    {
                        "data": cdc_boys_weight_age_24_240,
                        "title": 'Weight for age (Boys 2 - 20 years)',
                        "xType": 'Generic',
                        "yType": 'Weight',
                        "xLabel": 'Age',
                        "yLabel": 'Weight',
                        "zLabel": 'Percentile',
                        "layerData": generate_layer_data(weight_for_age),
                        "tab": "CDC"
                    }
                )

                graphs.append(
                    {
                        "data": cdc_boys_stature_age,
                        "title": 'Stature for age (Boys 2 - 20 years)',
                        "xType": 'Generic',
                        "yType": 'Length',
                        "xLabel": 'Age',
                        "yLabel": 'Length',
                        "zLabel": 'Percentile',
                        "layerData": generate_layer_data(length_for_age),
                        "tab": "CDC"
                    }
                )

                graphs.append(
                    {
                        "data": cdc_boys_bmi_age,
                        "title": 'Bmi for age (Boys 2 - 20 years)',
                        "xType": 'Generic',
                        "yType": 'Generic',
                        "xLabel": 'Age',
                        "yLabel": 'Length',
                        "zLabel": 'Percentile',
                        "layerData": generate_layer_data(bmi_for_age),
                        "tab": "CDC"
                    }
                )

        elif sex_at_birth == "F":
            if is_less_than_24_months_old:
                graphs.append(
                    {
                        "data": who_girls_weight_age,
                        "title": 'Weight for age (Girls 0 - 2 years)',
                        "xType": 'Generic',
                        "yType": 'Weight',
                        "xLabel": 'Age',
                        "yLabel": 'Weight',
                        "zLabel": 'Percentile',
                        "layerData": generate_layer_data(weight_for_age),
                        "tab": "WHO"
                    }
                )

                graphs.append(
                    {
                        "data": who_girls_length_age,
                        "title": 'Length for age (Girls 0 - 2 years)',
                        "xType": 'Generic',
                        "yType": 'Length',
                        "xLabel": 'Age',
                        "yLabel": 'Length',
                        "zLabel": 'Percentile',
                        "layerData": generate_layer_data(length_for_age),
                        "tab": "WHO"
                    }
                )

                graphs.append(
                    {
                        "data": who_girls_weight_length,
                        "title": 'Weight for Length (Girls)',
                        "xType": 'Length',
                        "yType": 'Weight',
                        "xLabel": 'Length',
                        "yLabel": 'Weight',
                        "zLabel": 'Percentile',
                        "layerData": generate_layer_data(weight_for_length),
                        "tab": "WHO"
                    }
                )

                graphs.append(
                    {
                        "data": who_girls_circumference_age,
                        "title": 'Head Circumference for age (Girls 0 - 2 years)',
                        "xType": 'Generic',
                        "yType": 'Length',
                        "xLabel": 'Age',
                        "yLabel": 'Head Circumference',
                        "zLabel": 'Percentile',
                        "layerData": generate_layer_data(head_for_age),
                        "tab": "WHO"
                    }
                )
            if is_less_than_36_months_old:
                graphs.append(
                    {
                        "data": cdc_girls_weight_age,
                        "title": 'Weight for age (Girls 0 - 36 months)',
                        "xType": 'Generic',
                        "yType": 'Weight',
                        "xLabel": 'Age',
                        "yLabel": 'Weight',
                        "zLabel": 'Percentile',
                        "layerData": generate_layer_data(weight_for_age),
                        "tab": "CDC"
                    }
                )

                graphs.append(
                    {
                        "data": cdc_girls_length_age,
                        "title": 'Length for age (Girls 0 - 36 months)',
                        "xType": 'Generic',
                        "yType": 'Length',
                        "xLabel": 'Age',
                        "yLabel": 'Length',
                        "zLabel": 'Percentile',
                        "layerData": generate_layer_data(length_for_age),
                        "tab": "CDC"
                    }
                )

                graphs.append(
                    {
                        "data": cdc_girls_weight_length,
                        "title": 'Weight for recumbent length (Girls)',
                        "xType": 'Length',
                        "yType": 'Weight',
                        "xLabel": 'Length',
                        "yLabel": 'Weight',
                        "zLabel": 'Percentile',
                        "layerData": generate_layer_data(weight_for_length),
                        "tab": "CDC"
                    }
                )

                graphs.append(
                    {
                        "data": cdc_girls_head_age,
                        "title": 'Head Circumference for age (Girls 0 - 36 months)',
                        "xType": 'Generic',
                        "yType": 'Length',
                        "xLabel": 'Age',
                        "yLabel": 'Length',
                        "zLabel": 'Percentile',
                        "layerData": generate_layer_data(head_for_age),
                        "tab": "CDC"
                    }
                )

                graphs.append(
                    {
                        "data": cdc_girls_weight_stature,
                        "title": 'Weight for stature (Girls)',
                        "xType": 'Length',
                        "yType": 'Weight',
                        "xLabel": 'Length',
                        "yLabel": 'Weight',
                        "zLabel": 'Percentile',
                        "layerData": generate_layer_data(weight_for_length),
                        "tab": "CDC"
                    }
                )

            if 24 <= age_in_months <= 240:
                graphs.append(
                    {
                        "data": cdc_girls_weight_age_24_240,
                        "title": 'Weight for age (Girls 2 - 20 years)',
                        "xType": 'Generic',
                        "yType": 'Weight',
                        "xLabel": 'Age',
                        "yLabel": 'Weight',
                        "zLabel": 'Percentile',
                        "layerData": generate_layer_data(weight_for_age),
                        "tab": "CDC"
                    }
                )

                graphs.append(
                    {
                        "data": cdc_girls_stature_age,
                        "title": 'Stature for age (Girls 2 - 20 years)',
                        "xType": 'Generic',
                        "yType": 'Length',
                        "xLabel": 'Age',
                        "yLabel": 'Length',
                        "zLabel": 'Percentile',
                        "layerData": generate_layer_data(length_for_age),
                        "tab": "CDC"
                    }
                )

                graphs.append(
                    {
                        "data": cdc_girls_bmi_age,
                        "title": 'Bmi for age (Girls 2 - 20 years)',
                        "xType": 'Generic',
                        "yType": 'Generic',
                        "xLabel": 'Age',
                        "yLabel": 'Length',
                        "zLabel": 'Percentile',
                        "layerData": generate_layer_data(bmi_for_age),
                        "tab": "CDC"
                    }
                )
        else:
            return []

        launch_modal = LaunchModalEffect(
            content=render_to_string("templates/chart.html", {"graphs": graphs}),
        )

        return [launch_modal.apply()]

