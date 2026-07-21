from datetime import datetime

from sqlalchemy import ForeignKey, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class Favicon(Base):
    """
    A cached favicon.txt lookup, keyed by the URL that was fetched.
    """

    __tablename__ = "favicons"

    id: Mapped[int] = mapped_column(primary_key=True)
    url: Mapped[str] = mapped_column(unique=True)
    emoji: Mapped[str | None]
    expires_at: Mapped[datetime]


class Session(Base):
    """
    A login session, holding the user's uploaded TLS client certificate.
    """

    __tablename__ = "sessions"

    id: Mapped[int] = mapped_column(primary_key=True)
    token: Mapped[str] = mapped_column(unique=True)
    cert_pem: Mapped[str]
    key_pem: Mapped[str]
    created_at: Mapped[datetime]
    expires_at: Mapped[datetime]

    @property
    def identity_pem(self) -> str:
        """
        The certificate and private key combined into a single PEM file,
        the format accepted by ssl.SSLContext.load_cert_chain().
        """
        if self.key_pem:
            return self.cert_pem + "\n" + self.key_pem
        return self.cert_pem


class CertActivation(Base):
    """
    An origin (scheme + hostname + port) that a session's TLS client
    certificate has been activated for.
    """

    __tablename__ = "cert_activations"
    __table_args__ = (UniqueConstraint("session_id", "scheme", "hostname", "port"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("sessions.id", ondelete="CASCADE"))
    scheme: Mapped[str]
    hostname: Mapped[str]
    port: Mapped[int]
