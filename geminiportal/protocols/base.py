from __future__ import annotations

import asyncio
import logging
import re
import socket
import ssl
from asyncio.exceptions import IncompleteReadError
from collections.abc import AsyncIterator

from quart import Response as QuartResponse
from werkzeug.wrappers.response import Response as WerkzeugResponse

from geminiportal.handlers import get_handler_class
from geminiportal.handlers.base import BaseHandler, StreamHandler
from geminiportal.urls import URLReference
from geminiportal.utils import ProxyOptions

_logger = logging.getLogger(__name__)

# Chunk size for streaming files, taken from the twisted FileSender class
CHUNK_SIZE = 2**14

# When not streaming, limit the maximum response size to avoid running out
# of RAM when downloading & converting large files to HTML.
MAX_BODY_SIZE = 2**20

# Hosts that have requested that their content be removed from the proxy
BLOCKED_HOSTS = [
    "vger.cloud",
    "warpengineer.space",
    "michaelnordmeyer.com",
]

# Ports that the proxied servers can be hosted on
ALLOWED_PORTS = {
    70,
    77,
    79,
    300,
    301,
    3000,
    3333,
    1900,
    *range(1960, 2021),
    5699,
    *range(7000, 7100),
    8070,
}

# Time waiting to establish a connection before aborting
CONNECT_TIMEOUT = 10


class ProxyError(Exception):
    pass


class ProxyResponseSizeError(ProxyError):
    def __init__(self, partial: bytes):
        super().__init__(f"Maximum response size of {len(partial)} bytes read.")
        self.partial = partial


class BaseRequest:
    """
    Encapsulates a request to a protocol.
    """

    _blocked_hosts = [re.compile(rf"(?:.+\.)?{host}\.?$", flags=re.I) for host in BLOCKED_HOSTS]

    def __init__(self, url: URLReference, options: ProxyOptions):
        self.url = url
        self.host, self.port = url.conn_info
        self.options = options
        self.peer_address = ""
        self.clean()

    def clean(self):
        for pattern in self._blocked_hosts:
            if pattern.match(self.host):
                raise ValueError(
                    "This host has kindly requested that their content "
                    "not be accessed via web proxy."
                )
        if self.port not in ALLOWED_PORTS:
            raise ValueError(f"Proxied content is disabled over port {self.port}.")

    async def get_response(self):
        _logger.info(f"{self.__class__.__name__}: Making request to {self.url}")
        try:
            response = await self.fetch()
        except socket.gaierror:
            raise ProxyError(f'Unable to establish connection with host "{self.host}"')
        except OSError as e:
            raise ProxyError(f"Connection error: {e}")

        _logger.info(f"{self.__class__.__name__}: Response received: {response.status}")
        return response

    @staticmethod
    def parse_response_header(raw_header: bytes) -> tuple[str, str]:
        header = raw_header.decode()
        parts = header.strip().split(maxsplit=1)
        if len(parts) == 1:
            status, meta = parts[0], ""
        else:
            status, meta = parts

        return status, meta

    async def open_connection(self, **kwargs) -> tuple[asyncio.StreamReader, asyncio.StreamWriter]:
        future = asyncio.open_connection(self.host, self.port, **kwargs)
        try:
            reader, writer = await asyncio.wait_for(future, timeout=CONNECT_TIMEOUT)
        except asyncio.TimeoutError:
            raise ProxyError("Timeout establishing connection with server")

        peername = writer.get_extra_info("peername")
        if peername:
            self.peer_address = peername[0]

        return reader, writer

    async def fetch(self) -> BaseResponse:
        raise NotImplementedError


class BaseResponse:
    """
    Encapsulates a response from the proxied server.
    """

    STATUS_CODES: dict[str, str] = {}

    request: BaseRequest
    reader: asyncio.StreamReader
    writer: asyncio.StreamWriter
    status: str
    meta: str
    mimetype: str
    charset: str | None
    lang: str | None
    proxy_response_builder: BaseProxyResponseBuilder

    def __str__(self) -> str:
        return f'{self.__class__.__name__} {self.status} "{self.meta}"'

    @property
    def url(self) -> URLReference:
        return self.request.url

    @property
    def options(self) -> ProxyOptions:
        return self.request.options

    @property
    def title_display(self) -> str:
        return self.url.hostname or "<unknown>"

    @property
    def status_display(self) -> str:
        """
        A human-readable status message for the response, if available.
        """
        if self.status in self.STATUS_CODES:
            if self.status:
                return f"{self.status} ({self.STATUS_CODES[self.status].title()})"
            else:
                return f"{self.STATUS_CODES[self.status].title()}"
        else:
            return self.status

    @staticmethod
    def parse_meta(meta: str) -> tuple[str, dict[str, str]]:
        """
        Parse & normalize extra params from the MIME string.

        Used for gemini/spartan style responses.
        """
        parts = meta.split(";", maxsplit=1)
        if len(parts) == 2:
            mimetype, extra = parts
        else:
            mimetype, extra = parts[0], ""
        mimetype = mimetype.strip()

        params = {}
        for param in extra.split(";"):
            parts = param.strip().split("=", maxsplit=1)
            if len(parts) == 2:
                params[parts[0].lower()] = parts[1]

        return mimetype, params

    def close(self) -> None:
        """
        Close the socket connection.
        """
        _logger.info("Closing socket")
        try:
            self.writer.close()
        except Exception as e:
            # This will fail if the remote server has already closed the
            # socket via SSL close_notify, but there is no way to know
            # that ahead of time.
            _logger.warning(f"Error closing socket: {e}")

    async def get_body(self) -> bytes:
        """
        Return the entire response body as bytes, up to the max body size.
        """
        try:
            data = await self.reader.readexactly(MAX_BODY_SIZE)
        except IncompleteReadError as e:
            # If EOF was received before the MAX_BODY_SIZE, success!
            # Even though this says "partial", it's the entire body.
            self.close()
            return e.partial
        except Exception:
            self.close()
            raise
        else:
            # We have reached the MAX_BODY_SIZE before the EOF was
            # received. Don't close the connection just yet, because
            # we may want to continue streaming the connection.
            raise ProxyResponseSizeError(data)

    async def stream_body(self) -> AsyncIterator[bytes]:
        """
        Return a streaming iterator for the response bytes.
        """
        try:
            while chunk := await self.reader.read(CHUNK_SIZE):
                yield chunk
        finally:
            self.close()

    async def build_proxy_response(self) -> QuartResponse | WerkzeugResponse:
        """
        Render the native response from the remote server as an HTTP response.
        """
        return await self.proxy_response_builder.build_proxy_response()


class BaseProxyResponseBuilder:
    """
    Convert a response from the proxy server into an HTTP response object.
    """

    def __init__(self, response: BaseResponse):
        self.response = response

    async def render_from_handler(self) -> QuartResponse:
        handler_class: type[BaseHandler]

        if self.response.options.raw:
            handler_class = StreamHandler
        else:
            handler_class = get_handler_class(self.response)

        try:
            handler = await handler_class.from_response(self.response)
            response = await handler.render()
        except ProxyResponseSizeError as e:
            # The file is too large to render in an HTML template, add the
            # data back into the read buffer and re-render as a data stream.
            handler = await StreamHandler.from_partial_response(self.response, e.partial)
            response = await handler.render()

        return response

    async def build_proxy_response(self) -> QuartResponse | WerkzeugResponse:
        raise NotImplementedError


class CloseNotifyState:
    """
    Inject into the SSL context to register if the TLS close_notify signal
    was received at the end of the connection.
    """

    def __init__(self, context: ssl.SSLContext):
        self.received: bool = False

        def msg_callback(connection, direction, v, c, m, data):
            if m == ssl._TLSAlertType.CLOSE_NOTIFY:  # type: ignore  # noqa
                if direction == "read":
                    _logger.info("CLOSE_NOTIFY received")
                    self.received = True

        # This is a private debugging hook provided by the SSL library
        context._msg_callback = msg_callback  # type: ignore

    def __bool__(self) -> bool:
        return self.received
