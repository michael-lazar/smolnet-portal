from __future__ import annotations

import re
from collections.abc import AsyncIterator
from typing import TYPE_CHECKING, ClassVar

from quart import Response, render_template

from geminiportal.urls import URLReference
from geminiportal.utils import prepend_bytes_to_iterator, smart_decode

if TYPE_CHECKING:
    from geminiportal.protocols.base import BaseResponse

# Strip ANSI color characters from text responses
ANSI_ESCAPE = re.compile(
    r"""
    \x1B    # ESC
    [@-_]   # 7-bit C1 Fe
    [0-?]*  # Parameter bytes
    [ -/]*  # Intermediate bytes
    [@-~]   # Final byte
""",
    re.VERBOSE,
)


class BaseHandler:
    """
    File handler for a mimetype or set of mimetypes.
    """

    async def render(self) -> Response:
        raise NotImplementedError

    @classmethod
    async def from_response(cls, response: BaseResponse):
        raise NotImplementedError


class StreamHandler(BaseHandler):
    """
    Send the proxied response stream straight through the HTTP connection.
    """

    def __init__(
        self,
        url: URLReference,
        content_iter: AsyncIterator[bytes],
        mimetype: str,
        charset: str | None = None,
    ):
        self.url = url
        self.content_iter = content_iter
        self.mimetype = mimetype
        self.charset = charset

    async def render(self) -> Response:
        content_type = self.get_content_type()
        return Response(self.content_iter, content_type=content_type)  # type: ignore

    def get_content_type(self) -> str:
        """
        Adjust the content type for text/gemini responses to allow streaming in
        the browser.
        """
        if self.mimetype in (
            "text/gemini",
            "application/gopher-menu",
            "application/gopher+-menu",
            "application/gopher+-attributes",
            "application/nex",
        ):
            mimetype = "text/plain"
        else:
            mimetype = self.mimetype

        if mimetype == "text/plain":
            charset = self.charset or "UTF-8"
            return f"{mimetype}; charset={charset}"
        else:
            return mimetype

    @classmethod
    async def from_response(cls, response: BaseResponse) -> StreamHandler:
        return cls(
            response.url,
            response.stream_body(),
            response.mimetype,
            response.charset,
        )

    @classmethod
    async def from_partial_response(
        cls,
        response: BaseResponse,
        partial_data: bytes,
    ) -> StreamHandler:
        return cls(
            response.url,
            prepend_bytes_to_iterator(partial_data, response.stream_body()),
            response.mimetype,
            response.charset,
        )


class TemplateHandler(BaseHandler):
    """
    Render the proxied response as HTML and insert it inside the page.
    """

    template: ClassVar[str]

    def __init__(
        self,
        url: URLReference,
        content: bytes,
        mimetype: str,
        charset: str | None = None,
    ):
        self.url = url
        self.content = content
        self.mimetype = mimetype
        self.charset = charset
        self._text: str | None = None

    @property
    def text(self) -> str:
        """
        Decode the content from bytes to text.
        """
        if self._text is None:
            self._text, self.charset = smart_decode(self.content, self.charset)

            # Strip any ANSI colors or sequences that won't render in the proxy
            self._text = ANSI_ESCAPE.sub("", self._text)

        return self._text

    async def render(self) -> Response:
        context = self.get_context()
        content = await render_template(self.template, **context)
        return Response(content)

    @classmethod
    async def from_response(cls, response: BaseResponse) -> TemplateHandler:
        return cls(
            response.url,
            await response.get_body(),
            response.mimetype,
            response.charset,
        )

    def get_context(self) -> dict:
        return {"handler": self}
