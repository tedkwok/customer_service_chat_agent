from sqlalchemy.orm import DeclarativeBase
from sqlalchemy import String, func
from sqlalchemy.orm import mapped_column
from sqlalchemy.orm import Mapped
import datetime

class Base(DeclarativeBase):
    pass

class Message(Base):
    __tablename__ = "message_history"

    # MySQL requires a length on VARCHAR; unlength-ed String columns fail
    # at CREATE TABLE. (String[N] subscripting also silently drops the
    # length in SQLAlchemy 2.x — it must be called, not subscripted.)
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    jid: Mapped[str] = mapped_column(String(20))
    sid: Mapped[str] = mapped_column(String(20))
    content: Mapped[str] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(100))
    token: Mapped[int] = mapped_column(default=0)
    created_at: Mapped[datetime.datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime.datetime] = mapped_column(server_default=func.now(), onupdate=func.now())

    def __repr__(self) -> str:
        return f"Message(id={self.id!r}, jid={self.jid!r}, sid={self.sid!r}), content={self.content!r}, status={self.status!r}, created_at={self.created_at!r}, updated_at={self.updated_at!r})"
