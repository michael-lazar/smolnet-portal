from __future__ import annotations

from urllib.parse import quote_from_bytes, unquote_to_bytes

from quart import Response as QuartResponse
from quart import render_template
from werkzeug.utils import redirect

from geminiportal.errors import UpstreamResponseError
from geminiportal.protocols.base import (
    BaseProxyResponseBuilder,
    BaseRequest,
    BaseResponse,
)


class SpartanRequest(BaseRequest):
    """
    Encapsulates a spartan:// request.
    """

    async def fetch(self) -> SpartanResponse:
        reader, writer = await self.open_connection()

        path = self.url.path or "/"
        data = unquote_to_bytes(self.url.query)

        encoded_host = self.host.encode("idna")
        encoded_path = quote_from_bytes(unquote_to_bytes(path)).encode("ascii")

        request = b"%s %s %d\r\n%b" % (encoded_host, encoded_path, len(data), data)
        writer.write(request)
        await writer.drain()

        raw_header = await reader.readline()
        status, meta = self.parse_response_header(raw_header)

        return SpartanResponse(self, reader, writer, status, meta)


class SpartanResponse(BaseResponse):
    STATUS_CODES = {
        "2": "SUCCESS",
        "3": "REDIRECT",
        "4": "CLIENT ERROR",
        "5": "SERVER ERROR",
    }

    def __init__(self, request, reader, writer, status, meta):
        self.request = request
        self.reader = reader
        self.writer = writer
        self.status = status
        self.meta = meta

        self.mimetype, params = self.parse_meta(meta)
        self.charset = request.options.charset or params.get("charset", "UTF-8")
        self.lang = None

        self.proxy_response_builder = SpartanProxyResponseBuilder(self)


class SpartanProxyResponseBuilder(BaseProxyResponseBuilder):
    response: SpartanResponse

    async def build_proxy_response(self):
        if self.response.status.startswith("2"):
            return await self.render_from_handler()

        elif self.response.status.startswith("3"):
            location = self.response.url.join(self.response.meta).get_proxy_url()
            return redirect(location, 307)

        elif self.response.status.startswith(("4", "5")):
            content = await render_template(
                "proxy/server-error.html",
                error=self.response.status_display,
                message=self.response.meta,
            )
            return QuartResponse(content)

        else:
            raise UpstreamResponseError(
                f'The server returned an unrecognized status code "{self.response.status}".'
            )
