import pytest

from geminiportal.protocols import (
    FingerRequest,
    GeminiRequest,
    GopherRequest,
    NexRequest,
    SpartanRequest,
    TxtRequest,
    build_proxy_request,
)
from geminiportal.urls import URLReference
from geminiportal.utils import ProxyOptions


def test_build_proxy_request_gemini():
    url = URLReference("gemini://mozz.us/hello")
    request = build_proxy_request(url)
    assert isinstance(request, GeminiRequest)
    assert request.port == 1965
    assert request.host == "mozz.us"


def test_build_proxy_request_spartan():
    url = URLReference("spartan://mozz.us:3000")
    request = build_proxy_request(url)
    assert isinstance(request, SpartanRequest)
    assert request.port == 3000
    assert request.host == "mozz.us"


def test_build_proxy_request_txt():
    url = URLReference("text://174.138.124.169/hello")
    request = build_proxy_request(url)
    assert isinstance(request, TxtRequest)
    assert request.port == 1961
    assert request.host == "174.138.124.169"


def test_build_proxy_request_finger():
    url = URLReference("finger://mozz.us/michael")
    request = build_proxy_request(url)
    assert isinstance(request, FingerRequest)
    assert request.port == 79
    assert request.host == "mozz.us"


def test_build_proxy_request_gopher():
    url = URLReference("gopher://mozz.us/")
    request = build_proxy_request(url)
    assert isinstance(request, GopherRequest)
    assert request.port == 70
    assert request.host == "mozz.us"


def test_build_proxy_request_nex():
    url = URLReference("nex://mozz.us")
    request = build_proxy_request(url)
    assert isinstance(request, NexRequest)
    assert request.port == 1900
    assert request.host == "mozz.us"


def test_build_proxy_request_missing_host():
    url = URLReference("mozz.us")
    with pytest.raises(ValueError):
        build_proxy_request(url)


def test_build_proxy_request_blocked_host():
    url = URLReference("gemini://vger.cloud/hello")
    with pytest.raises(ValueError):
        build_proxy_request(url)


def test_build_proxy_request_blocked_port():
    url = URLReference("gemini://mozz.us:22")
    with pytest.raises(ValueError):
        build_proxy_request(url)


@pytest.mark.integration
async def test_gemini_request():
    url = URLReference("gemini://mozz.us")
    request = build_proxy_request(url)
    response = await request.get_response()
    assert await response.get_body()

    assert response.tls_close_notify_received
    assert response.tls_cert
    assert response.tls_version
    assert response.tls_cipher


@pytest.mark.integration
async def test_spartan_request():
    url = URLReference("spartan://mozz.us/echo?hello%20world")
    request = build_proxy_request(url)
    response = await request.get_response()
    assert await response.get_body() == b"hello world"


@pytest.mark.integration
async def test_txt_request():
    url = URLReference("text://txt.textprotocol.org/")
    request = build_proxy_request(url)
    response = await request.get_response()
    assert await response.get_body()


@pytest.mark.integration
async def test_finger_request():
    url = URLReference("finger://mozz.us/michael")
    request = build_proxy_request(url)
    response = await request.get_response()
    assert await response.get_body()


@pytest.mark.integration
async def test_nex_request():
    url = URLReference("nex://nex.nightfall.city")
    request = build_proxy_request(url)
    response = await request.get_response()
    assert await response.get_body()


@pytest.mark.integration
async def test_gopher_request():
    url = URLReference("gopher://mozz.us")
    request = build_proxy_request(url)
    response = await request.get_response()
    assert await response.get_body()


@pytest.mark.integration
async def test_gopher_plus_request():
    url = URLReference("gopher://mozz.us:7070/%09%09!")
    request = build_proxy_request(url)
    response = await request.get_response()
    assert await response.get_body()


@pytest.mark.integration
async def test_scroll_request():
    url = URLReference("scroll://scrollprotocol.us.to")
    request = build_proxy_request(url)
    response = await request.get_response()
    assert await response.get_body()


@pytest.mark.integration
async def test_scroll_request_meta():
    url = URLReference("scroll://scrollprotocol.us.to")
    request = build_proxy_request(url, options=ProxyOptions(meta=True))
    response = await request.get_response()
    assert await response.get_body()
