from __future__ import annotations

import secrets
from datetime import UTC, datetime, timedelta

from quart import after_this_request, request
from sqlalchemy import delete, select

from geminiportal import db
from geminiportal.models import Session
from geminiportal.tls import CertInfo
from geminiportal.utils import HTTPResponse, utcnow

SESSION_COOKIE_NAME = "session_id"
SESSION_LIFETIME = timedelta(days=400)
SESSION_REFRESH_INTERVAL = timedelta(days=1)


def set_session_cookie(response: HTTPResponse, token: str) -> None:
    response.set_cookie(
        SESSION_COOKIE_NAME,
        token,
        expires=datetime.now(UTC) + SESSION_LIFETIME,
        httponly=True,
        samesite="Lax",
    )


def delete_session_cookie(response: HTTPResponse) -> None:
    response.delete_cookie(SESSION_COOKIE_NAME)


async def load_session() -> Session | None:
    """
    Look up the session for the current request's cookie.
    """
    token = request.cookies.get(SESSION_COOKIE_NAME)
    if not token:
        return None

    now = utcnow()
    async with db.session_factory() as dbs:
        session = await dbs.scalar(
            select(Session).where(
                Session.token == token,
                Session.expires_at > now,
            )
        )
        if session is None:
            return None

        if session.expires_at < now + SESSION_LIFETIME - SESSION_REFRESH_INTERVAL:
            session.expires_at = now + SESSION_LIFETIME
            await dbs.commit()

            # Re-set the cookie so its expiration matches the session row
            # pyrefly: ignore [bad-argument-type]
            @after_this_request
            def refresh_session_cookie(response: HTTPResponse) -> HTTPResponse:
                set_session_cookie(response, token)
                return response

    return session


async def create_session(cert_pem: str, key_pem: str, cert_info: CertInfo) -> Session:
    """
    Store a new session, returning it with a freshly generated token.
    """
    now = utcnow()
    session = Session(
        token=secrets.token_urlsafe(32),
        cert_pem=cert_pem,
        key_pem=key_pem,
        cert_common_name=cert_info.common_name,
        cert_subject=cert_info.subject,
        cert_issuer=cert_info.issuer,
        cert_not_valid_before=cert_info.not_valid_before,
        cert_not_valid_after=cert_info.not_valid_after,
        cert_fingerprint=cert_info.fingerprint,
        created_at=now,
        expires_at=now + SESSION_LIFETIME,
    )
    async with db.session_factory() as dbs:
        dbs.add(session)
        await dbs.commit()

    return session


async def delete_session(session: Session) -> None:
    """
    Invalidate the session server-side, destroying the stored keypair.
    The session's activations are removed by the ON DELETE CASCADE.
    """
    async with db.session_factory() as dbs:
        await dbs.execute(delete(Session).where(Session.id == session.id))
        await dbs.commit()


async def purge_expired_sessions() -> None:
    async with db.session_factory() as dbs:
        await dbs.execute(delete(Session).where(Session.expires_at <= utcnow()))
        await dbs.commit()
