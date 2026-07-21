from __future__ import annotations

import asyncio
import logging
import re
import socket
import ssl
from asyncio.exceptions import IncompleteReadError
from collections.abc import AsyncIterator

from quart import Response as QuartResponse

from geminiportal.errors import (
    InvalidRequestError,
    RequestBlockedError,
    UpstreamConnectionError,
    UpstreamTimeoutError,
)
from geminiportal.handlers import get_handler_class
from geminiportal.handlers.base import BaseHandler, StreamHandler
from geminiportal.tls import get_ssl_context
from geminiportal.urls import URLReference
from geminiportal.utils import HTTPResponse, ProxyOptions

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


def supports_client_cert(scheme: str) -> bool:
    """
    Whether the proxied scheme can authenticate with a TLS client
    certificate.
    """
    return scheme in ("gemini", "gophers", "scroll")


class ResponseSizeExceeded(Exception):
    """
    The response body exceeded the maximum size that can be buffered
    into memory.

    Carries the data read so far, and leaves the connection open so
    that the response can be re-rendered as a raw data stream.
    """

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
                raise RequestBlockedError(
                    f'The host "{self.host}" has kindly requested that their '
                    "content not be accessed via web proxy."
                )
        if self.port not in ALLOWED_PORTS:
            raise RequestBlockedError(f"Proxied content is disabled over port {self.port}.")

    async def get_response(self):
        _logger.info(f"{self.__class__.__name__}: Making request to {self.url}")
        try:
            response = await self.fetch()
        except socket.gaierror:
            raise UpstreamConnectionError(f'The hostname "{self.host}" could not be resolved.')
        except ConnectionRefusedError:
            raise UpstreamConnectionError(
                f'The server at "{self.host}" refused the connection on port {self.port}.'
            )
        except ssl.SSLError as e:
            raise UpstreamConnectionError(
                f'A secure TLS connection could not be established with "{self.host}".'
            ) from e
        except OSError as e:
            raise UpstreamConnectionError(f'The connection to "{self.host}" failed.') from e

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
        except TimeoutError:
            raise UpstreamTimeoutError(
                f'The server at "{self.host}" did not accept the connection '
                f"after {CONNECT_TIMEOUT} seconds."
            )

        peername = writer.get_extra_info("peername")
        if peername:
            self.peer_address = peername[0]

        return reader, writer

    def create_ssl_context(self) -> ssl.SSLContext:
        """
        Build the SSL context for the request, attaching the user's TLS
        client certificate when one has been activated for the host.
        """
        try:
            return get_ssl_context(self.options.client_crt)
        except ssl.SSLError as e:
            raise InvalidRequestError(
                "The TLS context for the request could not be created. "
                "If you have activated a client certificate for this host, "
                "try logging out and logging back in."
            ) from e

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

    async def get_body(self, truncate: bool = False) -> bytes:
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
            # We have reached the MAX_BODY_SIZE before the EOF was received.
            if truncate:
                self.close()
                return data
            # Don't close the connection just yet, because we may want
            # to continue streaming the connection.
            raise ResponseSizeExceeded(data)

    async def stream_body(self) -> AsyncIterator[bytes]:
        """
        Return a streaming iterator for the response bytes.
        """
        try:
            while chunk := await self.reader.read(CHUNK_SIZE):
                yield chunk
        finally:
            self.close()

    async def build_proxy_response(self) -> HTTPResponse:
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
        except ResponseSizeExceeded as e:
            # The file is too large to render in an HTML template, add the
            # data back into the read buffer and re-render as a data stream.
            handler = await StreamHandler.from_partial_response(self.response, e.partial)
            response = await handler.render()

        return response

    async def build_proxy_response(self) -> HTTPResponse:
        raise NotImplementedError
