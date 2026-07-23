import pytest


async def test_get_robots(client):
    response = await client.get("/robots.txt")
    assert response.status_code == 200
    assert response.mimetype == "text/plain"


async def test_get_about(client):
    response = await client.get("/about")
    assert response.status_code == 200


async def test_get_changes(client):
    response = await client.get("/changes")
    assert response.status_code == 200


async def test_get_home(client):
    response = await client.get("/")
    assert response.status_code == 200


async def test_input_url_redirect(client):
    response = await client.get(
        "/gemini/mozz.us/",
        query_string={"url": "spartan://mozz.us/test"},
    )
    assert response.status_code == 302
    assert response.location == "/spartan/mozz.us/test"


async def test_input_url_preserve_double_slashes(client):
    response = await client.get(
        "/gemini/mozz.us/",
        query_string={"url": "spartan://mozz.us/test//.//"},
    )
    assert response.status_code == 302
    assert response.location == "/spartan/mozz.us/test//.//"


async def test_input_query_redirect(client):
    response = await client.get(
        "/gemini/mozz.us/",
        query_string={"q": "hello world"},
    )
    assert response.status_code == 302
    # Space is double encoded ($2520)
    assert response.location == "/gemini/mozz.us/%3Fhello%2520world"


async def test_titan_upload_form(client):
    # No titan request is made until the upload form is submitted, so no
    # network access is required.
    response = await client.get("/titan/mozz.us/test.gmi")
    assert response.status_code == 200
    assert "Titan Upload" in await response.get_data(as_text=True)


@pytest.mark.integration
async def test_download_raw_certificate(client):
    response = await client.get("/gemini/mozz.us/?raw_crt=1")
    assert response.status_code == 200
    assert response.mimetype == "application/x-x509-ca-cert"


@pytest.mark.integration
async def test_view_certificate_page(client):
    response = await client.get("/gemini/mozz.us/?crt=1")
    assert response.status_code == 200
    assert response.mimetype == "text/html"


@pytest.mark.integration
async def test_gemini_redirect(client):
    response = await client.get("/gemini/mozz.us/journal")
    assert response.status_code == 303
    assert response.location == "/gemini/mozz.us/journal/"


@pytest.mark.integration
async def test_gemini_handler_success(client):
    response = await client.get("/gemini/mozz.us/")
    assert response.status_code == 200
    assert response.mimetype == "text/html"


@pytest.mark.integration
async def test_gemini_handler_raw_response(client):
    response = await client.get("/gemini/mozz.us/?raw=1")
    assert response.status_code == 200
    assert response.mimetype == "text/plain"
