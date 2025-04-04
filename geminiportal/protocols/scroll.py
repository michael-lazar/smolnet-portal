from __future__ import annotations

import logging
import ssl
from dataclasses import dataclass
from datetime import datetime, timezone

from quart import Response as QuartResponse
from quart import render_template
from werkzeug.utils import redirect

from geminiportal.protocols.base import (
    BaseProxyResponseBuilder,
    BaseRequest,
    BaseResponse,
    CloseNotifyState,
)
from geminiportal.utils import describe_tls_cert

_logger = logging.getLogger(__name__)


@dataclass
class DocumentMetadata:
    author: str | None
    publish_date: datetime | None
    modification_date: datetime | None


class ScrollRequest(BaseRequest):
    """
    Encapsulates a scroll:// request.
    """

    def create_ssl_context(self) -> ssl.SSLContext:
        context = ssl.create_default_context()
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE
        return context

    def parse_date(self, line: bytes) -> datetime | None:
        if date_str := line.decode("UTF-8").rstrip():
            try:
                return datetime.fromisoformat(date_str)
            except ValueError:
                # This is fixed in python 3.11
                # https://github.com/python/cpython/issues/80010
                if date_str.endswith("Z"):
                    date_str = date_str[:-1]
                    return datetime.fromisoformat(date_str).replace(tzinfo=timezone.utc)

        return None

    def parse_author(self, line: bytes) -> str | None:
        if author := line.decode("UTF-8").rstrip():
            return author

        return None

    async def fetch(self) -> ScrollResponse:
        context = self.create_ssl_context()
        tls_close_notify = CloseNotifyState(context)

        reader, writer = await self.open_connection(ssl=context)
        ssock = writer.get_extra_info("ssl_object")

        tls_cert = ssock.getpeercert(True)
        tls_version = ssock.version()
        tls_cipher, _, _ = ssock.cipher()

        language_list = ["en"]
        if self.options.lang and self.options.lang != "en":
            language_list.insert(0, self.options.lang)

        data = self.url.get_scroll_request(self.options.meta, language_list)
        writer.write(data)
        await writer.drain()

        raw_header = await reader.readline()
        status, meta = self.parse_response_header(raw_header)

        if status.startswith("2"):
            document_meta = DocumentMetadata(
                author=self.parse_author(await reader.readline()),
                publish_date=self.parse_date(await reader.readline()),
                modification_date=self.parse_date(await reader.readline()),
            )

        else:
            document_meta = None

        return ScrollResponse(
            request=self,
            reader=reader,
            writer=writer,
            status=status,
            meta=meta,
            document_meta=document_meta,
            tls_cert=tls_cert,
            tls_version=tls_version,
            tls_cipher=tls_cipher,
            tls_close_notify=tls_close_notify,
        )


class ScrollResponse(BaseResponse):
    STATUS_CODES = {
        "10": "INPUT",
        "11": "SENSITIVE INPUT",
        "20": "General Science, Knowledge, Documentation, News",
        "21": "Philosophy, Psychology",
        "22": "Religion, Theology, Scripture",
        "23": "Social Sciences, Military",
        "24": "Default, Unclassified",
        "25": "Mathmatics, Natural Science",
        "26": "Applied Science, Medicine, General Technology, Engineering",
        "27": "Arts, Entertainment, Sport, Fitness",
        "28": "Linguistics, Literature, Personal Blogs, Reviews",
        "29": "Geography, History, Biography",
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

    document_meta: DocumentMetadata

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
        document_meta,
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

        self.document_meta = document_meta

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

        self.proxy_response_builder = ScrollProxyResponseBuilder(self)

    @property
    def tls_close_notify_received(self):
        return bool(self.tls_close_notify)


class ScrollProxyResponseBuilder(BaseProxyResponseBuilder):
    response: ScrollResponse

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
            await self.response.get_body()

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
                "proxy/proxy-error.html",
                error=self.response.status_display,
                message=self.response.meta,
            )
            return QuartResponse(content)

        elif self.response.status.startswith("6"):
            content = await render_template("proxy/gemini-cert-required.html")
            return QuartResponse(content)

        else:
            content = await render_template(
                "proxy/gateway-error.html",
                error="The response from the proxied server is unrecognized or invalid.",
            )
            return QuartResponse(content)
