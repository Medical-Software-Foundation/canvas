from http import HTTPStatus

from canvas_sdk.caching.plugins import get_cache
from canvas_sdk.effects import Effect
from canvas_sdk.effects.simple_api import JSONResponse, HTMLResponse, Response
from canvas_sdk.handlers.simple_api import SessionCredentials, SimpleAPI, api
from canvas_sdk.templates import render_to_string
from canvas_sdk.v1.data.patient import Patient

#
# Check out https://docs.canvasmedical.com/sdk/handlers-simple-api-http


class MyWebApp(SimpleAPI):
    PREFIX = "/app"

    # Using session credentials allows us to ensure only logged in users can
    # access this.
    def authenticate(self, credentials: SessionCredentials) -> bool:
        return credentials.logged_in_user != None

    # Store the id of the ServiceEligibility so we can fetch the results as
    # needed
    @api.post("/store-eligibility-id")
    def store_eligibility_id(self) -> list[Response | Effect]:
        # POST /store-eligibility-id
        # {
        #   "ServiceEligibility": {
        #     "id": "abc123"
        #   }
        # }
        logged_in_user = Patient.objects.get(id=self.request.headers["canvas-logged-in-user-id"])

        request_body = self.request.json()
        service_eligibility_id = request_body["ServiceEligibility"]["id"]

        # We want to store this in a way that makes it retrievable knowing
        # nothing but the patient's id. We don't get any part of this cache
        # key from the request body. Since the request is made by the
        # patient's client, we need to make sure they can only store data for
        # themselves, therefore, we use the id based on who the session data
        # says the request originated from.
        cache_key = f"service-eligibility-id:{logged_in_user.id}"
        cache = get_cache()
        # Max TTL on the cache is 14 days
        fourteen_days_in_seconds = 14 * 24 * 60 * 60  # days * hours * minutes * seconds
        cache.set(cache_key, service_eligibility_id, timeout_seconds=fourteen_days_in_seconds)

        return [
            JSONResponse({"message": "Stored!"})
        ]

    # Serve templated HTML
    @api.get("/bridge-eligibility")
    def index(self) -> list[Response | Effect]:
        logged_in_user = Patient.objects.get(id=self.request.headers["canvas-logged-in-user-id"])
        cache_key = f"service-eligibility-id:{logged_in_user.id}"
        cache = get_cache()

        existing_service_request_id = cache.get(cache_key)

        context = {
            "first_name": logged_in_user.first_name,
            "last_name": logged_in_user.last_name,
            "existing_service_request_id": existing_service_request_id,
        }

        return [
            HTMLResponse(
                render_to_string("portal_experience/static/index.html", context),
                status_code=HTTPStatus.OK,
            )
        ]

    # Serve the contents of a js file
    @api.get("/main.js")
    def get_main_js(self) -> list[Response | Effect]:
        return [
            Response(
                render_to_string("portal_experience/static/main.js").encode(),
                status_code=HTTPStatus.OK,
                content_type="text/javascript",
            )
        ]

    # Serve the contents of a css file
    @api.get("/styles.css")
    def get_css(self) -> list[Response | Effect]:
        return [
            Response(
                render_to_string("portal_experience/static/styles.css").encode(),
                status_code=HTTPStatus.OK,
                content_type="text/css",
            )
        ]
