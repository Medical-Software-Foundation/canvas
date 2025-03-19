from __future__ import annotations

import json
from base64 import b64encode
from http import HTTPStatus

from logger import log
from requests import post as requests_post

from claim_coding_agent.protocols.llms.llm_base import LlmBase, HttpResponse


class LlmOpenai(LlmBase):

    def add_audio(self, audio: bytes, audio_format: str) -> None:
        if audio:
            self.audios.append({
                "format": audio_format,
                "data": b64encode(audio).decode("utf-8"),
            })

    def to_dict(self, for_log: bool = False) -> dict:
        roles = {
            self.ROLE_SYSTEM: "system",  # <-- for o1 models it should be "developer"
            self.ROLE_USER: "user",
            self.ROLE_MODEL: "assistant",
        }
        messages = [
            {
                "role": roles[prompt.role],
                "content": [{"type": "text", "text": "\n".join(prompt.text)}],
            }
            for prompt in self.prompts
        ]
        # on the first user input, add the audio, if any
        for audio in self.audios:
            messages[1]["content"].append({
                "type": "input_audio",
                "input_audio": "some audio" if for_log else audio,
            })

        return {
            "model": self.model,
            "modalities": ["text"],
            "messages": messages,
            "temperature": self.temperature,
        }

    def request(self, add_log: bool = False) -> HttpResponse:
        url = "https://api.openai.com/v1/chat/completions"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
            "OpenAI-Beta": "assistants=v2",
        }
        data = json.dumps(self.to_dict())
        request = requests_post(
            url,
            headers=headers,
            params={},
            data=data,
            verify=True,
            timeout=None,
        )
        result = HttpResponse(code=request.status_code, response=request.text)
        if result.code == HTTPStatus.OK.value:
            content = json.loads(request.text)
            text = content.get("choices", [{}])[0].get("message", {}).get("content", "")
            result = HttpResponse(code=result.code, response=text)

        if add_log:
            log.info("***** CHAT STARTS ******")
            log.info(json.dumps(self.to_dict(True), indent=2))
            log.info(f"response code: >{request.status_code}<")
            log.info(request.text)
            log.info("****** CHAT ENDS *******")

        return result

    def audio_to_text(self, audio: bytes) -> HttpResponse:
        default_model = "whisper-1"
        language = "en"
        response_format = "text"
        url = "https://api.openai.com/v1/audio/transcriptions"
        prompt = [
            "The conversation is in the medical context.",
        ]
        data = {
            "model": default_model,
            "language": language,
            "prompt": "\n".join(prompt),
            "response_format": response_format,
        }

        headers = {
            # "Content-Type": "multipart/form-data",
            "Authorization": f"Bearer {self.api_key}",
        }
        files = {"file": ("audio.mp3", audio, "application/octet-stream")}
        request = requests_post(
            url,
            headers=headers,
            params={},
            data=data,
            files=files,
            verify=True,
        )
        return HttpResponse(code=request.status_code, response=request.text)
