from __future__ import annotations

import logging

from quart import Response as QuartResponse
from quart import render_template
from werkzeug.utils import redirect

from geminiportal.errors import UpstreamResponseError
from geminiportal.protocols.base import (
    BaseProxyResponseBuilder,
    BaseRequest,
    BaseResponse,
)
from geminiportal.tls import CloseNotifyState, describe_tls_cert

_logger = logging.getLogger(__name__)


class GeminiRequest(BaseRequest):
    """
    Encapsulates a gemini:// request.
    """

    async def fetch(self) -> GeminiResponse:
        context = self.create_ssl_context()
        reader, writer = await self.open_connection(ssl=context)

        ssock = writer.get_extra_info("ssl_object")
        tls_close_notify = CloseNotifyState(ssock)

        tls_cert = ssock.getpeercert(True)
        tls_version = ssock.version()
        tls_cipher, _, _ = ssock.cipher()

        data = self.url.get_gemini_request()
        writer.write(data)
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


class GeminiResponse(BaseResponse):
    STATUS_CODES = {
        "10": "INPUT",
        "11": "SENSITIVE INPUT",
        "20": "SUCCESS",
        "30": "REDIRECT - TEMPORARY",
        "31": "REDIRECT - PERMANENT",
        "40": "TEMPORARY FAILURE",
        "41": "SERVER UNAVAILABLE",
        "42": "CGI ERROR",
        "43": "PROXY ERROR",
        "44": "SLOW DOWN",
        "50": "PERMANENT FAILURE",
        "51": "NOT FOUND",
        "52": "GONE",
        "53": "PROXY REQUEST REFUSED",
        "59": "BAD REQUEST",
        "60": "CLIENT CERTIFICATE REQUIRED",
        "61": "CERTIFICATE NOT AUTHORISED",
        "62": "CERTIFICATE NOT VALID",
    }

    tls_cert: bytes
    tls_version: str
    tls_cipher: str
    tls_close_notify: CloseNotifyState

    def __init__(
        self,
        request,
        reader,
        writer,
        status,
        meta,
        tls_cert,
        tls_version,
        tls_cipher,
        tls_close_notify,
    ):
        self.request = request
        self.reader = reader
        self.writer = writer
        self.status = status
        self.meta = meta

        self.tls_cert = tls_cert
        self.tls_version = tls_version
        self.tls_cipher = tls_cipher
        self.tls_close_notify = tls_close_notify

        if self.status.startswith("2"):
            self.mimetype, params = self.parse_meta(meta)
            self.charset = request.options.charset or params.get("charset", "UTF-8")
            self.lang = params.get("lang", None)
        else:
            self.charset = request.options.charset or "UTF-8"
            self.mimetype = ""
            self.lang = None

        self.proxy_response_builder = GeminiProxyResponseBuilder(self)

    @property
    def tls_close_notify_received(self):
        return bool(self.tls_close_notify)


class GeminiProxyResponseBuilder(BaseProxyResponseBuilder):
    response: GeminiResponse

    async def build_proxy_response(self):
        if self.response.options.raw_crt:
            return QuartResponse(
                self.response.tls_cert,
                content_type="application/x-x509-ca-cert",
                headers={
                    "Content-Disposition": f"attachment; filename={self.response.request.host}.cer",
                },
            )

        elif self.response.options.crt:
            # Consume the request, so we can check for the close_notify signal
            await self.response.get_body(truncate=True)

            cert_description = await describe_tls_cert(self.response.tls_cert)
            content = await render_template(
                "proxy/tls-context.html",
                cert_description=cert_description,
                response=self.response,
            )
            return QuartResponse(content)

        elif self.response.status.startswith("1"):
            content = await render_template(
                "proxy/gemini-query.html",
                secret=self.response.status == "11",
                prompt=self.response.meta,
            )
            return QuartResponse(content)

        elif self.response.status.startswith("2"):
            return await self.render_from_handler()

        elif self.response.status.startswith("3"):
            location = self.response.url.join(self.response.meta).get_proxy_url()
            return redirect(location, 307)

        elif self.response.status.startswith(("4", "5")):
            content = await render_template(
                "proxy/error-response.html",
                error=self.response.status_display,
                message=self.response.meta,
            )
            return QuartResponse(content)

        elif self.response.status.startswith("6"):
            content = await render_template(
                "proxy/gemini-cert-required.html",
                error=self.response.status_display,
                message=self.response.meta,
            )
            return QuartResponse(content)

        else:
            raise UpstreamResponseError(
                f'The server returned an unrecognized status code "{self.response.status}".'
            )
