from __future__ import annotations

from geminiportal.protocols.base import BaseRequest
from geminiportal.protocols.gemini import GeminiResponse
from geminiportal.tls import CloseNotifyState
from geminiportal.urls import URLReference
from geminiportal.utils import ProxyOptions


class TitanRequest(BaseRequest):
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

    async def fetch(self) -> GeminiResponse:
        context = self.create_ssl_context()
        reader, writer = await self.open_connection(ssl=context)

        ssock = writer.get_extra_info("ssl_object")
        tls_close_notify = CloseNotifyState(ssock)

        tls_cert = ssock.getpeercert(True)
        tls_version = ssock.version()
        tls_cipher, _, _ = ssock.cipher()

        data = self.url.get_titan_request(len(self.content), self.mime, self.token)
        writer.write(data)
        writer.write(self.content)
        await writer.drain()

        raw_header = await reader.readline()
        status, meta = self.parse_response_header(raw_header)

        return GeminiResponse(
            request=self,
            reader=reader,
            writer=writer,
            status=status,
            meta=meta,
            tls_cert=tls_cert,
            tls_version=tls_version,
            tls_cipher=tls_cipher,
            tls_close_notify=tls_close_notify,
        )
