from geminiportal.urls import URLReference


def test_deconstruct_gemini():
    url = URLReference("gemini://mozz.us/")
    assert url.scheme == "gemini"
    assert url.port == 1965
    assert url.hostname == "mozz.us"
    assert url.path == ""
    assert url.params == ""
    assert url.query == ""
    assert url.fragment == ""
    assert url.guess_mimetype() is None
    assert url.get_external_indicator() is None
    assert url.get_url() == "gemini://mozz.us"


def test_deconstruct_gemini_full():
    url = URLReference("gemini://mozz.us:1966/%20Hello.gmi?foo=2&bar=3#%20world")
    assert url.scheme == "gemini"
    assert url.port == 1966
    assert url.hostname == "mozz.us"
    assert url.path == "/%20Hello.gmi"
    assert url.params == ""
    assert url.query == "foo=2&bar=3"
    assert url.fragment == "%20world"
    assert url.guess_mimetype() == "text/gemini"
    assert url.get_external_indicator() is None
    assert url.get_url() == "gemini://mozz.us:1966/%20Hello.gmi?foo=2&bar=3#%20world"


def test_deconstruct_gemini_relative():
    url = URLReference("good/vibrations/", "gemini://mozz.us:1965/hello/world.gmi")
    assert url.scheme == "gemini"
    assert url.port == 1965
    assert url.hostname == "mozz.us"
    assert url.path == "/hello/good/vibrations/"
    assert url.params == ""
    assert url.guess_mimetype() is None
    assert url.get_external_indicator() is None
    assert url.get_url() == "gemini://mozz.us/hello/good/vibrations/"


def test_get_external_indicator_hostname():
    url = URLReference("gemini://chat.mozz.us", "gemini://mozz.us/")
    assert url.scheme == "gemini"
    assert url.port == 1965
    assert url.hostname == "chat.mozz.us"
    assert url.path == ""
    assert url.params == ""
    assert url.guess_mimetype() is None
    assert url.get_external_indicator() == "chat.mozz.us"
    assert url.get_url() == "gemini://chat.mozz.us"


def test_get_external_indicator_hostname_and_scheme():
    url = URLReference("gemini://chat.mozz.us", "gopher://mozz.us/")
    assert url.get_external_indicator() == "gemini://chat.mozz.us"


def test_deconstruct_finger_url():
    url = URLReference("finger://space.mit.edu:79/nasanews")
    assert url.finger_request == "nasanews"
    assert url.get_url() == "finger://space.mit.edu/nasanews"


def test_deconstruct_finger_url_null_request():
    url = URLReference("finger://space.mit.edu")
    assert url.finger_request == ""
    assert url.get_url() == "finger://space.mit.edu"


def test_deconstruct_finger_url_not_encoded():
    url = URLReference("finger://host2.bigstate.edu/someuser@host1.bigstate.edu")
    assert url.finger_request == "someuser@host1.bigstate.edu"
    assert url.get_url() == "finger://host2.bigstate.edu/someuser@host1.bigstate.edu"


def test_deconstruct_finger_url_encoded():
    url = URLReference("finger://host1.bigstate.edu/%2FW%20someuser")
    assert url.finger_request == "%2FW%20someuser"
    assert url.get_url() == "finger://host1.bigstate.edu/%2FW%20someuser"


def test_deconstruct_gopher():
    url = URLReference("gopher://mozz.us")
    assert url.gopher_item_type == "1"
    assert url.gopher_selector == ""
    assert url.guess_mimetype() == "application/gopher-menu"
    assert url.get_url() == "gopher://mozz.us"


def test_deconstruct_gopher_trailing_slash():
    url = URLReference("gopher://mozz.us/")
    assert url.gopher_item_type == "1"
    assert url.gopher_selector == ""
    assert url.get_url() == "gopher://mozz.us"


def test_deconstruct_gopher_file_type():
    url = URLReference("gopher://mozz.us:222/0")
    assert url.gopher_item_type == "0"
    assert url.gopher_selector == ""
    assert url.guess_mimetype() == "text/plain"
    assert url.get_url() == "gopher://mozz.us:222/0"


def test_deconstruct_gopher_full():
    url = URLReference("gopher://mozz.us/9/file.pdf?extra#info%20.jpg")
    assert url.gopher_item_type == "9"
    assert url.gopher_selector == "/file.pdf?extra#info%20.jpg"
    assert url.guess_mimetype() == "application/pdf"
    assert url.get_url() == "gopher://mozz.us/9/file.pdf?extra#info%20.jpg"


def test_deconstruct_unknown_scheme():
    url = URLReference("mailto:michael@mozz.us", "gemini://mozz.us/")
    assert url.scheme == "mailto"
    assert url.port is None
    assert url.hostname is None
    assert url.path == "michael@mozz.us"
    assert url.params == ""
    assert url.guess_mimetype() is None
    assert url.get_external_indicator() == "mailto://"
    assert url.get_url() == "mailto:michael@mozz.us"


def test_url_join():
    url = URLReference("gemini://mozz.us/").join("/hello")
    assert url.get_url() == "gemini://mozz.us/hello"


def test_get_root_url_gopher():
    url = URLReference("gopher://mozz.us/1~mozz")
    assert url.get_root().get_url() == "gopher://mozz.us"
    assert url.get_root(include_user_dirs=True).get_url() == "gopher://mozz.us/1~mozz/"


def test_get_root_url_spartan():
    url = URLReference("spartan://mozz.us/~mozz/hello")
    assert url.get_root().get_url() == "spartan://mozz.us"
    assert url.get_root(include_user_dirs=True).get_url() == "spartan://mozz.us/~mozz/"


def test_get_root_url_finger():
    url = URLReference("finger://mozz.us/michael")
    assert url.get_root().get_url() == "finger://mozz.us"
    assert url.get_root(include_user_dirs=True).get_url() == "finger://mozz.us/michael"


def test_get_root_url_mailto():
    url = URLReference("mailto:michael@mozz.us")
    assert url.get_root() is None
    assert url.get_root(include_user_dirs=True) is None


def test_get_root_url_view_source():
    url = URLReference("view-source:gemini://mozz.us/michael")
    assert url.get_root().get_url() == "gemini://mozz.us"


def test_get_parent_url_base():
    url = URLReference("gemini://mozz.us")
    assert url.get_parent() is None


def test_get_parent_url_slash():
    url = URLReference("gemini://mozz.us/")
    assert url.get_parent() is None


def test_get_parent_url_extra():
    url = URLReference("gemini://mozz.us/hello/world?q=2#hi")
    assert url.get_parent().get_url() == "gemini://mozz.us/hello/"


def test_get_parent_url_directory():
    url = URLReference("gemini://mozz.us/hello/")
    assert url.get_parent().get_url() == "gemini://mozz.us"


def test_get_parent_url_gopher_dir_type():
    url = URLReference("gopher://mozz.us/2hello/there")
    assert url.get_parent().get_url() == "gopher://mozz.us/1hello/"


def test_get_root_url_gopher_dir_type():
    url = URLReference("gopher://mozz.us/2~user/there")
    assert url.get_root(include_user_dirs=True).get_url() == "gopher://mozz.us/1~user/"


def test_get_root_url_gopher_dir_type_alt():
    url = URLReference("gopher://mozz.us/2/~user/there")
    assert url.get_root(include_user_dirs=True).get_url() == "gopher://mozz.us/1/~user/"


def test_gopher_parse_search_data():
    url = URLReference("gopher://mozz.us/7hello%09search%09/data")
    assert url.gopher_selector == "hello"
    assert url.gopher_search == "search"
    assert url.gopher_plus_string == "/data"

    assert url.get_url() == "gopher://mozz.us/7hello%09search%09/data"
    assert url.get_parent().get_url() == "gopher://mozz.us"
    assert url.get_root().get_url() == "gopher://mozz.us"


async def test_get_proxy_gemini_link(app):
    base = URLReference("gemini://mozz.us/test/")
    async with app.app_context():
        url = base.join("gemini://mozz.us")
        assert url.get_proxy_url() == "http://portal.mozz.us/gemini/mozz.us/"


async def test_get_proxy_spartan_link(app):
    base = URLReference("gemini://mozz.us/test/")
    async with app.app_context():
        url = base.join("spartan://mozz.us")
        assert url.get_proxy_url() == "http://portal.mozz.us/spartan/mozz.us/"


async def test_get_proxy_text_link(app):
    base = URLReference("gemini://mozz.us/test/")
    async with app.app_context():
        url = base.join("text://mozz.us")
        assert url.get_proxy_url() == "http://portal.mozz.us/text/mozz.us/"


async def test_get_proxy_gopher_link(app):
    base = URLReference("gemini://mozz.us/test/")
    async with app.app_context():
        url = base.join("gopher://mozz.us")
        assert url.get_proxy_url() == "http://portal.mozz.us/gopher/mozz.us/"


async def test_get_proxy_gemini_link_relative(app):
    base = URLReference("gemini://mozz.us/test/")
    async with app.app_context():
        url = base.join("picture.jpg")
        assert url.get_proxy_url() == "http://portal.mozz.us/gemini/mozz.us/test/picture.jpg"


async def test_get_proxy_gemini_link_cwd(app):
    base = URLReference("gemini://mozz.us/test/")
    async with app.app_context():
        url = base.join(".")
        assert url.get_proxy_url() == "http://portal.mozz.us/gemini/mozz.us/test/"


async def test_get_proxy_gemini_link_parent(app):
    base = URLReference("gemini://mozz.us/test/")
    async with app.app_context():
        url = base.join("..")
        assert url.get_proxy_url() == "http://portal.mozz.us/gemini/mozz.us/"


async def test_get_proxy_gemini_link_different_host(app):
    base = URLReference("gemini://mozz.us/test/")
    async with app.app_context():
        url = base.join("gemini://ascii.mozz.us")
        assert url.get_proxy_url() == "http://portal.mozz.us/gemini/ascii.mozz.us/"


async def test_get_proxy_gemini_link_different_scheme(app):
    base = URLReference("gemini://mozz.us/test/")
    async with app.app_context():
        url = base.join("spartan://mozz.us/")
        assert url.get_proxy_url() == "http://portal.mozz.us/spartan/mozz.us/"


async def test_get_proxy_unknown_scheme(app):
    url = URLReference("telnet://mozz.us:23")
    async with app.app_context():
        assert url.get_proxy_url() == "telnet://mozz.us:23"


def test_get_gopher_request():
    url = URLReference("gopher://mozz.us/0my%20file.txt")
    assert url.get_gopher_request() == b"my file.txt\r\n"


def test_get_gopher_request_search():
    url = URLReference("gopher://mozz.us/0selector%09search%20string")
    assert url.get_gopher_request() == b"selector\tsearch string\r\n"


def test_get_gopher_request_plus():
    url = URLReference("gopher://mozz.us/0selector%09%09+")
    assert url.get_gopher_request() == b"selector\t+\r\n"


def test_get_gopher_request_plus_search():
    url = URLReference("gopher://mozz.us/0selector%09search%09+")
    assert url.get_gopher_request() == b"selector\tsearch\t+\r\n"


def test_get_gopher_request_plus_ask():
    url = URLReference("gopher://mozz.us/0selector%09%09?")
    assert url.get_gopher_request() == b"selector\t!\r\n"


def test_get_scroll_request():
    url = URLReference("scroll://scrollprotocol.us.to/spec.scroll")
    request = url.get_scroll_request(meta=False, language_list=["en"])
    assert request == b"scroll://scrollprotocol.us.to/spec.scroll en\r\n"


def test_get_scroll_request_meta():
    url = URLReference("scroll://scrollprotocol.us.to/spec.scroll")
    request = url.get_scroll_request(meta=True, language_list=["en", "es"])
    assert request == b"scroll://scrollprotocol.us.to/spec.scroll +en,es\r\n"
