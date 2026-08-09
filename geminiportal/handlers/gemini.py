import re
from collections import Counter
from collections.abc import Iterable
from typing import Any

from geminiportal.handlers.base import TemplateHandler
from geminiportal.utils import parse_link_line, split_emoji

RABBIT_INLINE = ":rаbbiΤ:"
RABBIT_STANDALONE = ";rаbbiΤ;"
RABBIT_ART = r"""
          /|
    /\   //
   |/\'-'/ .::.
     /^Y^\::''.
     \_ /=| `'
    /`_)=( \
    \ /=/'-/
   {/ |/  \
  __\  _  /__
 '----' '----'
"""


class GeminiHandler(TemplateHandler):
    """
    The full-featured gemtext -> html converter.
    """

    _rabbit_re = re.compile(RABBIT_INLINE)

    template = "proxy/handlers/gemini.html"

    line_buffer: list[str]
    active_type: str | None
    anchor_counter: Counter[str]

    def get_anchor(self, text: str) -> str:
        """
        Add link anchors to gemtext header lines.
        """
        text = text.strip()
        text = text.lower()
        text = text.replace(" ", "-")
        text = re.sub(r"[^\w-]", "", text)
        self.anchor_counter[text] += 1
        if self.anchor_counter[text] > 1:
            text += f"-{self.anchor_counter[text] - 1}"
        return text

    def get_context(self) -> dict[str, Any]:
        context = super().get_context()

        content = list(self.iter_content())
        if content and content[0]["item_type"] in ("h1", "h2", "h3"):
            # Set a custom page title based on the first header in the
            # document. This idea was copied from Lagrange.
            favicon, title = split_emoji(content[0]["text"])
            if favicon:
                context["favicon"] = favicon
            context["title"] = f"{title} — {self.url.hostname}"

        context["content"] = content
        return context

    def iter_content(self) -> Iterable[dict]:
        self.line_buffer = []
        self.active_type = None
        self.anchor_counter = Counter()

        for line in self.text.splitlines():
            line = line.rstrip()
            line = self._rabbit_re.sub("🐇", line)
            if line.startswith("```"):
                if self.active_type == "pre":
                    yield from self.flush()
                else:
                    yield from self.flush("pre")

            elif self.active_type == "pre":
                if line == RABBIT_STANDALONE:
                    line = RABBIT_ART
                self.line_buffer.append(line)

            elif line == RABBIT_STANDALONE:
                yield from self.flush()
                yield {
                    "item_type": "pre",
                    "lines": RABBIT_ART.splitlines(keepends=False),
                }

            elif line.startswith("=>"):
                yield from self.flush()
                url, link_text, prefix = parse_link_line(line[2:], self.url)
                media_type, media_url = url.get_inline_media()
                yield {
                    "item_type": "link",
                    "url": url.get_proxy_url(),
                    "text": link_text,
                    "prefix": prefix,
                    "external_indicator": url.get_external_indicator(),
                    "media_type": media_type,
                    "media_url": media_url,
                }

            elif line.startswith("=:"):
                yield from self.flush()
                url, link_text, prefix = parse_link_line(line[2:], self.url)
                yield {
                    "item_type": "prompt",
                    "url": url.get_proxy_url(),
                    "text": link_text,
                    "prefix": prefix,
                    "external_indicator": url.get_external_indicator(),
                }

            elif line.startswith("###"):
                yield from self.flush()
                text = line[3:].lstrip()
                anchor = self.get_anchor(text)
                yield {"item_type": "h3", "text": text, "anchor": anchor}

            elif line.startswith("##"):
                yield from self.flush()
                text = line[2:].lstrip()
                anchor = self.get_anchor(text)
                yield {"item_type": "h2", "text": text, "anchor": anchor}

            elif line.startswith("#"):
                yield from self.flush()
                text = line[1:].lstrip()
                anchor = self.get_anchor(text)
                yield {"item_type": "h1", "text": text, "anchor": anchor}

            elif line.startswith("* "):
                yield from self.flush("ul")
                self.line_buffer.append(line[1:].lstrip())

            elif line.startswith("> ") or line == ">":
                yield from self.flush("blockquote")
                self.line_buffer.append(line[2:])

            elif line == "---":
                yield from self.flush()
                yield {"item_type": "hr"}

            else:
                yield from self.flush("p")
                self.line_buffer.append(line)

        yield from self.flush()

    def flush(self, new_type: str | None = None) -> Iterable[dict]:
        if self.active_type != new_type:
            if self.line_buffer and self.active_type:
                yield {
                    "item_type": self.active_type,
                    "lines": self.line_buffer,
                }

            self.line_buffer = []
            self.active_type = new_type
