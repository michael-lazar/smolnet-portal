import logging
import uuid
from datetime import datetime
from urllib.parse import quote

from quart import (
    Quart,
    Response,
    after_this_request,
    g,
    render_template,
    request,
    url_for,
)
from quart.logging import default_handler
from werkzeug.wrappers.response import Response as WerkzeugResponse

from geminiportal.favicons import favicon_cache
from geminiportal.protocols import build_proxy_request
from geminiportal.protocols.base import ProxyError
from geminiportal.urls import URLReference, quote_gopher
from geminiportal.utils import ProxyOptions

logger = logging.getLogger("geminiportal")
logger.setLevel(logging.INFO)
logger.addHandler(default_handler)

app = Quart(__name__)
app.jinja_env.trim_blocks = True
app.jinja_env.lstrip_blocks = True
app.jinja_env.keep_trailing_newline = True
app.config.from_prefixed_env()


@app.errorhandler(ValueError)
async def handle_value_error(e) -> Response:
    content = await render_template("proxy/gateway-error.html", error=e)
    return Response(content, status=400)


@app.errorhandler(ProxyError)
async def handle_proxy_error(e):
    content = await render_template("proxy/gateway-error.html", error=e)
    return Response(content, status=500)


@app.context_processor
def inject_context():
    kwargs = {}

    kwargs["trap_url"] = url_for("trap", token=uuid.uuid4().hex)

    if "response" in g:
        kwargs["response"] = g.response
        if hasattr(g.response, "tls_cert"):
            kwargs["cert_url"] = g.response.url.get_proxy_url(crt=1)

    if "url" in g:
        kwargs["url"] = g.url.get_url()
        kwargs["proxy_url"] = g.url.get_proxy_url()
        kwargs["root_url"] = g.url.get_root_proxy_url()
        kwargs["parent_url"] = g.url.get_parent_proxy_url() or kwargs["root_url"]
        kwargs["raw_url"] = g.url.get_proxy_url(raw=1)

        if "response" in g and g.response.mimetype in (
            "application/gopher-menu",
            "application/gopher+-menu",
            "application/gopher-attributes",
        ):
            kwargs["vr_url"] = g.url.get_proxy_url(vr=1)

        if "response" in g and g.response.url.scheme == "scroll":
            kwargs["meta_url"] = g.url.get_proxy_url(meta=1)

    elif "address" in g:
        kwargs["url"] = g.address

    if "favicon" in g and g.favicon:
        kwargs["favicon"] = g.favicon
    return kwargs


@app.route("/robots.txt")
async def robots() -> Response:
    return await app.send_static_file("robots.txt")


@app.route("/about")
async def about() -> Response:
    now = datetime.utcnow()
    content = await render_template("about.html", year=now.year)
    return Response(content)


@app.route("/changes")
async def changes() -> Response:
    content = await render_template("changes.html")
    return Response(content)


@app.route("/trap/<token>", endpoint="trap")
async def trap(token: str) -> Response | WerkzeugResponse:
    # Note: this endpoint doesn't actually do anything, I have a fail2ban rule setup
    # that watches the logs for requests to the path /trap/* and adds them to a ban list.
    return Response("Your IP Address has been banned 🧑‍⚖️.", status=404)


@app.route("/")
async def home() -> Response | WerkzeugResponse:
    g.address = request.args.get("url")
    if g.address:
        # URL was provided via the address bar, redirect to the canonical endpoint
        url = g.address.strip()
        proxy_url = URLReference(url).get_proxy_url(external=False)
        return app.redirect(proxy_url)

    content = await render_template("home.html")
    return Response(content)


@app.route("/<scheme>", strict_slashes=False)
async def old_scheme(scheme: str) -> Response | WerkzeugResponse:
    return app.redirect("/", 301)


def set_captcha_cookie(response: Response) -> Response:
    # Set all cookies to expire on Jan 1st to reduce the possibility of
    # tracking users based on their unique cookie expiration timestamp.
    now = datetime.now()
    expires = datetime(now.year + 2, 1, 1)
    response.set_cookie("captcha", "1", samesite="Lax", expires=expires, httponly=True)
    return response


async def check_captcha(options: ProxyOptions) -> Response | WerkzeugResponse | None:
    if request.method == "POST":
        form = await request.form
        if form.get("captcha"):
            after_this_request(set_captcha_cookie)
            return app.redirect(request.full_path, code=303)
        else:
            return Response(status=400)

    if options.raw or options.raw_crt:
        # Allow requests to the raw files.
        return None

    user_agent = request.headers.get("User-Agent", "")
    if "Mozilla" not in user_agent:
        # Allow any bots that don't spoof their user agent.
        # Allow niche browsers like curl, lynx, etc.
        return None

    captcha = request.cookies.get("captcha")
    if captcha:
        after_this_request(set_captcha_cookie)
        return None

    content = await render_template("proxy/captcha.html")
    return Response(content)


@app.route("/<scheme>/<netloc>/", endpoint="proxy-netloc", methods=["GET", "POST"])
@app.route("/<scheme>/<netloc>/<path:path>", endpoint="proxy-path", methods=["GET", "POST"])
async def proxy(
    scheme: str = "gemini", netloc: str | None = None, path: str | None = None
) -> Response | WerkzeugResponse:
    """
    The main entrypoint for the web proxy.
    """
    g.address = request.args.get("url")
    if g.address:
        # URL was provided via the address bar, redirect to the canonical endpoint
        url = g.address.strip()
        proxy_url = URLReference(url).get_proxy_url(external=False)
        return app.redirect(proxy_url)

    g.url = URLReference(f"{scheme}://{netloc}{'' if path is None else '/' + path}")

    query = request.args.get("q")
    if query:
        # Query was provided via the input box, redirect to the canonical endpoint
        if g.url.scheme in ("gopher", "gophers"):
            if "\t" in query:
                # Can't allow any <tab> characters in the gopher query because it
                # would be confused as a gopher+ string.
                raise ValueError("The <tab> character is not allowed in gopher searches")
            g.url.gopher_search = quote_gopher(query)
        else:
            g.url.query = quote(query)

        proxy_url = g.url.get_proxy_url(external=False)
        return app.redirect(proxy_url)

    options = ProxyOptions(
        charset=request.args.get("charset") or None,
        lang=request.args.get("lang") or None,
        format=request.args.get("format") or None,
        raw=bool(request.args.get("raw")),
        raw_crt=bool(request.args.get("raw_crt")),
        vr=bool(request.args.get("vr")),
        crt=bool(request.args.get("crt")),
        meta=bool(request.args.get("meta")),
    )

    captcha_response = await check_captcha(options)
    if captcha_response:
        return captcha_response

    proxy_request = build_proxy_request(g.url, options)
    response = await proxy_request.get_response()

    g.response = response
    g.favicon = favicon_cache.check(g.url)

    proxy_response = await response.build_proxy_response()
    return proxy_response


if __name__ == "__main__":
    app.config["DEBUG"] = True
    app.config["SERVER_NAME"] = "localhost:8000"
    app.run()
