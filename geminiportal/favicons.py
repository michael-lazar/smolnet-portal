import asyncio
import logging
import os
import shelve
import tempfile
import time
from typing import cast

from geminiportal.errors import BaseProxyError
from geminiportal.protocols import build_proxy_request
from geminiportal.urls import URLReference
from geminiportal.utils import smart_decode

_logger = logging.getLogger(__name__)


DB_NAME = os.path.join(tempfile.gettempdir(), "gemini-portal-favicon-db")


class FaviconCache:
    """
    Download favicon.txt files from sites in the background, and
    stash the results in a temporary directory on the filesystem
    using the shelve module.
    """

    FAVICON_PATH = "/favicon.txt"
    EXPIRATION = 60 * 60 * 4

    def __init__(self, db_name: str):
        self.db_name = db_name

        # References to coroutines that are currently fetching favicons
        self.tasks: dict[str, asyncio.Task] = {}

    def check(self, url: URLReference) -> str | None:
        if url.scheme not in ("gemini", "spartan"):
            return None

        favicon_url = url.join(self.FAVICON_PATH)
        key = favicon_url.get_url()
        with shelve.open(self.db_name) as db:
            if key in db:
                ttl, value = cast(tuple[float, str], db[key])
                if time.time() < ttl:
                    return value

        # Schedule a background task to download and save the favicon
        # Only make one request per-domain at a time to avoid spamming
        if key not in self.tasks:
            self.tasks[key] = asyncio.create_task(self._update(favicon_url))
            self.tasks[key].add_done_callback(lambda *_: self.tasks.pop(key))

        return None

    def shutdown(self) -> None:
        for _, task in self.tasks.items():
            task.cancel()

    async def _update(self, favicon_url: URLReference) -> None:
        favicon = None
        try:
            favicon = await self._fetch_favicon(favicon_url)
        except BaseProxyError:
            _logger.warning("Error fetching favicon")

        _logger.info(f"Favicon for {favicon_url}: {favicon}")
        with shelve.open(self.db_name) as db:
            key = favicon_url.get_url()
            ttl = time.time() + self.EXPIRATION
            db[key] = ttl, favicon

    async def _fetch_favicon(self, favicon_url: URLReference) -> str | None:
        request = build_proxy_request(favicon_url)
        response = await request.get_response()
        if response.status.startswith("2") and response.meta.startswith("text/plain"):
            body = await response.get_body(truncate=True)
            favicon, _ = smart_decode(body, response.charset)
            favicon = favicon.strip()
            if len(favicon) <= 8:  # Emojis can contain up to 8 code points
                return favicon

        return None


favicon_cache = FaviconCache(DB_NAME)
