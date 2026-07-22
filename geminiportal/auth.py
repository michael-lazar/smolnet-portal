from __future__ import annotations

import ssl
import tempfile
from typing import NamedTuple

from quart import request
from sqlalchemy import delete, select
from sqlalchemy.dialects.sqlite import insert
from werkzeug.datastructures import FileStorage

from geminiportal import db
from geminiportal.models import CertActivation, Session
from geminiportal.tls import get_ssl_context

# Real keypairs are 1-8 KB, reject anything unreasonably large
MAX_PEM_SIZE = 32 * 1024


class CertValidationError(Exception):
    """
    The uploaded certificate/key could not be validated, contains a
    user-facing error message.
    """


class Origin(NamedTuple):
    """
    An origin that a client certificate can be activated for.
    """

    scheme: str
    hostname: str
    port: int


async def activate_cert(session: Session, origin: Origin) -> None:
    statement = (
        insert(CertActivation)
        .values(
            session_id=session.id,
            scheme=origin.scheme,
            hostname=origin.hostname,
            port=origin.port,
        )
        .on_conflict_do_nothing()
    )
    async with db.session_factory() as dbs:
        await dbs.execute(statement)
        await dbs.commit()


async def deactivate_cert(session: Session, origin: Origin) -> None:
    async with db.session_factory() as dbs:
        await dbs.execute(
            delete(CertActivation).where(
                CertActivation.session_id == session.id,
                CertActivation.scheme == origin.scheme,
                CertActivation.hostname == origin.hostname,
                CertActivation.port == origin.port,
            )
        )
        await dbs.commit()


async def is_cert_activated(session: Session, origin: Origin) -> bool:
    async with db.session_factory() as dbs:
        activation = await dbs.scalar(
            select(CertActivation).where(
                CertActivation.session_id == session.id,
                CertActivation.scheme == origin.scheme,
                CertActivation.hostname == origin.hostname,
                CertActivation.port == origin.port,
            )
        )
        return activation is not None


async def list_activations(session: Session) -> list[CertActivation]:
    async with db.session_factory() as dbs:
        result = await dbs.scalars(
            select(CertActivation)
            .where(CertActivation.session_id == session.id)
            .order_by(CertActivation.scheme, CertActivation.hostname, CertActivation.port)
        )
        return list(result)


def _read_pem_file(upload: FileStorage | None, description: str) -> str:
    """
    Read a file input from the login form, returning an empty string
    when the input was left blank. Oversized files are rejected without
    buffering more than the size cap into memory.
    """
    if upload is None or not upload.filename:
        return ""

    data = upload.read(MAX_PEM_SIZE + 1)
    if len(data) > MAX_PEM_SIZE:
        raise CertValidationError(f"The {description} file is too large.")

    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        raise CertValidationError(f"The {description} file is not valid PEM data.")


async def read_keypair_form() -> tuple[str, str]:
    """
    Read and validate the client identity submitted to the login form,
    raising CertValidationError with a user-facing message on failure.

    The identity arrives either as uploaded files or as a combined PEM
    pasted into the text box. The PEM data is stored as-is; when the
    certificate and private key are combined, the returned key is an
    empty string.
    """
    if request.content_length and request.content_length > MAX_PEM_SIZE:
        raise CertValidationError("The submitted form data is too large.")

    form = await request.form
    if not form.get("accept_risk"):
        raise CertValidationError("You must accept the risk acknowledgement.")

    files = await request.files
    cert_pem = _read_pem_file(files.get("cert"), "certificate")
    key_pem = _read_pem_file(files.get("key"), "private key")

    pem_text = form.get("pem_text", "").strip()
    if len(pem_text) > MAX_PEM_SIZE:
        raise CertValidationError("The pasted PEM text is too large.")

    if pem_text:
        if cert_pem or key_pem:
            raise CertValidationError("Provide either uploaded files or pasted PEM text, not both.")
        cert_pem = pem_text
    elif not cert_pem:
        raise CertValidationError("A certificate file or pasted PEM text is required.")

    validate_keypair(cert_pem, key_pem)
    return cert_pem, key_pem


def validate_keypair(cert_pem: str, key_pem: str) -> None:
    """
    Check that the keypair can be loaded by the same ssl machinery that
    will use it for proxied requests.
    """
    for text in (cert_pem, key_pem):
        # Matches both the "BEGIN ENCRYPTED PRIVATE KEY" PEM label and the
        # "Proc-Type: 4,ENCRYPTED" header used by legacy RSA/EC keys.
        if "ENCRYPTED" in text:
            raise CertValidationError("Password-protected private keys are not supported.")

    with tempfile.NamedTemporaryFile("w", suffix=".pem") as certfile:
        certfile.write(cert_pem)
        certfile.flush()
        try:
            ssl.create_default_context().load_verify_locations(cafile=certfile.name)
        except ssl.SSLError as e:
            raise CertValidationError("No PEM-encoded certificate was found.") from e

    try:
        get_ssl_context(cert_pem + "\n" + key_pem if key_pem else cert_pem)
    except ssl.SSLError as e:
        raise CertValidationError(
            "The private key does not match the certificate, or no "
            "PEM-encoded private key was found."
        ) from e
