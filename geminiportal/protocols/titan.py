from __future__ import annotations

from geminiportal.protocols.gemini import (
    GeminiProxyResponseBuilder,
    GeminiRequest,
    GeminiResponse,
)
from geminiportal.urls import URLReference
from geminiportal.utils import ProxyOptions


class TitanRequest(GeminiRequest):
    """
    Encapsulates a titan:// request.

    Titan is the file upload companion to the gemini protocol. The client
    sends a gemini-style URL with size/mime/token parameters attached,
    followed immediately by the upload content, and the server replies
    with a regular gemini response.
    """

    content: bytes
    mime: str | None
    token: str | None

    def __init__(self, url: URLReference, options: ProxyOptions):
        super().__init__(url, options)
        self.content = b""
        self.mime = None
        self.token = None

    def set_upload(self, content: bytes, mime: str | None = None, token: str | None = None):
        self.content = content
        self.mime = mime
        self.token = token

    def get_request_data(self) -> bytes:
        request = self.url.get_titan_request(len(self.content), self.mime, self.token)
        return request + self.content

    @property
    def response_class(self) -> type[GeminiResponse]:
        return TitanResponse


class TitanResponse(GeminiResponse):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.proxy_response_builder = TitanProxyResponseBuilder(self)


class TitanProxyResponseBuilder(GeminiProxyResponseBuilder):
    response: TitanResponse

    # Redirect with a 303 so the browser follows up with a GET request,
    # instead of re-submitting the upload form to the new location.
    redirect_code = 303
