from logger import log
from urllib.parse import urlencode
from http import HTTPStatus

from canvas_sdk.effects import Effect
from canvas_sdk.effects.simple_api import JSONResponse, Response
from canvas_sdk.handlers.simple_api import SimpleAPI, api, APIKeyAuthMixin
from canvas_sdk.utils.http import ontologies_http


class ConditionsAPI(APIKeyAuthMixin, SimpleAPI):

    def handle_condition_lookup(self, search_params) -> list[Response | Effect]:
        log.info(f"Search condition by: {search_params}")

        response_json = ontologies_http.get_json(
            f"/icd/condition?{urlencode(search_params)}"
        ).json()

        count = 0
        results = []
        if response_json:
            for obj in response_json.get('results', []):
                icd_code = obj.get('icd10_code')
                name = obj.get('icd10_text')
                snomed_code = obj.get('snomed_concept_id')

                results.append({
                    "text": name, 
                    "value": icd_code, 
                    "coding": ([
                            {
                                "code": icd_code, 
                                "display": name, 
                                "system": 'ICD-10'
                            },
                        ] + (
                            [{
                                "code": f"{snomed_code}", 
                                "display": name, 
                                "system": 'http://snomed.info/sct'
                            }] if snomed_code else []
                        ))
                    })
                count = count + 1

        return {
            "count": count,
            "results": results
        }

    @api.get("/condition_search")
    def condition_search(self) -> list[Response | Effect]:
        """
            Search for conditions by text and/or ICD-10 code
        """
        log.info(f"Condition API received search with params {dict(self.request.query_params)}")

        text = self.request.query_params.get('text')
        icd10_code = self.request.query_params.get('icd10_code')

        # Search by either text OR ICD-10 code, not both
        if text and icd10_code:
            # Return error if both parameters are provided
            return [JSONResponse(
                {"error": "Provide either 'text' OR 'icd10_code', not both"},
                status_code=HTTPStatus.BAD_REQUEST,
            )]
        elif text:
            results = self.handle_condition_lookup({'search': text})
        elif icd10_code:
            results = self.handle_condition_lookup({'search': icd10_code})
        else:
            # Return error if neither parameter is provided
            return [JSONResponse(
                {"error": "Provide either 'text' OR 'icd10_code' parameter"},
                status_code=HTTPStatus.BAD_REQUEST,
            )]
        
        # Return results directly
        return [JSONResponse(
            results,
            status_code=HTTPStatus.OK,
        )]
