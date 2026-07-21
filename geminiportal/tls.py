from __future__ import annotations

import asyncio
import logging
import ssl
import subprocess
import tempfile
from datetime import datetime
from functools import lru_cache
from typing import NamedTuple
from weakref import WeakKeyDictionary

from cryptography import x509
from cryptography.hazmat.primitives import hashes
from cryptography.x509.oid import NameOID

_logger = logging.getLogger(__name__)


@lru_cache(maxsize=64)
def get_ssl_context(client_crt: str | None = None) -> ssl.SSLContext:
    """
    Build the SSL context used for proxied requests, loading a TLS client
    certificate when given (as a single PEM string containing both the
    certificate and the private key). The ssl module can't load
    certificates from memory, so the PEM data is written to a temporary
    file.
    """
    context = ssl.create_default_context()
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE

    _install_close_notify_registry(context)

    if client_crt:
        with tempfile.NamedTemporaryFile("w", suffix=".pem") as certfile:
            certfile.write(client_crt)
            certfile.flush()
            context.load_cert_chain(certfile.name)

    return context


async def describe_tls_cert(tls_cert: bytes, inform: str = "DER") -> str:
    """
    Use openssl to print details about the given TLS certificate data.
    """
    proc = await asyncio.create_subprocess_exec(
        *["openssl", "x509", "-inform", inform, "-text"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate(tls_cert)
    return stdout.decode(errors="ignore")


class CertInfo(NamedTuple):
    """
    The interesting X509 fields parsed out of a TLS certificate.
    """

    common_name: str | None
    subject: str
    issuer: str
    not_valid_before: datetime
    not_valid_after: datetime
    fingerprint: str


def parse_tls_cert(tls_cert: bytes) -> CertInfo:
    """
    Parse the X509 fields from the given PEM-encoded TLS certificate data.
    """
    cert = x509.load_pem_x509_certificate(tls_cert)

    common_name = None
    for attribute in cert.subject.get_attributes_for_oid(NameOID.COMMON_NAME):
        common_name = str(attribute.value)
        break

    return CertInfo(
        common_name=common_name,
        subject=cert.subject.rfc4514_string(),
        issuer=cert.issuer.rfc4514_string(),
        not_valid_before=cert.not_valid_before_utc.replace(tzinfo=None),
        not_valid_after=cert.not_valid_after_utc.replace(tzinfo=None),
        fingerprint=cert.fingerprint(hashes.SHA256()).hex().upper(),
    )


# Marks connections whose close_notify arrived before a CloseNotifyState
# was attached, so the signal isn't lost in that window.
_CLOSE_NOTIFY_RECEIVED = object()


def _install_close_notify_registry(context: ssl.SSLContext) -> None:
    """
    The ssl module's message callback is the only way to observe TLS
    alerts, but it's a private debugging hook that can only be registered
    per-context — and contexts are cached and shared between connections.
    Install a single callback that dispatches close_notify alerts to the
    CloseNotifyState attached to the individual connection.
    """
    registry: WeakKeyDictionary = WeakKeyDictionary()

    def msg_callback(connection, direction, v, c, m, data):
        if m == ssl._TLSAlertType.CLOSE_NOTIFY:  # type: ignore  # noqa
            if direction == "read":
                _logger.info("CLOSE_NOTIFY received")
                state = registry.get(connection)
                if isinstance(state, CloseNotifyState):
                    state.received = True
                else:
                    registry[connection] = _CLOSE_NOTIFY_RECEIVED

    context._close_notify_registry = registry  # type: ignore
    context._msg_callback = msg_callback  # type: ignore


class CloseNotifyState:
    """
    Registers whether the TLS close_notify signal was received at the end
    of a connection. Attach to the connection's SSLObject once it has been
    established.
    """

    def __init__(self, ssl_object: ssl.SSLObject):
        registry = ssl_object.context._close_notify_registry  # type: ignore
        # The close_notify may have already arrived if the server hung up
        # right after the handshake completed.
        self.received: bool = registry.get(ssl_object) is _CLOSE_NOTIFY_RECEIVED
        registry[ssl_object] = self

    def __bool__(self) -> bool:
        return self.received
