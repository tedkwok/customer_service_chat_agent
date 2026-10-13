"""Seed demo data so the chat / top-up / membership flows can be exercised.

Inserts:
  - 8 demo products (P001..P008) into product_info
  - 1 demo customer (demo_user, Gold, balance 5000) into customer_info
  - 2 purchase history rows so refund/history questions have data

Idempotent: existing rows are left untouched (products are matched by
product_id; the demo customer by customer_id).

Usage:
    python scripts/seed_demo_data.py --yes
"""

import argparse
import os
import sys
from datetime import datetime, timedelta

# Allow running from a source checkout without installing the package.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from sqlalchemy import select  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from app.BaseModel.customer_history import Customer_Purchase_History  # noqa: E402
from app.BaseModel.customer_info import Customer_info  # noqa: E402
from app.BaseModel.product_info import Product_Info  # noqa: E402
from app.connection.mysql import sql_engine, init_database  # noqa: E402

DEMO_PRODUCTS = [
    # (product_id, product_name, product_category, product_price, stock_amount)
    ("P001", "Aurora Wireless Headphones", "Audio", 1299.0, 45),
    ("P002", "Nimbus Smart Speaker", "Audio", 599.0, 80),
    ("P003", "Zenith 4K Monitor", "Computers", 3299.0, 20),
    ("P004", "Pulse Fitness Watch", "Wearables", 1499.0, 60),
    ("P005", "Lumen Desk Lamp", "Home", 329.0, 120),
    ("P006", "Breeze Air Purifier", "Home", 1899.0, 25),
    ("P007", "Vertex Mechanical Keyboard", "Accessories", 899.0, 70),
    ("P008", "Halo Smartphone Stand", "Accessories", 99.0, 200),
]

DEMO_CUSTOMER_ID = "demo_user"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--yes", action="store_true",
                        help="Actually write to the database (default: dry-run)")
    args = parser.parse_args()

    init_database()

    with Session(sql_engine) as session:
        added_products = 0
        for product_id, name, category, price, stock in DEMO_PRODUCTS:
            exists = session.scalar(select(Product_Info)
                                    .where(Product_Info.product_id == product_id))
            if exists is None:
                session.add(Product_Info(product_id=product_id, product_name=name,
                                         product_category=category,
                                         product_price=price, stock_amount=stock))
                added_products += 1

        added_customer = 0
        customer = session.scalar(select(Customer_info)
                                  .where(Customer_info.customer_id == DEMO_CUSTOMER_ID))
        if customer is None:
            session.add(Customer_info(customer_id=DEMO_CUSTOMER_ID,
                                      membership_level="Gold",
                                      account_balance=5000.0))
            added_customer = 1

        added_history = 0
        for record_id, item_id, item_name, category, price, qty, days_ago in [
            ("demo_rec_001", "P001", "Aurora Wireless Headphones", "Audio", 1299.0, 1, 10),
            ("demo_rec_002", "P005", "Lumen Desk Lamp", "Home", 329.0, 2, 3),
        ]:
            exists = session.scalar(select(Customer_Purchase_History)
                                    .where(Customer_Purchase_History.purchase_record_id == record_id))
            if exists is None:
                session.add(Customer_Purchase_History(
                    purchase_record_id=record_id,
                    customer_id=DEMO_CUSTOMER_ID,
                    purchase_item_name=item_name,
                    purchase_item_id=item_id,
                    purchase_date=datetime.now() - timedelta(days=days_ago),
                    purchase_item_category=category,
                    purchase_item_price=price,
                    purchase_item_quantity=qty))
                added_history += 1

        if not args.yes:
            print(f"[dry-run] would insert {added_products} products, "
                  f"{added_customer} customer, {added_history} history rows. "
                  f"Re-run with --yes to write.")
            session.rollback()
            return

        session.commit()

    print(f"Seeded: {added_products} products, {added_customer} customer, "
          f"{added_history} history rows (existing rows untouched).")


if __name__ == "__main__":
    main()
