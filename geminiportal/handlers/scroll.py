import re
from collections.abc import Iterable
from enum import Enum
from typing import Any

from markupsafe import Markup, escape

from geminiportal.handlers.base import TemplateHandler
from geminiportal.utils import parse_link_line, split_emoji


class AnchorLevel(Enum):
    H2 = 2
    H3 = 3
    H4 = 4


class ScrollHandler(TemplateHandler):
    """
    Like gemini but with more stuff in it.
    """

    template = "proxy/handlers/scroll.html"

    line_buffer: list[str]
    active_type: str | None
    anchor_counters: dict[AnchorLevel, int]

    def bump_h2_anchor(self):
        self.anchor_counters[AnchorLevel.H2] += 1
        self.anchor_counters[AnchorLevel.H3] = 0
        self.anchor_counters[AnchorLevel.H4] = 0

    def bump_h3_anchor(self):
        if self.anchor_counters[AnchorLevel.H2] == 0:
            self.bump_h2_anchor()

        self.anchor_counters[AnchorLevel.H3] += 1
        self.anchor_counters[AnchorLevel.H4] = 0

    def bump_h4_anchor(self):
        if self.anchor_counters[AnchorLevel.H3] == 0:
            self.bump_h3_anchor()

        self.anchor_counters[AnchorLevel.H4] += 1

    def get_anchor(self, level: AnchorLevel) -> str:
        """
        Add link anchors to scrolltext header lines.
        """
        match level:
            case AnchorLevel.H2:
                self.bump_h2_anchor()
                return str(self.anchor_counters[AnchorLevel.H2])
            case AnchorLevel.H3:
                self.bump_h3_anchor()
                return ".".join(
                    (
                        str(self.anchor_counters[AnchorLevel.H2]),
                        str(self.anchor_counters[AnchorLevel.H3]),
                    )
                )
            case AnchorLevel.H4:
                self.bump_h4_anchor()
                return ".".join(
                    (
                        str(self.anchor_counters[AnchorLevel.H2]),
                        str(self.anchor_counters[AnchorLevel.H3]),
                        str(self.anchor_counters[AnchorLevel.H4]),
                    )
                )
            case _:
                raise ValueError()

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
        self.anchor_counters = {
            AnchorLevel.H2: 0,
            AnchorLevel.H3: 0,
            AnchorLevel.H4: 0,
        }

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
                # TODO: add citation for quote
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
                anchor = self.get_anchor(AnchorLevel.H4)
                yield {"item_type": "h4", "text": text, "anchor": anchor}

            elif line.startswith("###"):
                yield from self.flush()
                text = line[3:].lstrip()
                anchor = self.get_anchor(AnchorLevel.H3)
                yield {"item_type": "h3", "text": text, "anchor": anchor}

            elif line.startswith("##"):
                yield from self.flush()
                text = line[2:].lstrip()
                anchor = self.get_anchor(AnchorLevel.H2)
                yield {"item_type": "h2", "text": text, "anchor": anchor}

            elif line.startswith("#"):
                yield from self.flush()
                text = line[1:].lstrip()
                yield {"item_type": "h1", "text": text}

            elif line.startswith("* "):
                # Note: The spec allows nested lists, currently unsupported.
                #
                # * Unordered list item 1
                # ** 1. Ordered sub-list item 1
                # ** 2. Ordered sub-list item 2
                # * Unordered list item 2
                # ...

                yield from self.flush("ul")
                self.line_buffer.append(line[1:].lstrip())

            elif line.startswith("> ") or line == ">":
                # Note: The spec allows nested quotes, currently unsupported.
                #
                # > Quote level 1
                # >> Quote level 2
                # ...

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
        # TODO: it's kinda broken, see test file
        text = str(escape(text))
        text = re.sub(r"`([^`]+)`", r"<code>\1</code>", text)
        text = re.sub(r"\*([^*]+)\*", r"<b>\1</b>", text)
        text = re.sub(r"_([^_]+)_", r"<i>\1</i>", text)
        return Markup(text)
