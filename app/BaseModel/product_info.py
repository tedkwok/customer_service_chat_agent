from sqlalchemy.orm import DeclarativeBase, mapped_column, Mapped
from sqlalchemy import String, func, Float, Integer
import datetime

class Base(DeclarativeBase):
    pass

class Product_Info(Base):
    __tablename__ = "product_info"

    # Length required on MySQL VARCHAR; matches purchase_item_id (String(30)).
    product_id: Mapped[str] = mapped_column(String(30), primary_key = True)
    product_name: Mapped[str] = mapped_column(String(100))
    product_category: Mapped[str] = mapped_column(String(100))
    product_price: Mapped[float] = mapped_column(Float)
    stock_amount: Mapped[int] = mapped_column(Integer)

    def __repr__(self) -> str:
        return f"Product_Info(product_id={self.product_id!r}, product_name={self.product_name!r}, product_category={self.product_category!r}, product_price={self.product_price!r}, stock_amount={self.stock_amount!r})"
