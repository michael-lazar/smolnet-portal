import logging
import uuid
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from functools import wraps
from typing import Any
from urllib.parse import quote, urlsplit

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

from geminiportal import auth, db, sessions
from geminiportal.errors import BaseProxyError, InvalidRequestError
from geminiportal.favicons import favicon_cache
from geminiportal.protocols import build_proxy_request
from geminiportal.protocols.base import supports_client_cert
from geminiportal.tls import parse_tls_cert
from geminiportal.urls import URLReference, quote_gopher
from geminiportal.utils import HTTPResponse, ProxyOptions

logger = logging.getLogger("geminiportal")
logger.setLevel(logging.INFO)
logger.addHandler(default_handler)

app = Quart(__name__)
app.jinja_env.trim_blocks = True
app.jinja_env.lstrip_blocks = True
app.jinja_env.keep_trailing_newline = True
app.config.from_prefixed_env()


@app.before_serving
async def startup() -> None:
    await db.run_migrations()
    await sessions.purge_expired_sessions()


@app.before_request
async def load_current_session() -> None:
    g.session = await sessions.load_session()


@app.after_serving
async def shutdown() -> None:
    favicon_cache.shutdown()
    await db.engine.dispose()


@app.errorhandler(ValueError)
async def handle_value_error(e) -> Response:
    return await handle_proxy_error(InvalidRequestError(e))


@app.errorhandler(BaseProxyError)
async def handle_proxy_error(e) -> Response:
    # If a response was received, don't render its details on the error page
    g.pop("response", None)

    content = await render_template("proxy/portal-error.html", error=e)
    return Response(content, status=e.http_status)


@app.context_processor
def inject_context():
    kwargs: dict[str, Any] = {}

    kwargs["trap_url"] = url_for("trap", token=uuid.uuid4().hex)

    session = g.get("session")
    kwargs["session"] = session

    if session is None:
        kwargs["login_url"] = url_for("login", next=request.full_path)
    else:
        kwargs["profile_url"] = url_for("profile")

    if "response" in g:
        kwargs["response"] = g.response
        if hasattr(g.response, "tls_cert"):
            kwargs["cert_url"] = g.response.url.get_proxy_url(crt=1)

    if "url" in g:
        kwargs["url"] = g.url.get_url()
        # Setting reader=None forces reader mode to be cleared when opening this link
        kwargs["proxy_url"] = g.url.get_proxy_url(reader=None)
        kwargs["root_url"] = g.url.get_root_proxy_url()
        kwargs["parent_url"] = g.url.get_parent_proxy_url() or kwargs["root_url"]
        kwargs["raw_url"] = g.url.get_proxy_url(raw=1)
        kwargs["reader_url"] = g.url.get_proxy_url(reader=1)

        if "response" in g and g.response.mimetype in (
            "application/gopher-menu",
            "application/gopher+-menu",
            "application/gopher-attributes",
        ):
            kwargs["vr_url"] = g.url.get_proxy_url(vr=1)

        if "response" in g and g.response.url.scheme == "scroll":
            kwargs["meta_url"] = g.url.get_proxy_url(meta=1)

        if "cert_active" in g:
            cert_params = {
                "scheme": g.url.scheme,
                "hostname": g.url.hostname,
                "port": g.url.port,
                "next": request.full_path,
            }
            if g.cert_active:
                kwargs["cert_deactivate_url"] = url_for("cert_deactivate", **cert_params)
            else:
                kwargs["cert_activate_url"] = url_for("cert_activate", **cert_params)

    elif "address" in g:
        kwargs["url"] = g.address

    if "favicon" in g and g.favicon:
        kwargs["favicon"] = g.favicon

    if "options" in g:
        kwargs["reader"] = g.options.reader

    return kwargs


@app.route("/robots.txt")
async def robots() -> Response:
    return await app.send_static_file("robots.txt")


@app.route("/about")
async def about() -> Response:
    now = datetime.now(UTC)
    content = await render_template("about.html", year=now.year)
    return Response(content)


@app.route("/changes")
async def changes() -> Response:
    content = await render_template("changes.html")
    return Response(content)


@app.route("/trap/<token>", endpoint="trap")
async def trap(token: str) -> HTTPResponse:
    # Note: this endpoint doesn't actually do anything, I have a fail2ban rule setup
    # that watches the logs for requests to the path /trap/* and adds them to a ban list.
    return Response("Your IP Address has been banned 🧑‍⚖️.", status=404)


@app.route("/")
async def home() -> HTTPResponse:
    g.address = request.args.get("url")
    if g.address:
        # URL was provided via the address bar, redirect to the canonical endpoint
        url = g.address.strip()
        proxy_url = URLReference(url).get_proxy_url(external=False)
        return app.redirect(proxy_url)

    content = await render_template("home.html")
    return Response(content)


def clean_next_url(next_url: str | None) -> str:
    """
    Only allow redirects to relative paths within the portal, so the
    "next" param can't be used as an open redirect.
    """
    if next_url and next_url.startswith("/") and not next_url.startswith("//"):
        if "\\" not in next_url:
            return next_url
    return "/"


def parse_proxy_path_origin(path: str) -> auth.Origin | None:
    """
    Extract the origin from a portal proxy path like "/gemini/host/...",
    returning None if the path doesn't point to an origin that a client
    certificate can be activated for.
    """
    parts = urlsplit(path).path.split("/")
    if len(parts) < 3:
        return None

    scheme, netloc = parts[1], parts[2]
    if not supports_client_cert(scheme):
        return None

    try:
        url = URLReference(f"{scheme}://{netloc}")
    except ValueError:
        return None

    if not url.hostname or not url.port:
        return None

    return auth.Origin(url.scheme, url.hostname, url.port)


def login_required(
    func: Callable[..., Awaitable[HTTPResponse]],
) -> Callable[..., Awaitable[HTTPResponse]]:
    """
    Redirect to the login page when the request has no active session.
    """

    @wraps(func)
    async def wrapper(*args: Any, **kwargs: Any) -> HTTPResponse:
        if g.session is None:
            return app.redirect(url_for("login", next=request.full_path), 303)
        return await func(*args, **kwargs)

    return wrapper


def post_required(
    func: Callable[..., Awaitable[HTTPResponse]],
) -> Callable[..., Awaitable[HTTPResponse]]:
    """
    Reject non-POST requests with a 405; the catch-all proxy route would
    otherwise swallow these URLs instead of returning a proper error.
    """

    @wraps(func)
    async def wrapper(*args: Any, **kwargs: Any) -> HTTPResponse:
        if request.method != "POST":
            return Response(status=405, headers={"Allow": "POST"})
        return await func(*args, **kwargs)

    return wrapper


@app.route("/login", methods=["GET", "POST"])
async def login() -> HTTPResponse:
    next_arg = request.args.get("next")
    form_action = url_for("login", next=next_arg) if next_arg else url_for("login")

    if request.method == "GET":
        content = await render_template("login.html", error=None, form_action=form_action)
        return Response(content)

    try:
        cert_pem, key_pem = await auth.read_keypair_upload()
    except auth.CertValidationError as e:
        content = await render_template("login.html", error=str(e), form_action=form_action)
        return Response(content, status=400)

    if g.session is not None:
        # Re-login replaces the stored session
        await sessions.delete_session(g.session)

    cert_info = parse_tls_cert(cert_pem.encode())
    g.session = await sessions.create_session(cert_pem, key_pem, cert_info)

    next_url = clean_next_url(next_arg)

    # When the login page was reached from a capsule, activate the new
    # certificate for that origin so landing there doesn't require a
    # second [activate] click
    origin = parse_proxy_path_origin(next_url)
    if origin is not None:
        await auth.activate_cert(g.session, origin)

    response = app.redirect(next_url, 303)
    sessions.set_session_cookie(response, g.session.token)
    return response


@app.route("/logout", methods=["GET", "POST"])
@post_required
async def logout() -> HTTPResponse:
    if g.session is not None:
        await sessions.delete_session(g.session)
        g.session = None

    response = app.redirect(clean_next_url(request.args.get("next")), 303)
    sessions.delete_session_cookie(response)
    return response


@app.route("/profile")
@login_required
async def profile() -> HTTPResponse:
    activations = []
    for activation in await auth.list_activations(g.session):
        url = URLReference(f"{activation.scheme}://{activation.hostname}:{activation.port}")
        activations.append(
            {
                "display": url.get_url(),
                "proxy_url": url.get_proxy_url(external=False),
                "deactivate_url": url_for(
                    "cert_deactivate",
                    scheme=activation.scheme,
                    hostname=activation.hostname,
                    port=activation.port,
                    next=url_for("profile"),
                ),
            }
        )

    content = await render_template("profile.html", activations=activations)
    return Response(content)


@app.route("/auth/certificate/download")
@login_required
async def cert_download() -> HTTPResponse:
    # The combined PEM format round-trips through the login form
    return Response(
        g.session.identity_pem,
        content_type="application/x-pem-file",
        headers={"Content-Disposition": "attachment; filename=identity.pem"},
    )


def parse_cert_activation_params() -> auth.Origin:
    scheme = request.args.get("scheme", "")
    if not supports_client_cert(scheme):
        raise ValueError(f'"{scheme}" is not a scheme that supports client certificates')

    hostname = (request.args.get("hostname") or "").strip().lower()
    if not hostname:
        raise ValueError("A hostname is required")

    port_str = request.args.get("port")
    if port_str:
        port = int(port_str)
        if not 1 <= port <= 65535:
            raise ValueError(f"Invalid port: {port}")
    else:
        port = URLReference.DEFAULT_PORTS[scheme]

    return auth.Origin(scheme, hostname, port)


async def update_cert_activation(activate: bool) -> HTTPResponse:
    origin = parse_cert_activation_params()

    if activate:
        await auth.activate_cert(g.session, origin)
    else:
        await auth.deactivate_cert(g.session, origin)

    next_url = request.args.get("next")
    if not next_url:
        url = URLReference(f"{origin.scheme}://{origin.hostname}:{origin.port}")
        next_url = url.get_proxy_url(external=False)

    return app.redirect(clean_next_url(next_url), 303)


@app.route("/auth/certificate/activate", methods=["GET", "POST"])
@post_required
@login_required
async def cert_activate() -> HTTPResponse:
    return await update_cert_activation(activate=True)


@app.route("/auth/certificate/deactivate", methods=["GET", "POST"])
@post_required
@login_required
async def cert_deactivate() -> HTTPResponse:
    return await update_cert_activation(activate=False)


@app.route("/<scheme>", strict_slashes=False)
async def old_scheme(scheme: str) -> HTTPResponse:
    return app.redirect("/", 301)


def set_captcha_cookie(response: HTTPResponse) -> HTTPResponse:
    # Set all cookies to expire on Jan 1st to reduce the possibility of
    # tracking users based on their unique cookie expiration timestamp.
    now = datetime.now()
    expires = datetime(now.year + 2, 1, 1)
    response.set_cookie("captcha", "1", samesite="Lax", expires=expires, httponly=True)
    return response


async def check_captcha(options: ProxyOptions) -> HTTPResponse | None:
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

    if "HTMLPDF" in user_agent:
        # Allow www.sejda.com HTML -> PDF conversion tool
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
) -> HTTPResponse:
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

    client_crt = None
    if g.session and supports_client_cert(g.url.scheme) and g.url.hostname and g.url.port:
        origin = auth.Origin(g.url.scheme, g.url.hostname, g.url.port)
        g.cert_active = await auth.is_cert_activated(g.session, origin)
        if g.cert_active:
            client_crt = g.session.identity_pem

    options = ProxyOptions(
        charset=request.args.get("charset") or None,
        lang=request.args.get("lang") or None,
        raw=bool(request.args.get("raw")),
        raw_crt=bool(request.args.get("raw_crt")),
        vr=bool(request.args.get("vr")),
        crt=bool(request.args.get("crt")),
        meta=bool(request.args.get("meta")),
        reader=bool(request.args.get("reader")),
        client_crt=client_crt,
    )

    captcha_response = await check_captcha(options)
    if captcha_response:
        return captcha_response

    proxy_request = build_proxy_request(g.url, options)
    response = await proxy_request.get_response()

    g.response = response
    g.options = options
    g.favicon = await favicon_cache.check(g.url)

    proxy_response = await response.build_proxy_response()
    return proxy_response


if __name__ == "__main__":
    app.run(port=8000, debug=True)
