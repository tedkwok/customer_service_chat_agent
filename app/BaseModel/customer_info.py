from sqlalchemy.orm import DeclarativeBase, mapped_column, Mapped
from sqlalchemy import String, func, Float
import datetime

class Base(DeclarativeBase):
    pass

class Customer_info(Base):
    __tablename__ = "customer_info"

    # Length required on MySQL VARCHAR; matches customer_id elsewhere.
    customer_id: Mapped[str] = mapped_column(String(20), primary_key = True)
    membership_level: Mapped[str] = mapped_column(String(10), server_default = "Basic" )
    createdts: Mapped[datetime.datetime] = mapped_column(server_default=func.now())
    account_balance: Mapped[float] = mapped_column(Float, server_default = "0")

    def __repr__(self) -> str:
        return f"Customer_info(customer_id={self.customer_id!r}, membership_level={self.membership_level!r}, createdts={self.createdts!r}, account_balance={self.account_balance!r})"
