from __future__ import annotations

import copy
import mimetypes
import os
import os.path
import urllib.parse
from urllib.parse import quote, unquote_to_bytes, urljoin, urlparse, urlunparse

from quart import url_for

# Add custom mimetypes for extensions not defined by the filesystem
mimetypes.add_type("text/gemini", ".gmi")
mimetypes.add_type("text/gemini", ".gemini")
mimetypes.add_type("text/x-rst", ".rst")
mimetypes.add_type("application/gopher-menu", ".goph")
mimetypes.add_type("text/scroll", ".scroll")

PROXY_SCHEMES = [
    "gemini",
    "spartan",
    "text",
    "finger",
    "nex",
    "gopher",
    "gophers",
    "scroll",
]


# Patch hardcoded URL schemes to support our niche protocols
def _extend(container: list, schemes: list):
    for scheme in schemes:
        if scheme not in container:
            container.append(scheme)


_extend(urllib.parse.uses_relative, PROXY_SCHEMES)
_extend(urllib.parse.uses_netloc, PROXY_SCHEMES)


class URLReference:
    """
    Central class for all URL handling and manipulation.

    Contains extra support for schemes like gopher:// and finger:// that
    aren't well-structured according to rfc4266, and schemes like mailto:
    that don't have a netloc.

    This was copied from another project that I'm working on, which is why
    it handles gopher & other URL patterns that the proxy does not support
    (yet).
    """

    DEFAULT_PORTS: dict[str, int] = {
        "http": 80,
        "https": 443,
        "gopher": 70,
        "gophers": 70,
        "spartan": 300,
        "gemini": 1965,
        "text": 1961,
        "finger": 79,
        "nex": 1900,
        "scroll": 5699,
    }

    def __init__(self, url: str, base: str | None = None):
        """
        Deconstruct the URL, so we can inspect and transform it.

        Args:
            url: The target URL, may be either absolute or relative.
            base: The document that the URL was retrieved from,
                this is used to resolve relative URLs.
        """
        self.original = url
        self.base = base
        if base:
            url = urljoin(base, url)

        url_parts = urlparse(url)

        self.scheme = url_parts.scheme
        self.port = url_parts.port or self.DEFAULT_PORTS.get(self.scheme, None)
        self.hostname = url_parts.hostname
        self.username = url_parts.username
        self.password = url_parts.password

        # HTTP/Gemini/Spartan URL components (RFC 3986)
        self.path = url_parts.path
        self.params = url_parts.params
        self.query = url_parts.query
        self.fragment = url_parts.fragment

        # Remove the optional trailing slash
        if self.path == "/":
            self.path = ""

        sections = url.split("/", maxsplit=3)

        # https://datatracker.ietf.org/doc/html/draft-ietf-uri-url-finger
        # Finger URLs parse differently after the authority component
        self.finger_request = ""
        if self.scheme == "finger" and len(sections) == 4:
            self.finger_request = sections[3]

        # https://datatracker.ietf.org/doc/html/rfc4266
        # Gopher URLs parse differently after the authority component
        self.gopher_item_type = ""
        self.gopher_selector = ""
        self.gopher_search = ""
        self.gopher_plus_string = ""
        if self.scheme in ("gopher", "gophers"):
            if len(sections) < 4 or sections[3] == "":
                self.gopher_item_type = "1"
                self.gopher_selector = ""
            else:
                self.gopher_item_type = sections[3][0]
                self.gopher_selector = sections[3][1:]

        # Strip the search string & gopher+ data out of the selector and path
        if "%09" in self.gopher_selector:
            self.gopher_selector, self.gopher_search = self.gopher_selector.split("%09", maxsplit=1)
            self.path = self.gopher_selector

        if "%09" in self.gopher_search:
            self.gopher_search, self.gopher_plus_string = self.gopher_search.split(
                "%09", maxsplit=1
            )

        # TODO: Validate gopher+ string here, if not startswith +, !, $, ?, ...

    def __str__(self):
        return self.get_url()

    def __repr__(self):
        return f"URLReference: {self.get_url()}"

    def __eq__(self, other) -> bool:
        if isinstance(other, URLReference):
            return self.get_url() == other.get_url()
        else:
            return False

    def guess_mimetype(self) -> str | None:
        """
        Guess the mimetype of the file/document that the URL is pointed to.
        """
        if self.scheme in ("gopher", "gophers"):
            # Using the path component instead of the selector is a heuristic
            # here, because even though the path has no meaning in gopher, I'm
            # assuming most modern gopher servers are going to use HTTP-style
            # paths for file names.
            return self.guess_gopher_mimetype()

        return mimetypes.guess_type(self.path, strict=False)[0]

    def get_external_indicator(self) -> str | None:
        """
        Return a string that can be displayed next to external links to
        indicate that they will navigate away from the current host.
        """
        if self.base is None:
            return None

        base_parts = urlparse(self.base)
        base_scheme = base_parts.scheme
        base_hostname = base_parts.hostname

        if self.scheme and self.scheme != base_scheme:
            if self.hostname:
                return f"{self.scheme}://{self.hostname}"
            else:
                return f"{self.scheme}://"

        if self.hostname and self.hostname != base_hostname:
            return self.hostname

        return None

    @property
    def netloc(self) -> str:
        """
        Return the normalized netloc value for constructing URLs.
        """
        if not self.hostname:
            return ""

        netloc = self.hostname

        if self.username:
            if self.password:
                netloc = f"{self.username}:{self.password}@{netloc}"
            else:
                netloc = f"{self.username}@{netloc}"

        if self.port and self.port != self.DEFAULT_PORTS.get(self.scheme):
            netloc = f"{netloc}:{self.port}"

        return netloc

    @property
    def conn_info(self) -> tuple[str, int]:
        """
        Return the IP connection info if available.
        """
        if not self.port:
            raise ValueError(f"Unable to build connection info, missing port: {self.get_url()}")
        elif not self.hostname:
            raise ValueError(f"Unable to build connection info, missing hostname: {self.get_url()}")
        else:
            return self.hostname, self.port

    def get_finger_path(self) -> str:
        if self.finger_request:
            return f"/{self.finger_request}"
        else:
            return ""

    def get_finger_url(self) -> str:
        path = self.get_finger_path()
        return f"{self.scheme}://{self.netloc}{path}"

    def get_gopher_path(self) -> str:
        selector = self.gopher_selector
        if self.gopher_plus_string:
            selector = f"{selector}%09{self.gopher_search}%09{self.gopher_plus_string}"
        elif self.gopher_search:
            selector = f"{selector}%09{self.gopher_search}"

        if selector and selector != "/":
            return f"/{self.gopher_item_type}{selector}"
        elif self.gopher_item_type != "1":
            return f"/{self.gopher_item_type}"
        else:
            return ""

    def get_gopher_url(self) -> str:
        if self.scheme not in ("gopher", "gophers"):
            raise ValueError(f"Invalid scheme for gopher URL: {self.scheme}")

        path = self.get_gopher_path()
        return f"{self.scheme}://{self.netloc}{path}"

    def get_url(self, include_query: bool = True, include_fragment: bool = True) -> str:
        """
        Construct a normalized URL string.
        """
        if self.scheme == "finger":
            return self.get_finger_url()
        elif self.scheme in ("gopher", "gophers"):
            return self.get_gopher_url()

        query = self.query
        if not include_query:
            query = ""

        fragment = self.fragment
        if not include_fragment:
            fragment = ""

        parts = (self.scheme, self.netloc, self.path, self.params, query, fragment)
        return urlunparse(parts)

    def get_gemini_request(self) -> bytes:
        """
        Get the URL formatted to be sent in a gemini server.
        """
        path = self.path
        if self.scheme in ("gemini", "text") and path == "":
            # Add an optional trailing slash for gemini because of a quirk in
            # many server implementations that will redirect if the slash is
            # missing from the root URL.
            path = "/"

        # Drop the fragment from the request sent to the server
        fragment = ""

        # Convert domain names to punycode for compatibility with URLs that
        # contain encoded IDNs (follows RFC 3490).
        netloc = self.netloc.encode("idna").decode("ascii")
        parts = (self.scheme, netloc, path, self.params, self.query, fragment)
        url = urlunparse(parts)
        return f"{url}\r\n".encode()

    def get_scroll_request(self, meta: bool, language_list: list[str]) -> bytes:
        """
        Get the URL formatted to be sent to a scroll server.
        """
        path = self.path
        if path == "":
            # Add an optional trailing slash for gemini because of a quirk in
            # many server implementations that will redirect if the slash is
            # missing from the root URL.
            path = "/"

        # Drop the fragment from the request sent to the server
        fragment = ""

        # Convert domain names to punycode for compatibility with URLs that
        # contain encoded IDNs (follows RFC 3490).
        netloc = self.netloc.encode("idna").decode("ascii")
        parts = (self.scheme, netloc, path, self.params, self.query, fragment)
        url = urlunparse(parts)

        lang_str = ",".join(language_list)
        meta_str = "+" if meta else ""

        return f"{url} {meta_str}{lang_str}\r\n".encode()

    def get_gopher_request(self) -> bytes:
        """
        Get the URL formatted to be sent to a gopher server.
        """
        request = self.gopher_selector
        if self.gopher_search:
            request += f"%09{self.gopher_search}"

        if self.gopher_plus_string == "?":
            # Selectors that support ASK queries are denoted in the URL by a
            # "?" in the gopher plus string, but the client is supposed to make
            # a standard "!" info request to retrieve the +ASK block.
            request += "%09!"
        elif self.gopher_plus_string:
            request += f"%09{self.gopher_plus_string}"

        return unquote_to_bytes(f"{request}\r\n")

    def get_root(self, include_user_dirs=False) -> URLReference | None:
        """
        Get the base component of the URL that denotes a unique site.
        """
        if self.scheme == "view-source":
            target = self.get_view_source_target()
            return target.get_root(include_user_dirs=include_user_dirs)

        path = ""
        if include_user_dirs:
            if self.scheme == "finger":
                # E.g. finger://mozz.us/michael
                user = self.finger_request
                path = f"/{user}"
            elif self.scheme == "gopher":
                if len(self.path) >= 3 and self.path[2] == "~":
                    # E.g. gopher://example.com/0~user/file.txt
                    user = self.path[2:].split("/")[0]
                    path = f"/1{user}/"
                elif len(self.path) >= 4 and self.path[2:4] == "/~":
                    # E.g. gopher://example.com/0/~user/file.txt
                    user = self.path[3:].split("/")[0]
                    path = f"/1/{user}/"
            elif self.path.startswith("/~"):
                # E.g. gemini://example.com/~user/file.txt
                user = self.path[1:].split("/")[0]
                path = f"/{user}/"

        if self.scheme == "gopher" and len(path) > 1:
            # Force gopher menu type
            path = f"/1{path[2:]}"

        if self.netloc and path:
            return URLReference(f"{self.scheme}://{self.netloc}{path}")
        elif self.netloc:
            return URLReference(f"{self.scheme}://{self.netloc}")
        else:
            return None

    def get_parent(self) -> URLReference | None:
        """
        Get the parent of the URL with the last path component stripped off.
        """
        path = self.path.rstrip("/")
        if not path:
            # We're already at the root URL
            return None

        # Strip off the last path component and add a trailing slash
        path = "/".join(path.split("/")[:-1]) + "/"

        if self.scheme == "gopher" and len(path) > 1:
            # Force gopher menu type
            path = f"/1{path[2:]}"

        if self.netloc and path:
            return URLReference(f"{self.scheme}://{self.netloc}{path}")
        elif self.netloc:
            return URLReference(f"{self.scheme}://{self.netloc}")
        else:
            return None

    def get_info(self) -> URLReference | None:
        """
        Return a gopher+ info URL for the given resource.
        """
        if self.scheme not in ("gopher", "gophers"):
            return None

        url = self.copy()
        url.gopher_plus_string = "!"
        return url

    def get_view_source(self) -> URLReference:
        """
        Get the URL to view the raw source for the resource.
        """
        if self.scheme == "view-source":
            return self
        else:
            return URLReference(f"view-source:{self.get_url()}")

    def get_view_source_target(self) -> URLReference:
        """
        Get the URL nested inside a view-source scheme.
        """
        if self.scheme == "view-source":
            return URLReference(self.original[12:])
        else:
            return self

    def join(self, url: str) -> URLReference:
        """
        Create a new URL reference using the current object as the base.
        """
        return self.__class__(url, self.get_url())

    def copy(self) -> URLReference:
        """
        Return a copy of the current object.
        """
        return copy.deepcopy(self)

    @classmethod
    def from_filename(cls, filename: str):
        """
        Generate a file:// link from a local filename.
        """
        filename = os.path.abspath(filename)
        url = f"file://{quote(filename)}"
        return cls(url)

    def get_dir(self) -> URLReference:
        """
        If the URL path is not a directory, go up one level to the nearest directory.
        """
        if not self.path:
            # The root URL is always a directory
            return self
        elif self.path.endswith("/"):
            return self
        else:
            parent = self.get_parent()
            if parent is None:
                raise AssertionError(f"Could not derive directory for url: {self}")
            return parent

    def get_proxy_url(self, external=True, **query_params) -> str:
        """
        Build a https://portal.mozz.us/... proxy link for the given URL.
        """
        if self.scheme not in PROXY_SCHEMES:
            if external:
                return self.get_url()
            else:
                raise ValueError(f"Unsupported URL scheme: {self.scheme}")

        if self.scheme == "finger":
            path = self.get_finger_path()
            anchor = None
        elif self.scheme in ("gopher", "gophers"):
            path = self.get_gopher_path()
            # Note: gopher/finger do not support #anchor tags
            anchor = None
        else:
            path = urlunparse(("", "", self.path, self.params, self.query, ""))
            anchor = self.fragment or None

        if path:
            return url_for(
                "proxy-path",
                scheme=self.scheme,
                netloc=self.netloc,
                path=path.lstrip("/"),
                _anchor=anchor,
                **query_params,
            )
        else:
            return url_for(
                "proxy-netloc",
                scheme=self.scheme,
                netloc=self.netloc,
                _anchor=anchor,
                **query_params,
            )

    def get_root_proxy_url(self, include_user_dirs=False) -> str | None:
        """
        Get the base component of the URL as a string.
        """
        root = self.get_root(include_user_dirs)
        if root:
            return root.get_proxy_url()
        else:
            return None

    def get_parent_proxy_url(self) -> str | None:
        """
        Get the parent of the URL as a string.
        """
        parent = self.get_parent()
        if parent:
            return parent.get_proxy_url()
        else:
            return None

    def get_info_proxy_url(self) -> str | None:
        """
        Get the gopher+ info URL as a string.
        """
        info = self.get_info()
        if info:
            return info.get_proxy_url()
        else:
            return None

    def guess_gopher_mimetype(self) -> str | None:
        """
        Attempt to guess a specific mimetype for a gopher selector based on the
        selector's item type and the extension on the selector.
        """
        mimetype, encoding = mimetypes.guess_type(self.path)

        if self.gopher_plus_string.startswith(("!", "$", "?")):
            mimetype = "application/gopher+-attributes"
        elif self.gopher_item_type in ("1", "7"):
            if self.gopher_plus_string:
                mimetype = "application/gopher+-menu"
            else:
                mimetype = "application/gopher-menu"
        elif self.gopher_item_type in ("h", "H"):
            mimetype = "text/html"
        elif self.gopher_item_type == "g":
            mimetype = "image/gif"
        elif self.gopher_item_type == "4":
            mimetype = "application/binhex"
        elif self.gopher_item_type == "6":
            mimetype = "text/x-uuencode"
        elif self.gopher_item_type == "d":
            mimetype = mimetype or "application/pdf"
        elif self.gopher_item_type in ("5", "9"):
            if encoding:
                # For example, gzipped text files
                mimetype = "application/octet-stream"
            else:
                mimetype = mimetype or "application/octet-stream"
        elif self.gopher_item_type == "s":
            if mimetype and mimetype.startswith("audio/"):
                mimetype = mimetype
            else:
                mimetype = "audio/wave"
        elif self.gopher_item_type == "0":
            if mimetype and mimetype.startswith("text/"):
                mimetype = mimetype
            else:
                mimetype = "text/plain"
        elif self.gopher_item_type in ("2", "8", "3", "i", "+"):
            mimetype = None
        else:
            mimetype = mimetype

        return mimetype

    def get_filename(self) -> str:
        return os.path.basename(self.path.strip("/"))


def quote_gopher(selector: str) -> str:
    """
    Apply percent-style escaping to the selector so it can be used in a URL.

    This also works for gopher search strings and gopher+ strings.

    From RFC 4266:
        <selector> is the gopher selector string. In the Gopher protocol,
        Gopher selector strings are a sequence of octets that may contain
        any octets except <tab>, <lf>, and <cr>.

    However, if you take this at face value if means that a gopher URL can
    can contain spaces. Most URL parsing libraries are going to be confused
    by this and screw up. For example, curl won't load a gopher URL with a
    space in it.

    Because gopher URLs do not have any query params or fragments in them, we
    can allow some extra characters that are normally escaped.
    """
    return quote(selector, safe="/?#$+-!=&@.,|")
