from sqlalchemy.orm import DeclarativeBase, mapped_column, Mapped
from sqlalchemy import String, func, Float, Integer
import datetime

class Base(DeclarativeBase):
    pass

class Customer_Purchase_History(Base):
    __tablename__ = "customer_purchase_history"

    # Length required on MySQL VARCHAR. Built as customer_id + timestamp
    # (see purchase_record_append), so 50 chars covers 20 + 19.
    purchase_record_id: Mapped[str] = mapped_column(String(50), primary_key = True)
    customer_id: Mapped[str] = mapped_column(String(20))
    purchase_item_name: Mapped[str] = mapped_column(String(30))
    purchase_item_id: Mapped[str] = mapped_column(String(30))
    purchase_date: Mapped[datetime.datetime] = mapped_column(server_default=func.now())
    purchase_item_category: Mapped[str] = mapped_column(String(30))
    purchase_item_price: Mapped[float] = mapped_column(Float)
    purchase_item_quantity: Mapped[int] = mapped_column(Integer)

    def __repr__(self) -> str:
        return f"Customer_Purchase_History(purchase_record_id={self.purchase_record_id!r}, customer_id={self.customer_id!r}, purchase_item_name={self.purchase_item_name!r}), purchase_date={self.purchase_date!r}, purchase_item_category={self.purchase_item_category!r}, purchase_item_price={self.purchase_item_price!r})"
    