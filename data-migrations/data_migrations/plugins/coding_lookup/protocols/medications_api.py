from logger import log
from urllib.parse import urlencode
from http import HTTPStatus

from canvas_sdk.effects import Effect
from canvas_sdk.effects.simple_api import JSONResponse, Response
from canvas_sdk.handlers.simple_api import SimpleAPI, api, APIKeyAuthMixin
from canvas_sdk.utils.http import ontologies_http


class MedicationsAPI(APIKeyAuthMixin, SimpleAPI):

    def handle_medication_lookup(self, params) -> list[Response | Effect]:
        log.info(f"Search medication by: {params}")

        response_json = ontologies_http.get_json(
            f"/fdb/grouped-medication/?{urlencode(params)}"
        ).json()

        count = 0
        results = []
        if response_json:
            for obj in response_json.get('results', []):
                fdb_code = obj.get('med_medication_id')
                name = obj.get('med_medication_description')
                rxnorm = obj.get('rxnorm_rxcui')

                results.append({
                    "text": name, 
                    "value": fdb_code, 
                    "coding": ([
                            {
                                "code": fdb_code, 
                                "display": name, 
                                "system": "http://www.fdbhealth.com/"
                            },
                        ] + (
                            [{
                                "code": rxnorm, 
                                "display": name, 
                                "system": "http://www.nlm.nih.gov/research/umls/rxnorm"
                            }] if rxnorm else []
                        ))
                    })
                count = count + 1

        return {
            "count": count,
            "results": results
        }

    @api.get("/medication_search")
    def medication_search(self) -> list[Response | Effect]:
        """
            Search for medications by text and/or rxnorm code
        """
        log.info(f"Medication API received search with params {dict(self.request.query_params)}")

        text = self.request.query_params.get('text')
        rxnorm_code = self.request.query_params.get('rxnorm_code')

        # Check if at least one parameter is provided
        if not text and not rxnorm_code:
            # Return error if neither parameter is provided
            return [JSONResponse(
                {"error": "Provide at least one of: 'text' OR 'rxnorm_code' parameter"},
                status_code=HTTPStatus.BAD_REQUEST,
            )]

        # Build search parameters (both can be used together)
        search_params = {}
        if text:
            search_params['search'] = text
        if rxnorm_code:
            search_params['rxnorm_rxcui'] = f'{rxnorm_code}'

        results = self.handle_medication_lookup(search_params)

        return [JSONResponse(
            results,
            status_code=HTTPStatus.OK,
        )]