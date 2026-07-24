from geminiportal.urls import URLReference
from geminiportal.utils import parse_link_line

BASE = URLReference("gemini://mozz.us/")


def test_parse_link_line():
    url, link_text, prefix = parse_link_line("/hello.gmi Hello, world!", BASE)
    assert url.get_url() == "gemini://mozz.us/hello.gmi"
    assert link_text == "Hello, world!"
    assert prefix == ""


def test_parse_link_line_no_text():
    url, link_text, prefix = parse_link_line("/hello.gmi", BASE)
    assert url.get_url() == "gemini://mozz.us/hello.gmi"
    assert link_text == "/hello.gmi"
    assert prefix == ""


def test_parse_link_line_emoji_prefix():
    url, link_text, prefix = parse_link_line("/hello.gmi 🚀 Hello, world!", BASE)
    assert url.get_url() == "gemini://mozz.us/hello.gmi"
    assert link_text == "Hello, world!"
    assert prefix == "🚀 "


def test_parse_link_line_emoji_only():
    # If the link text is only an emoji, it should be kept inside of the
    # link so there's still something to click on.
    url, link_text, prefix = parse_link_line("/hello.gmi 🚀", BASE)
    assert url.get_url() == "gemini://mozz.us/hello.gmi"
    assert link_text == "🚀"
    assert prefix == ""
