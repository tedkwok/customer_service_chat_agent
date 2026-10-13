import os

from sqlalchemy import create_engine, select, update, insert
from sqlalchemy.orm import Session
from app.utils.circuit_breaker import breaker
from app.BaseModel.customer_history import Customer_Purchase_History
from app.BaseModel.customer_info import Customer_info
from app.BaseModel.product_info import Product_Info
from app.BaseModel.user_credentials import User_Credentials
from datetime import datetime



sql_engine = create_engine(
                os.environ["MYSQL_CONNECTION_URL"],
                pool_size = int(os.getenv("MYSQL_POOL_SIZE", "5")),
                max_overflow = int(os.getenv("MYSQL_MAX_OVERFLOW", "10")),
                pool_pre_ping=True
            )


def init_database():
    """Create any missing tables (the repo has no migration tooling).

    Each BaseModel file defines its own DeclarativeBase, so every model's
    metadata must be created individually. create_all only issues CREATE
    TABLE for tables that do not exist yet.
    """
    from app.BaseModel.message import Base as MessageBase
    from app.BaseModel.customer_history import Base as HistoryBase
    from app.BaseModel.customer_info import Base as CustomerBase
    from app.BaseModel.product_info import Base as ProductBase
    from app.BaseModel.user_credentials import Base as CredentialsBase

    for metadata in (MessageBase.metadata,
                     HistoryBase.metadata,
                     CustomerBase.metadata,
                     ProductBase.metadata,
                     CredentialsBase.metadata):
        metadata.create_all(sql_engine)
    print("Database tables verified (created if missing)", flush=True)


def get_customer_history_from_database(customer_id:str, from_date, to_date):

    stmt = ( select(Customer_Purchase_History.purchase_record_id, 
                  Customer_Purchase_History.purchase_item_name,
                  Customer_Purchase_History.purchase_date,
                  Customer_Purchase_History.purchase_item_category,
                  Customer_Purchase_History.purchase_item_price,
                  Customer_Purchase_History.purchase_item_quantity)
            .where(
                Customer_Purchase_History.customer_id == customer_id,
                Customer_Purchase_History.purchase_date >= from_date,
                Customer_Purchase_History.purchase_date <= to_date
                  )
            )
    with Session(sql_engine) as session:
    
            result = session.execute(stmt)
            return result.all()


def get_customer_info_from_database(customer_id:str):
    """Return the Customer_info entity for the customer, or None if absent.

    Note: returns the ORM entity (not a column tuple) so attribute access
    like customer_info.account_balance works in the agent tools.
    """
    stmt = select(Customer_info).where(Customer_info.customer_id == customer_id)

    with Session(sql_engine) as session:
        return session.scalar(stmt)


def register_membership_from_database(customer_id:str, membership_level_input:str):

    with Session(sql_engine) as session:
        stmt = (update(Customer_info)
            .where(Customer_info.customer_id == customer_id)
            .values(membership_level = membership_level_input))
        session.execute(stmt)
        session.commit()

def get_product_info_from_database(product_name, product_id, product_category):

    condition = []

    if product_name:
        condition.append(Product_Info.product_name == product_name)
    if product_id:
        condition.append(Product_Info.product_id == product_id)
    if product_category:
        condition.append(Product_Info.product_category == product_category)

    stmt = (select(Product_Info.product_id,
                   Product_Info.product_name,
                   Product_Info.product_category,
                   Product_Info.product_price,
                   Product_Info.stock_amount)
                   .where(
                       *condition
                   ))
    
    with Session(sql_engine) as session:

        result = session.execute(stmt)
        return result.all()


def account_balance_deduction(customer_account_balance, quantity, product_price, customer_id):

    customer_account_balance = customer_account_balance - (quantity*product_price)
    stmt = (update(Customer_info)
            .where(Customer_info.customer_id == customer_id)
             .values(account_balance =customer_account_balance) )

    with Session(sql_engine) as session:
        session.execute(stmt)
        session.commit()

def account_balance_topup(customer_id, amount):
    """Credit the customer's account balance (top-up page / POST /api/account/topup)."""

    stmt = (update(Customer_info)
            .where(Customer_info.customer_id == customer_id)
            .values(account_balance = Customer_info.account_balance + amount))

    with Session(sql_engine) as session:
        result = session.execute(stmt)

        if result.rowcount == 0:
            raise ValueError(f"No customer record found for customer_id:{customer_id}")

        session.commit()

    return get_customer_info_from_database(customer_id).account_balance

def stock_deduction(product_id, quantity, in_stock_quantity):

    in_stock_quantity = in_stock_quantity - quantity

    stmt = (update(Product_Info)
            .where(Product_Info.product_id == product_id)
            .values(stock_amount = in_stock_quantity))

    with Session(sql_engine) as session:
        session.execute(stmt)
        session.commit()

def purchase_record_append(customer_id, item_name, item_id, item_category, item_price, item_quantity):

    purchase_record_id_string = customer_id + datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    stmt = (insert(Customer_Purchase_History)
            .values(purchase_record_id=purchase_record_id_string,customer_id= customer_id,
                     purchase_item_name = item_name, 
                     purchase_item_id = item_id,
                     purchase_item_category=item_category,
                     purchase_item_price = item_price,
                     purchase_item_quantity = item_quantity))

    with Session(sql_engine) as session:
        session.execute(stmt)
        session.commit()
