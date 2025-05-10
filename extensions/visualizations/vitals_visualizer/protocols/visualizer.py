import arrow, json

from http import HTTPStatus

from canvas_sdk.handlers.action_button import ActionButton
from canvas_sdk.handlers.simple_api import SimpleAPI, api, Credentials
from canvas_sdk.effects import Effect
from canvas_sdk.effects.launch_modal import LaunchModalEffect
from canvas_sdk.effects.simple_api import HTMLResponse, Response
from canvas_sdk.templates import render_to_string

from canvas_sdk.v1.data.observation import Observation

from logger import log


class VitalsVisualizerButton(ActionButton):

    BUTTON_TITLE = "Open Visualizer"
    BUTTON_KEY = "vitals_visualizer"
    BUTTON_LOCATION = ActionButton.ButtonLocation.CHART_SUMMARY_VITALS_SECTION

    def visible(self) -> bool:
        return Observation.objects.for_patient(self.target).filter(category="vital-signs", name="Vital Signs Panel").exclude(entered_in_error__isnull=False).exists()

    def handle(self):
        return [
            LaunchModalEffect(
                url=f"/plugin-io/api/vitals_visualizer/?patient={self.target}"
            ).apply()
        ]

class VisualApp(SimpleAPI):
    def authenticate(self, credentials: Credentials) -> bool:
        return True

    @api.get("/")
    def index(self) -> list[Response | Effect]:
        patient = self.request.query_params.get("patient")

        patient_vitals_dict = {}
        patient_panels = Observation.objects.for_patient(patient).filter(category="vital-signs", name="Vital Signs Panel").exclude(entered_in_error__isnull=False)
        for panel in patient_panels:
            patient_vitals_dict[str(panel.id)] = {"effective_datetime": arrow.get(panel.effective_datetime).isoformat(), "values": {}}

        patient_observations = Observation.objects.for_patient(
            patient
            ).filter(
                category="vital-signs",
                effective_datetime__isnull=False
              ).exclude(
                  name="Vital Signs Panel"
              ).exclude(entered_in_error__isnull=False
              ).select_related("is_member_of")

        # List of all possible vital fields
        vital_keys = {
            "weight": "Weight (lbs)",
            "body_temperature": "Body Temp (°F)",
            "blood_pressure_systolic": "Systolic BP (mmHg)",
            "blood_pressure_diastolic": "Diastolic BP (mmHg)",
            "oxygen_saturation": "Oxygen Sat (%)",
            "height": "Height (inches)",
            "waist_circumference": "Waist Circ (cm)",
            "pulse": "Pulse (bpm)",
            "respiration_rate": "Respiration Rate (bpm)"
        }

        graph_ranges = {
            "Weight (lbs)": { "min": 1, "max": 1500 },
            "Body Temp (°F)": { "min": 85, "max": 107 },
            "Systolic BP (mmHg)": { "min": 30, "max": 305 },
            "Diastolic BP (mmHg)": { "min": 20, "max": 180 },
            "Oxygen Sat (%)": { "min": 60, "max": 100 },
            "Waist Circ (cm)": { "min": 20, "max": 200 },
            "Pulse (bpm)": { "min": 30, "max": 250 },
            "Respiration Rate (bpm)": { "min": 6, "max": 60 },
            "Height (inches)": { "min": 10, "max": 108 }
        }

        for observation in patient_observations:
            value = observation.value
            if observation.name == "weight" and value:
                # convert
                value = float(observation.value) / 16
            elif observation.name == "blood_pressure" and value:
                # separate into systolic and diastolic
                systolic_val, diastolic_val = value.split("/")
                patient_vitals_dict[str(observation.is_member_of.id)]["values"]["Systolic BP (mmHg)"] = systolic_val
                patient_vitals_dict[str(observation.is_member_of.id)]["values"]["Diastolic BP (mmHg)"] = diastolic_val
                continue
            elif observation.name in ["note", "pulse_rhythm"]:
                continue
            patient_vitals_dict[str(observation.is_member_of.id)]["values"][vital_keys[observation.name]] = value

        # Sort records by datetime
        entries = sorted(
            patient_vitals_dict.values(),
            key=lambda x: x['effective_datetime']
        )

        # Convert datetimes
        dates = [
            arrow.get(entry['effective_datetime']).format('M/D/YYYY')
            for entry in entries
        ]

        # Helper function to parse numeric strings
        def try_parse(value):
            if not value:
                return None
            try:
                return float(value)
            except ValueError:
                return value  # keep string if it's like '120/80' or 'Regular'

        # Build vitalsData dictionary
        vitals_data = {
            key: [
                try_parse(entry["values"].get(key, ""))
                for entry in entries
            ]
            for key in vital_keys.values()
        }
            
        return [
            HTMLResponse(
                render_to_string(
                    "templates/index.html", 
                    context={
                        "data": json.dumps(vitals_data),
                        "dates": json.dumps(dates),
                        "graph_ranges": json.dumps(graph_ranges)
                    }
                ),
                status_code=HTTPStatus.OK,
            )
        ]

    @api.get("/style.css")
    def get_css(self) -> list[Response | Effect]:
        return [
            Response(
                render_to_string("templates/style.css").encode(),
                status_code=HTTPStatus.OK,
                content_type="text/css",
            )
        ]


