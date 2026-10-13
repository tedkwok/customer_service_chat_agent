from sqlalchemy.orm import DeclarativeBase, mapped_column, Mapped
from sqlalchemy import String, func
import datetime

class Base(DeclarativeBase):
    pass

class User_Credentials(Base):
    __tablename__ = "user_credentials"

    username: Mapped[str] = mapped_column(String(50), primary_key=True)
    # pbkdf2-sha256 digest in "salt$hex" form (see app/routers/auth.py).
    password_hash: Mapped[str] = mapped_column(String(256))
    customer_id: Mapped[str] = mapped_column(String(20), unique=True)
    createdts: Mapped[datetime.datetime] = mapped_column(server_default=func.now())

    def __repr__(self) -> str:
        return f"User_Credentials(username={self.username!r}, customer_id={self.customer_id!r}, createdts={self.createdts!r})"
