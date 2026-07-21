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
MAX_UPLOAD_SIZE = 32 * 1024


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


def _read_upload(upload: FileStorage) -> bytes:
    """
    Read an uploaded file, rejecting anything over the size cap without
    buffering more than the cap into memory.
    """
    data = upload.read(MAX_UPLOAD_SIZE + 1)
    if len(data) > MAX_UPLOAD_SIZE:
        raise CertValidationError("The uploaded file is too large.")
    return data


def _decode_pem(data: bytes, description: str) -> str:
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        raise CertValidationError(f"The {description} file is not valid PEM data.")


async def read_keypair_upload() -> tuple[str, str]:
    """
    Read and validate the uploaded keypair from the login form, raising
    CertValidationError with a user-facing message on failure.

    The uploaded PEM data is stored as-is; when the private key is
    combined with the certificate in a single file, the returned key is
    an empty string.
    """
    if request.content_length and request.content_length > MAX_UPLOAD_SIZE:
        raise CertValidationError("The uploaded file is too large.")

    files = await request.files

    cert_file = files.get("cert")
    if cert_file is None or not cert_file.filename:
        raise CertValidationError("A certificate file is required.")
    cert_data = _read_upload(cert_file)

    key_data = b""
    key_file = files.get("key")
    if key_file is not None and key_file.filename:
        key_data = _read_upload(key_file)

    cert_pem = _decode_pem(cert_data, "certificate")
    key_pem = _decode_pem(key_data, "private key") if key_data else ""

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
            raise CertValidationError(
                "The certificate file does not contain a PEM-encoded certificate."
            ) from e

    try:
        get_ssl_context(cert_pem + "\n" + key_pem if key_pem else cert_pem)
    except ssl.SSLError as e:
        raise CertValidationError(
            "The private key does not match the certificate, or no "
            "PEM-encoded private key was found."
        ) from e
