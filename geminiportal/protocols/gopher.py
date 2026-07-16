from __future__ import annotations

import ssl

from quart import Response as QuartResponse
from quart import render_template

from geminiportal.errors import UpstreamResponseError
from geminiportal.handlers.gopher import GopherItem
from geminiportal.protocols.base import (
    BaseProxyResponseBuilder,
    BaseRequest,
    BaseResponse,
)
from geminiportal.utils import smart_decode


class GopherRequest(BaseRequest):
    """
    Encapsulates a gopher:// request.
    """

    async def fetch(self) -> GopherResponse | GopherPlusResponse:
        if self.url.scheme == "gophers":
            context = self.make_ssl_context()
        else:
            context = None

        reader, writer = await self.open_connection(ssl=context)

        request = self.url.get_gopher_request()
        writer.write(request)
        await writer.drain()

        if not self.url.gopher_plus_string:
            return GopherResponse(self, reader, writer)

        # Parse the response header for gopher+
        raw_header = await reader.readline()

        if raw_header[:1] == b"+":
            status, meta = "", ""
        elif raw_header[:1] == b"-":
            raw_status_line = await reader.readline()
            status_line = raw_status_line.decode()
            status, meta = status_line[0], status_line[1:]
        else:
            raise UpstreamResponseError("Invalid response, this server does not support Gopher+.")

        header = raw_header.decode()
        try:
            data_length = int(header[1:])
        except ValueError:
            raise UpstreamResponseError(
                f'Invalid length in Gopher+ response header: "{header.strip()}"'
            )
        meta = meta.strip()

        return GopherPlusResponse(
            self,
            reader=reader,
            writer=writer,
            status=status,
            meta=meta,
            data_length=data_length,
        )

    def make_ssl_context(self) -> ssl.SSLContext:
        context = ssl.create_default_context()
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE
        return context


class GopherResponse(BaseResponse):
    def __init__(self, request, reader, writer):
        self.request = request
        self.reader = reader
        self.writer = writer
        self.status = ""
        self.meta = ""
        self.lang = None
        self.charset = request.options.charset

        self.mimetype = self.url.guess_mimetype() or "application/octet-stream"
        self.proxy_response_builder = GopherProxyResponseBuilder(self)


class GopherPlusResponse(BaseResponse):
    STATUS_CODES = {
        "": "Success",
        "1": "Item is not available",
        "2": "Try again later",
        "3": "Item has moved",
    }

    def __init__(self, request, reader, writer, status, meta, data_length):
        self.request = request
        self.reader = reader
        self.writer = writer
        self.status = status
        self.meta = meta
        self.lang = None
        self.charset = request.options.charset

        # The data length flags make chunking the response stream very annoying,
        # so I'm going to ignore this feature and always wait for the server to
        # close the connection.
        self.data_length: int = data_length

        if self.status:
            self.mimetype = "text/plain"
        else:
            self.mimetype = self.url.guess_mimetype() or "application/octet-stream"

        self.proxy_response_builder = GopherPlusProxyResponseBuilder(self)


class GopherProxyResponseBuilder(BaseProxyResponseBuilder):
    response: GopherResponse

    async def build_proxy_response(self):
        return await self.render_from_handler()


class GopherPlusProxyResponseBuilder(BaseProxyResponseBuilder):
    response: GopherPlusResponse

    async def build_proxy_response(self):
        if self.response.status == "3":
            item = GopherItem.from_item_description(self.response.meta, self.response.url)
            content = await render_template(
                "proxy/gopher-plus-redirect.html",
                response=self.response,
                url=item.url,
            )
            return QuartResponse(content)
        elif self.response.status:
            data = await self.response.get_body(truncate=True)
            body, _ = smart_decode(data, self.response.charset)
            body = body.strip()
            content = await render_template(
                "proxy/gopher-plus-error.html",
                response=self.response,
                body=body,
            )
            return QuartResponse(content)
        else:
            return await self.render_from_handler()
