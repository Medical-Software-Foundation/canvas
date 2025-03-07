import datetime
import jwt

from http import HTTPStatus

from logger import log

from canvas_sdk.handlers.action_button import ActionButton
from canvas_sdk.effects import Effect
from canvas_sdk.effects.launch_modal import LaunchModalEffect
from canvas_sdk.handlers.simple_api import SimpleAPI, api, Credentials
from canvas_sdk.effects.simple_api import HTMLResponse, Response
from canvas_sdk.templates import render_to_string
from canvas_sdk.utils import Http
from canvas_sdk.v1.data.note import Note


class NablaLauncher(ActionButton):
    BUTTON_TITLE = "Launch Nabla"
    BUTTON_KEY = "LAUNCH_NABLA"
    BUTTON_LOCATION = ActionButton.ButtonLocation.NOTE_HEADER

    def handle(self) -> list[Effect]:
        """
        When clicked, jump through all auth hoops to end up with a user-specific
        access token that can be used in the client, and launch an iframe that
        provides the Nabla UI.
        """

        # 1. Create JWT to get backend JWT access_token
        #      POST https://us.api.nabla.com/v1/core/server/oauth/token
        #        NOTE: We should cache the resultant access_token, but we
        #        don't have a cache.
        #
        backend_access_token = self.get_backend_access_token()

        # 2. Get staff associated with note
        #      NOTE: This is a limitation, we assume the user for the scribe
        #      session is the staff associated with the note. We should enhance
        #      the event payload to include the logged in user that clicked.
        #
        staff_id = self.get_staff_id()

        # 3. Get nabla user id based on canvas staff key
        #      GET https://us.api.nabla.com/v1/core/server/users/find_by_external_id/:external_id
        #        If not found, create nabla user
        #            POST https://us.api.nabla.com/v1/core/server/users
        #
        nabla_user_id = self.get_nabla_user_id(staff_id, backend_access_token)

        # 4. Create a nabla user api token for the staff user using the backend JWT access token
        #      POST https://us.api.nabla.com/v1/core/server/jwt/authenticate/:user_id
        #        NOTE: We should cache the resultant access_token and
        #        refresh_token, but we don't have a cache.
        #
        user_access_token, user_refresh_token = self.get_user_tokens(nabla_user_id, backend_access_token)

        # 5. Launch a modal that utilizes the user access_token
        #

        return [
            LaunchModalEffect(
                target=LaunchModalEffect.TargetType.RIGHT_CHART_PANE,
                url=f"/plugin-io/api/nabla/?access_token={user_access_token}&refresh_token={user_refresh_token}"
            ).apply()
        ]

    def get_user_tokens(self, user_id, backend_access_token) -> tuple[str, str]:
        authenticate_response = Http().post(
            f"https://us.api.nabla.com/v1/core/server/jwt/authenticate/{user_id}",
            headers={"Authorization": f"Bearer {backend_access_token}"},
        )
        if authenticate_response.status_code == 200:
            # Success payload looks like this:
            # {
            #   "access_token": "eyJ0eXAiOiJ...",
            #   "refresh_token": "eyJ0eXAiOiJ..."
            # }
            payload = authenticate_response.json()
            return payload["access_token"], payload["refresh_token"]

        raise Exception("Could not authenticate nabla user")

    def get_nabla_user_id(self, staff_id, backend_access_token) -> str:
        search_response = Http().get(
            f"https://us.api.nabla.com/v1/core/server/users/find_by_external_id/{staff_id}",
            headers={"Authorization": f"Bearer {backend_access_token}"},
        )
        if search_response.status_code == 200:
            # Success payload looks like this:
            # {
            #   "id": "d0b90db0-2ca3-41aa-9751-63d931f58670",
            #   "activated": true,
            #   "external_id": "abc123",
            #   "metadata": null,
            #   "created_at": "2025-03-05T06:45:16.208Z"
            # }
            return search_response.json()["id"]

        if search_response.status_code == 400:
            # Error payload looks like this:
            # {
            #   "message": "A 'copilot_api_user' entity was not found.",
            #   "code": 20000,
            #   "name": "ENTITY_NOT_FOUND",
            #   "traceId": "projects/daring-runway-211808/traces/46766990e5176c84c2b12661748372ea",
            #   "debuggingHints": []
            # }
            
            # Since the user doesn't exist yet, let's create them.
            create_response = Http().post(
                "https://us.api.nabla.com/v1/core/server/users",
                json={"external_id": staff_id},
                headers={"Authorization": f"Bearer {backend_access_token}"},
            )

            if create_response.status_code == 200:
                # Success payload looks like this:
                # {
                #   "id": "a760124c-c6b9-416e-9943-287851eb4a91",
                #   "activated": true,
                #   "external_id": "def456",
                #   "metadata": null,
                #   "created_at": "2025-03-05T06:49:42.464Z"
                # }
                return create_response.json()["id"]

            log.error(f"Could not create nabla user for staff {staff_id}")
            raise Exception(f"Could not create nabla user for staff {staff_id}")



    def get_staff_id(self) -> str:
        note_dbid = self.context['note_id']
        return Note.objects.values_list('provider__id', flat=True).get(dbid=note_dbid)

    def get_backend_access_token(self) -> str:
        # TODO: Cache this token with a TTL = to the returned "expires_in" - 1s
        private_key = self.secrets["JWK_PRIVATE_KEY"].encode()
        client_id = self.secrets["NABLA_OAUTH_CLIENT_ID"]

        claimset = {
            "sub": client_id,
            "iss": client_id,
            "aud": "https://us.api.nabla.com/v1/core/server/oauth/token",
            "exp": int((datetime.datetime.now() + datetime.timedelta(minutes=3)).timestamp()),
        }

        encoded_claimset = jwt.encode(claimset, private_key, algorithm="RS256")

        response = Http().post(
            "https://us.api.nabla.com/v1/core/server/oauth/token",
            json={
                "grant_type": "client_credentials",
                "client_assertion_type": "urn:ietf:params:oauth:client-assertion-type:jwt-bearer",
                "client_assertion": encoded_claimset
            }
        )
        return response.json()['access_token']


class NablaApp(SimpleAPI):
    def authenticate(self, credentials: Credentials) -> bool:
        return True

    @api.get("/")
    def index(self) -> list[Response | Effect]:
        context = {
            "user_access_token": self.request.query_params.get("access_token", ["missing"])[0],
            "user_refresh_token": self.request.query_params.get("refresh_token", ["missing"])[0],
        }
        return [
            HTMLResponse(
                render_to_string("static/index.html", context),
                status_code=HTTPStatus.OK,
            )
        ]

    @api.get("/main.js")
    def get_main_js(self) -> list[Response | Effect]:
        return [
            Response(
                render_to_string("static/main.js").encode(),
                status_code=HTTPStatus.OK,
                content_type="text/javascript",
            )
        ]

    @api.get("/rawPcm16Processor.js")
    def get_audio_js(self) -> list[Response | Effect]:
        return [
            Response(
                render_to_string("static/rawPcm16Processor.js").encode(),
                status_code=HTTPStatus.OK,
                content_type="text/javascript",
            )
        ]

    @api.get("/style.css")
    def get_css(self) -> list[Response | Effect]:
        return [
            Response(
                render_to_string("static/style.css").encode(),
                status_code=HTTPStatus.OK,
                content_type="text/css",
            )
        ]
