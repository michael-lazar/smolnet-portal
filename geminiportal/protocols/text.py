from __future__ import annotations

from quart import Response as QuartResponse
from quart import render_template
from werkzeug.utils import redirect

from geminiportal.errors import UpstreamResponseError
from geminiportal.protocols.base import (
    BaseProxyResponseBuilder,
    BaseRequest,
    BaseResponse,
)


class TxtRequest(BaseRequest):
    """
    Encapsulates a text:// request.
    """

    async def fetch(self) -> TxtResponse:
        reader, writer = await self.open_connection()

        data = self.url.get_gemini_request()
        writer.write(data)
        await writer.drain()

        raw_header = await reader.readline()
        status, meta = self.parse_response_header(raw_header)

        return TxtResponse(self, reader, writer, status, meta)


class TxtResponse(BaseResponse):
    STATUS_CODES = {
        "20": "OK",
        "30": "REDIRECT",
        "40": "NOK",
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

        self.proxy_response_builder = TxtProxyResponseBuilder(self)


class TxtProxyResponseBuilder(BaseProxyResponseBuilder):
    response: TxtResponse

    async def build_proxy_response(self):
        if self.response.status == "20":
            return await self.render_from_handler()

        elif self.response.status == "30":
            location = self.response.url.join(self.response.meta).get_proxy_url()
            return redirect(location, 307)

        elif self.response.status == "40":
            content = await render_template(
                "proxy/error-response.html",
                error=self.response.status_display,
                message=self.response.meta,
            )
            return QuartResponse(content)

        else:
            raise UpstreamResponseError(
                f'The server returned an unrecognized status code "{self.response.status}".'
            )
