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


class ScoringVisualizerButton(ActionButton):

    BUTTON_TITLE = "Open Visualizer"
    BUTTON_KEY = "scoring_visualizer"
    BUTTON_LOCATION = ActionButton.ButtonLocation.CHART_SUMMARY_SOCIAL_DETERMINANTS_SECTION

    def visible(self) -> bool:
        return Observation.objects.for_patient(self.target).filter(category="survey").exclude(entered_in_error__isnull=False).exists()

    def handle(self):
        return [
            LaunchModalEffect(
                url=f"/plugin-io/api/scoring_visualizer/?patient={self.target}"
            ).apply()
        ]

class VisualApp(SimpleAPI):
    def authenticate(self, credentials: Credentials) -> bool:
        return True

    @api.get("/")
    def index(self) -> list[Response | Effect]:
        patient = self.request.query_params.get("patient")

        patient_observation_dict = {}
        patient_surveys = Observation.objects.for_patient(patient).filter(category="survey").exclude(entered_in_error__isnull=False)

        for survey in patient_surveys:
            value = survey.value
            created_date = arrow.get(survey.created).to("America/New_York").format("M/D/YYYY")
            if created_date in patient_observation_dict:
                patient_observation_dict[created_date][survey.name] = value
            else:
                patient_observation_dict[created_date]= {survey.name: value}

        # Step 1: Sort and normalize dates
        sorted_items = sorted(patient_observation_dict.items(), key=lambda x: arrow.get(x[0], 'M/D/YYYY'))

        # Step 2: Build list of all questionnaire names
        all_keys = set()
        for _, values in sorted_items:
            all_keys.update(values.keys())

        # Step 3: Initialize datasets dict with empty lists
        data = {key: [] for key in all_keys}

        # Step 4: Extract labels and build datasets
        dates = []
        for date_str, values in sorted_items:
            dates.append(date_str)
            for key in all_keys:
                val = values.get(key)
                data[key].append(float(val) if val else None)

        return [
            HTMLResponse(
                render_to_string(
                    "templates/index.html", 
                    context={
                        "data": json.dumps(data),
                        "dates": json.dumps(dates)
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

