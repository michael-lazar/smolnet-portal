from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import NamedTuple

import chardet
from emoji import is_emoji
from quart import Response
from werkzeug.wrappers.response import Response as WerkzeugResponse

from geminiportal.urls import URLReference

# An HTTP response from either quart or werkzeug (e.g. a redirect)
type HTTPResponse = Response | WerkzeugResponse


class ProxyOptions(NamedTuple):
    charset: str | None = None
    lang: str | None = None
    raw: bool = False
    raw_crt: bool = False
    vr: bool = False
    crt: bool = False
    meta: bool = False
    reader: bool = False
    client_crt: str | None = None


def utcnow() -> datetime:
    """
    The current time as a naive UTC datetime, the convention used for
    all timestamps stored in the database.
    """
    return datetime.now(UTC).replace(tzinfo=None)


async def prepend_bytes_to_iterator(
    partial_bytes: bytes, content_iter: AsyncIterator[bytes]
) -> AsyncIterator[bytes]:

    yield partial_bytes

    async for chunk in content_iter:
        yield chunk


def parse_link_line(line: str, base: URLReference) -> tuple[URLReference, str, str]:
    # Prefix is part of the text at the beginning of the link
    # description that shouldn't be underlined.
    prefix = ""

    parts = line.split(maxsplit=1)
    if len(parts) == 0:
        link, link_text = "", ""
    elif len(parts) == 1:
        link, link_text = parts[0], parts[0]
    else:
        link, link_text = parts
        prefix, link_text = split_emoji(link_text)
        if prefix:
            # Add a space after the emoji, this just makes it easier to insert
            # into a template string without using a conditional statement
            prefix = prefix + " "

    link_text = link_text.strip()
    url = base.join(link)
    return url, link_text, prefix


def split_emoji(line: str) -> tuple[str, str]:
    """
    Strips out a potential emoji at the beginning on a line of text.
    """
    for i in range(4, 0, -1):
        # Start with 4 characters and work backwards to 1 to check for
        # emojis that span multiple code points.
        if is_emoji(line[:i]):
            emoji = line[:i]
            link_text = line[i:].strip()
            return emoji, link_text

    return "", line


def smart_decode(
    data: bytes,
    charset: str | None,
    errors: str = "replace",
    default_charset: str = "UTF-8",
) -> tuple[str, str]:
    """
    Decode text, falling back to heuristics if the charset is not defined.
    """
    if charset:
        text = data.decode(charset, errors=errors)
        return text, charset

    try:
        text = data.decode(default_charset)
    except UnicodeDecodeError:
        autodetect = chardet.detect(data)

        if autodetect["confidence"] > 0.5:
            detected_charset = autodetect["encoding"] or default_charset
        else:
            detected_charset = default_charset
        text = data.decode(detected_charset, errors=errors)
    else:
        detected_charset = default_charset

    return text, detected_charset
