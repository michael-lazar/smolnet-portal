import re
from collections import Counter
from collections.abc import Iterable
from typing import Any

from markupsafe import Markup, escape

from geminiportal.handlers.base import TemplateHandler
from geminiportal.utils import parse_link_line, split_emoji


class ScrollHandler(TemplateHandler):
    """
    Like gemini but with more stuff in it.
    """

    template = "proxy/handlers/scroll.html"

    line_buffer: list[str]
    active_type: str | None
    anchor_counter: Counter[str]

    def get_anchor(self, text: str) -> str:
        """
        Add link anchors to scrolltext header lines.
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
            if line.startswith("```"):
                if self.active_type == "pre":
                    yield from self.flush()
                else:
                    yield from self.flush("pre")

            elif self.active_type == "pre":
                self.line_buffer.append(line)

            elif line.startswith("=>"):
                yield from self.flush()
                url, link_text, prefix = parse_link_line(line[2:], self.url)
                yield {
                    "item_type": "link",
                    "url": url.get_proxy_url(),
                    "text": link_text,
                    "prefix": prefix,
                    "external_indicator": url.get_external_indicator(),
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

            elif line.startswith("#####"):
                yield from self.flush()
                text = line[5:].lstrip()
                yield {"item_type": "h5", "text": text}

            elif line.startswith("####"):
                yield from self.flush()
                text = line[4:].lstrip()
                anchor = self.get_anchor(text)
                yield {"item_type": "h4", "text": text, "anchor": anchor}

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
                if self.active_type in ("p", "ul", "blockquote"):
                    lines = [self.parse_inline_markup(line) for line in self.line_buffer]
                else:
                    lines = self.line_buffer

                yield {
                    "item_type": self.active_type,
                    "lines": lines,
                }

            self.line_buffer = []
            self.active_type = new_type

    def parse_inline_markup(self, text: str) -> str:
        """
        Simple parser that converts inline markup into sanitized HTML tags.
        """
        text = str(escape(text))
        text = re.sub(r"`([^`]+)`", r"<code>\1</code>", text)
        text = re.sub(r"\*([^*]+)\*", r"<b>\1</b>", text)
        text = re.sub(r"_([^_]+)_", r"<i>\1</i>", text)
        return Markup(text)
