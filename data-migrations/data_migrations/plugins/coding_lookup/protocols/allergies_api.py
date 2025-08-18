import json

from logger import log

from urllib.parse import urlencode

from canvas_sdk.utils.http import ontologies_http

from http import HTTPStatus

from canvas_sdk.effects import Effect
from canvas_sdk.effects.simple_api import JSONResponse, Response
from canvas_sdk.handlers.simple_api import SimpleAPI, api, APIKeyAuthMixin


content_type_map = {
    "1": "medication",
    "104": "ingredient",
    "110": "allergy group"
}

content_type_category_map = {
    "medication": "2",
    "ingredient": "6",
    "allergy group": "1"
}


class AllergiesAPI(APIKeyAuthMixin, SimpleAPI):

    def handle_allergy_text_lookup(self, text) -> list[Response | Effect]:
        log.info(f"Search allergy by text: {text}")
        response_json = ontologies_http.get_json(
            f"/fdb/allergy?{urlencode({'dam_allergen_concept_id_description__fts': text})}"
        ).json()

        count = 0
        results = []
        if response_json:
            for obj in response_json.get('results', []):
                content_type = obj['concept_type']
                concept_id = f"{int(obj['dam_allergen_concept_id'])}"
                results.append({
                        "display": obj['dam_allergen_concept_id_description'],
                        "concept_type": content_type,
                        "concept_id": concept_id,
                        "code": f"{content_type_category_map[content_type]}-{concept_id}",
                        "system": "http://www.fdbhealth.com/"
                    })
                count = count + 1

        return {
            "count": count,
            "results": results
        }

    def handle_allergy_rxnorm_lookup(self, rxnorm_code) -> list[Response | Effect]:
        log.info(f"Search allergy by rxnorm_code: {rxnorm_code}")
        code = f'rxnorm|{rxnorm_code}'
        response_json = ontologies_http.get_json(
            f"/fdb/allergen?{urlencode({'code': code})}"
        ).json()

        content_type_map = {
            "1": "medication",
            "104": "ingredient",
            "110": "allergy group"
        }

        count = 0
        results = []
        if response_json:
            for obj in response_json.get('results', []):
                content_type = content_type_map[str(int(obj['evd_fdb_vocabulary_type_identifier']))]
                concept_id = f"{int(obj['imk_fdb_vocabulary_no_identifier'])}"
                results.append({
                        "display": obj['imk_fdb_vocabulary_description'],
                        "concept_type": content_type,
                        "concept_id": concept_id,
                        "code": f"{content_type_category_map[content_type]}-{concept_id}",
                        "system": "http://www.fdbhealth.com/"
                    })
                count = count + 1

        return {
            "count": count,
            "results": results
        }

    @api.get("/allergy_search")
    def allergy_search(self) -> list[Response | Effect]:
        """
            Search for allergies by text or rxnorm code
        """
        log.info(f"Allergy API received search with params {dict(self.request.query_params)}")

        text = self.request.query_params.get('text')
        rxnorm_code = self.request.query_params.get('rxnorm_code')

        # Search by either text OR rxnorm_code, not both
        if text and rxnorm_code:
            # Return error if both parameters are provided
            return [JSONResponse(
                {"error": "Provide either 'text' OR 'rxnorm_code', not both"},
                status_code=HTTPStatus.BAD_REQUEST,
            )]
        elif rxnorm_code:
            results = self.handle_allergy_rxnorm_lookup(rxnorm_code)
        elif text:
            results = self.handle_allergy_text_lookup(text)
        else:
            # Return error if neither parameter is provided
            return [JSONResponse(
                {"error": "Provide either 'text' OR 'rxnorm_code' parameter"},
                status_code=HTTPStatus.BAD_REQUEST,
            )]

        return [JSONResponse(
            results,
            status_code=HTTPStatus.OK,
        )]