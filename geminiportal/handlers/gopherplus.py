from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from geminiportal.handlers.base import TemplateHandler
from geminiportal.handlers.gopher import GopherItem
from geminiportal.urls import quote_gopher

type GopherPlusAttributeData = dict[str, Any]
type GopherPlusAttributeMap = dict[str, GopherPlusAttributeData]


class GopherPlusHandler(TemplateHandler):
    """
    Handles the structured response that's returned from a gopher+
    server when information attributes are requested.
    """

    template = "proxy/handlers/gopherplus.html"

    attribute_map: GopherPlusAttributeMap
    active_attribute: str | None
    active_attribute_data: GopherPlusAttributeData
    line_buffer: list[str]

    def get_context(self) -> dict[str, Any]:
        context = super().get_context()
        # Note: We need to evaluate the iterator in order to invoke `self.text`
        # and determine what the response charset is before rendering the page.
        context["content"] = list(self.iter_content())
        return context

    def iter_content(self) -> Iterable[GopherPlusAttributeMap]:
        self.attribute_map = {}
        self.active_attribute = None
        self.active_attribute_data = {}
        self.line_buffer = []

        for line in self.text.splitlines():
            if line.startswith("+"):
                parts = line[1:].split(":", maxsplit=1)
                attribute = parts[0]
                if len(parts) == 1:
                    attribute_data = {}
                else:
                    item_description = parts[1]
                    if item_description.startswith(" "):
                        # Strip out the space after the colon, "+INFO: <item-description>".
                        item_description = item_description[1:]

                    item = GopherItem.from_item_description(item_description, self.url)
                    attribute_data = {"item": item}

                yield from self.flush(attribute, attribute_data)
            else:
                self.line_buffer.append(line[1:])

        yield from self.flush()

    def flush(
        self,
        attribute: str | None = None,
        attribute_data: dict | None = None,
    ) -> Iterable[GopherPlusAttributeMap]:
        # Flush the previous attribute
        if self.active_attribute:
            self.active_attribute_data["content"] = "\n".join(self.line_buffer)
            # Custom handling for some of the standard views
            if self.active_attribute == "VIEWS":
                self.parse_views_block()
            elif self.active_attribute == "ADMIN":
                self.parse_admin_block()
            # TODO: Need to render ASK blocks
            self.attribute_map[self.active_attribute] = self.active_attribute_data

        # If we're starting a new info block, yield any existing attributes
        if attribute in ("INFO", None):
            if self.attribute_map:
                yield self.attribute_map
                self.attribute_map = {}  # noqa

        self.active_attribute = attribute
        self.active_attribute_data = attribute_data or {}
        self.line_buffer = []

    def parse_views_block(self) -> None:
        # The +VIEWS content-types are relative the the gopher selector
        # in the +ITEM block. The +ITEM block should always be included
        # in the response before the +VIEWS block, unless the server is
        # out-of-spec.
        item = self.attribute_map.get("INFO", {}).get("item")
        item_url = item.url if item else None

        lines = []
        for line in self.line_buffer:
            line = line.strip()
            if item_url:
                content_type = line.split(":", maxsplit=1)[0]
                url = item_url.copy()
                url.gopher_plus_string = f"+{quote_gopher(content_type)}"
            else:
                url = None

            lines.append({"text": line, "url": url})

        self.active_attribute_data["lines"] = lines

    def parse_admin_block(self) -> None:
        lines = []
        for line in self.line_buffer:
            line = line.strip()

            parts = line.split(":", maxsplit=1)
            if len(parts) == 1:
                name, val = parts[0], ""
            else:
                name, val = parts

            comments, meta_tag = self.split_attribute_meta_tag(val.strip())
            line_data = {"comments": comments, "meta_tag": meta_tag, "name": name}

            if meta_tag and "@" in meta_tag:
                line_data["url"] = f"mailto:{meta_tag}"

            lines.append(line_data)

        self.active_attribute_data["lines"] = lines

    def split_attribute_meta_tag(self, text: str) -> tuple[str, str | None]:
        """
        Split the <...> data off of an attribute description.

        E.g.
            Mod-Date: Sat Nov 26 15:56:40 2022 <20221126155640>
        """
        parts = text.rsplit("<", maxsplit=1)
        if len(parts) == 1:
            return text, None

        if parts[1][-1] != ">":
            return text, None

        return parts[0].rstrip(), parts[1][:-1]
