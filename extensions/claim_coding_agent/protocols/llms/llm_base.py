from __future__ import annotations

import json
import re
from http import HTTPStatus

from canvas_sdk.questionnaires.utils import Draft7Validator
from logger import log
from typing import NamedTuple

class Constants:
    OPENAI_CHAT_TEXT = "gpt-4o"
    MAX_ATTEMPTS_LLM_HTTP = 3
    MAX_ATTEMPTS_LLM_JSON = 3

class LlmTurn(NamedTuple):
    role: str
    text: list[str]


class HttpResponse(NamedTuple):
    code: int
    response: str


class JsonExtract(NamedTuple):
    error: str
    has_error: bool
    content: list



class LlmBase:
    ROLE_SYSTEM = "system"
    ROLE_USER = "user"
    ROLE_MODEL = "model"

    def __init__(self, api_key: str, model: str):
        self.api_key = api_key
        self.model = model
        self.temperature = 0.0
        self.prompts: list[LlmTurn] = []
        self.audios: list[dict] = []

    def set_system_prompt(self, prompt: list[str]) -> None:
        self.prompts.append(LlmTurn(role=self.ROLE_SYSTEM, text=prompt))

    def set_user_prompt(self, prompt: list[str]) -> None:
        self.prompts.append(LlmTurn(role=self.ROLE_USER, text=prompt))

    def set_model_prompt(self, prompt: list[str]) -> None:
        self.prompts.append(LlmTurn(role=self.ROLE_MODEL, text=prompt))

    def add_audio(self, audio: bytes, audio_format: str) -> None:
        raise NotImplementedError()

    def request(self, add_log: bool = False) -> HttpResponse:
        raise NotImplementedError()

    def attempt_requests(self, attempts: int, add_log: bool = False) -> HttpResponse:
        for _ in range(attempts):
            result = self.request(add_log=add_log)
            if result.code == HTTPStatus.OK.value:
                break
        else:
            result = HttpResponse(
                code=HTTPStatus.TOO_MANY_REQUESTS,
                response=f"max attempts ({attempts}) exceeded",
            )
        return result

    def chat(self, schemas: list, add_log: bool = False) -> JsonExtract:
        for _ in range(Constants.MAX_ATTEMPTS_LLM_JSON):
            response = self.attempt_requests(Constants.MAX_ATTEMPTS_LLM_HTTP, add_log=add_log)
            # http error
            if response.code != HTTPStatus.OK.value:
                result = JsonExtract(has_error=True, error=response.response, content=[])
                break

            result = self.extract_json_from(response.response, schemas)
            if result.has_error is False:
                break

            # JSON error
            self.set_model_prompt(response.response.splitlines())
            self.set_user_prompt([
                "Your previous response has the following errors:",
                "```text",
                result.error,
                "```",
                "",
                "Please, correct your answer following rigorously the initial request and the mandatory response format."
            ])
        else:
            result = JsonExtract(
                has_error=True,
                error=f"max attempts ({Constants.MAX_ATTEMPTS_LLM_JSON}) exceeded",
                content=[],
            )

        return result

    def single_conversation(self, system_prompt: list[str], user_prompt: list[str], schemas: list) -> list:
        self.set_system_prompt(system_prompt)
        self.set_user_prompt(user_prompt)
        response = self.chat(schemas)
        if response.has_error is False and response.content:
            return response.content
        return []

    @classmethod
    def json_validator(cls, response: list, json_schema: dict) -> str:
        result: list = []
        for error in Draft7Validator(json_schema).iter_errors(response):
            # assert isinstance(error, ValidationError)
            message = error.message
            if error.path:
                message = f"{error.message}, in path {list(error.path)}"
            result.append(message)

        return "\n".join(result)

    @classmethod
    def extract_json_from(cls, content: str, schemas: list) -> JsonExtract:
        # print("-------------------------------------------------")
        # print(content)
        # print("-------------------------------------------------")
        result: list = []
        pattern_json = re.compile(r"```json\s*\n(.*?)\n\s*```", re.DOTALL | re.IGNORECASE)
        for embedded in pattern_json.finditer(content):
            try:
                result.append(json.loads(embedded.group(1)))
            except Exception as e:
                log.info(e)
                log.info("---->")
                log.info(embedded)
                log.info("<----")
                return JsonExtract(error=str(e), has_error=True, content=[])

        if not result:
            return JsonExtract(error="No JSON markdown found", has_error=True, content=[])

        # check against the schemas
        for idx, (returned, validation) in enumerate(zip(result, schemas or [])):
            if problems := cls.json_validator(returned, validation):
                return JsonExtract(error=f"in the JSON #{idx + 1}:{problems}", has_error=True, content=[])

        # all good
        if len(result) == 1:
            return JsonExtract(error="", has_error=False, content=result[0])
        return JsonExtract(error="", has_error=False, content=result)
