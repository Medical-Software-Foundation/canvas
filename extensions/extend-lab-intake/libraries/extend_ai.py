from http import HTTPStatus
from typing import TypeVar, Type
from urllib.parse import urlencode

from canvas_sdk.utils.http import Http
from requests import delete as requests_delete, Response

from pdf_extract.structures.extend_config.extend_config_extract import ExtendConfigExtract
from pdf_extract.structures.extend_file import ExtendFile
from pdf_extract.structures.extend_processor_meta import ExtendProcessorMeta
from pdf_extract.structures.extend_processor_type import ExtendProcessorType
from pdf_extract.structures.extend_processor_version import ExtendProcessorVersion
from pdf_extract.structures.extend_run import ExtendRun
from pdf_extract.structures.extend_version import ExtendVersion
from pdf_extract.structures.request_failed import RequestFailed
from pdf_extract.structures.structure import Structure

T = TypeVar('T', bound=Structure)


class ExtendAi:
    def __init__(self, key: str) -> None:
        self.http = Http("https://api.extend.ai")
        self.headers = {
            "x-extend-api-version": "2025-04-21",
            "Authorization": f"Bearer {key}",
        }

    @classmethod
    def valid_content(cls, request: Response, key: str, returned_class: Type[T]) -> T | RequestFailed:
        if request.status_code == HTTPStatus.OK and (response := request.json()) and response["success"]:
            return returned_class.from_dict(response[key])
        return RequestFailed(status_code=request.status_code, message=request.content.decode())

    def valid_content_list(self, url: str, key: str, returned_class: Type[T]) -> list[T] | RequestFailed:
        result: list[T] = []
        base_url = url
        while True:
            request = self.http.get(url, headers=self.headers)
            if request.status_code == HTTPStatus.OK and (response := request.json()) and response["success"]:
                result.extend([returned_class.from_dict(item) for item in response[key]])
                next_page_token = response.get("nextPageToken")
                if not next_page_token:
                    break
                url = f"{base_url}?{urlencode({'nextPageToken': next_page_token})}"
            else:
                return RequestFailed(status_code=request.status_code, message=request.content.decode())
        return result

    def list_files(self) -> list[ExtendFile] | RequestFailed:
        return self.valid_content_list("/files", "files", ExtendFile)

    def delete_file(self, file_id: str) -> bool | RequestFailed:
        url = f"https://api.extend.ai/files/{file_id}"
        request = requests_delete(url, headers=self.headers)
        if request.status_code == HTTPStatus.OK and (response := request.json()) and response["success"]:
            return bool(response["success"])
        return RequestFailed(status_code=request.status_code, message=request.content.decode())

    def list_processors(self) -> list[ExtendProcessorMeta] | RequestFailed:
        return self.valid_content_list("/processors", "processors", ExtendProcessorMeta)

    def processor(self, processor_id: str, version: str) -> ExtendProcessorVersion | RequestFailed:
        if not version:
            version = ExtendVersion.DRAFT.value
        request = self.http.get(f"/processors/{processor_id}/versions/{version}", headers=self.headers)
        return self.valid_content(request, "version", ExtendProcessorVersion)

    def create_processor(self, name: str, config: ExtendConfigExtract) -> ExtendProcessorMeta | RequestFailed:
        headers = self.headers | {"Content-Type": "application/json"}
        data = {
            "name": name,
            "type": ExtendProcessorType.EXTRACT.value,
            "config": config.to_dict(),
        }
        request = self.http.post("/processors", headers=headers, json=data)
        return self.valid_content(request, "processor", ExtendProcessorMeta)

    def run_status(self, run_id: str) -> ExtendRun | RequestFailed:
        request = self.http.get(f"/processor_runs/{run_id}", headers=self.headers)
        return self.valid_content(request, "processorRun", ExtendRun)

    def run_processor(self, processor_id: str, file_name: str, file_url: str, config: ExtendConfigExtract | None) -> ExtendRun | RequestFailed:
        headers = self.headers | {"Content-Type": "application/json"}
        data = {
            "processorId": processor_id,
            "file": {
                "fileName": file_name,
                "fileUrl": file_url,
            },
        }
        if config is not None:
            data = data | {"config": config.to_dict()}
        request = self.http.post("/processor_runs", headers=headers, json=data)
        return self.valid_content(request, "processorRun", ExtendRun)
