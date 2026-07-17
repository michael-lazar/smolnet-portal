from datetime import datetime

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
