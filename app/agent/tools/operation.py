from langchain.tools import tool
from langchain_core.runnables import RunnableConfig
from app.BaseModel.customer_history import Customer_Purchase_History
from app.BaseModel.product_info import Product_Info
from app.agent.utils import check_datetime_format
from app.connection.mysql import get_customer_history_from_database, get_customer_info_from_database, register_membership_from_database, get_product_info_from_database, purchase_record_append, account_balance_deduction, stock_deduction
from datetime import datetime
import os
import json
import smtplib
from email.message import EmailMessage
import pandas as pd

SMTP_SERVER = os.getenv("SMTP_SERVER")
SMTP_PORT = int(os.getenv("SMTP_PORT", "465"))
SENDER_EMAIL = os.getenv("SENDER_EMAIL")
SENDER_PASSWORD = os.getenv("SENDER_PASSWORD")
# Refund requests are emailed to the manager for human approval.
MANAGER_EMAIL = os.getenv("MANAGER_EMAIL") or SENDER_EMAIL


@tool("get_customer_history")
def get_customer_history(from_date:str, to_date:str, config: RunnableConfig):
    """Get the customer purchase history record.

       This tool is to get the following information of the customer purchase record with given time range.
         1. purchased item name
         2. purchase date
         3. purchased quantity of the item
         4. purchased item category
         5. purchased item price

       Args:
         from_date: The start date of the date range of the customer history to be searched in %Y-%m-%d format
         to_date: The end date of the date range of the customer history to be searched in %Y-%m-%d format

       Return Value:
         status: status of execution of the tools, Success implies the successful call. Fail imples exception in the call.
         Exception_content: content of the exception thrown from the tools call if thrown
         data_file_dir: Directory of the csv file containing the customer purchase history in name format customer_history_{customer_id}_{file_createtimestamp}.csv if successfully retrieved. This directory is for the input of tools analyze_pandas_dataset for further analysis of the dataset
    """

    configurable = config.get("configurable", {})
    customer_id = configurable.get("user_id")
    print(f"[Agent]------Start getting the customer history for user:{customer_id}", flush=True)
    
    # Either malformed date must fail the call: with `and`, one bad date
    # bypasses this guard and then raises inside strptime below.
    if not check_datetime_format(from_date, "%Y-%m-%d") or not check_datetime_format(to_date, "%Y-%m-%d"):
        print(f"[Agent]------Wrong date format inserted into the tools call: get_customer_history", flush=True)
        return ["Fail", f"Wrong date format:{str(from_date)} or {str(to_date)} not in %Y-%m-%d format", ""]

    from_date = datetime.strptime(from_date, "%Y-%m-%d")
    to_date = datetime.strptime(to_date, "%Y-%m-%d")
    try:
        customer_history_data = get_customer_history_from_database(customer_id=customer_id,
                                                 from_date=from_date,
                                                 to_date = to_date)
        
        customer_history_data = [
            {col.name: getattr(record, col.name) for col in Customer_Purchase_History.__table__.columns}
            for record in customer_history_data
            ]

        data_file_dir = f"customer_history_{str(customer_id)}_{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}.csv"
        pd.DataFrame(customer_history_data).to_csv(data_file_dir, index=False)

    except Exception as e:
        print(f"[Agent]------Exception faced when get_customer_history for user:{customer_id} with exception:{str(e)}", flush=True)
        return ["Fail", str(e), ""]

    print(f"[Agent]------Successfully get customer history data for customer:{customer_id}", flush=True)
    return ["Success","", data_file_dir]
    


@tool("check_customer_info")
def check_customer_info(config: RunnableConfig):
    """Check the customer current info

        This tools is to get the customer info.
        1. customer current memebership level
        2. customer account createdts
        3. customer account balance amount

        Args:
          None. The customer_id has been already propagated through system variable

        Return:
          status: status of execution of the tools, Success implies the successful call. Fail imples exception in the call.
          Exception_content: content of the exception thrown from the tools call if thrown
          customer_info: above customer info if successfully retrieved

    """

    configurable = config.get("configurable", {})
    customer_id = configurable.get("user_id")

    try:

        customer_info = get_customer_info_from_database(customer_id)

    except Exception as e:
        print(f"[Agent]------Exception faced when get_customer_info for user:{customer_id} with exception:{str(e)}", flush=True)
        return ["Fail", str(e), ""]

    if customer_info is None:
        print(f"[Agent]------No customer record found for user:{customer_id}", flush=True)
        return ["Fail", f"No customer record found for customer_id:{customer_id}", ""]

    customer_info_json = {
                    "membership_level": customer_info.membership_level,
                    "createdts": customer_info.createdts,
                    "account_balance": str(customer_info.account_balance)
    }

    info_string = json.dumps(customer_info_json, default=str)
    print(f"[Agent]------Successfully get customer history data for customer:{customer_id}", flush=True)
    return ["Success", "", info_string]



@tool("register_membership")
def register_membership(membership_level:str, config: RunnableConfig):
    """Register the membership level for the customer

        This tool is to operate the membership registration after verifying the customer meets the membership requirement using check_customer_info and  get_customer_history.

        Args:
          1. membership_level to be registered for the customer

        Return:
          status: status of execution of the tools, Success implies the successful call. Fail imples exception in the call.
          Exception_content: content of the exception thrown from the tools call if thrown
    
    """

    configurable = config.get("configurable", {})
    customer_id = configurable.get("user_id")
    try:

        register_membership_from_database(customer_id = customer_id, membership_level= membership_level)

    except Exception as e:

        print(f"[Agent]------Error thrown when executing register membership for user:{customer_id}", flush=True)
        return ["Fail", str(e)]
    
    print(f"[Agent]------Successfully register membership for user:{customer_id}", flush=True)

    return ["Success", ""]


@tool("get_product_info")
def get_product_info(product_name=None, product_id = None, product_category=None):
    """Get the product info with or with providing product_name or product_id

        This tools is to get the product info
        1. product_id
        2. product_name
        3. product_category
        4. product_price
        5. stock_amount

        Args:
          1. product_name if provided
          2. product_id if provided
          3. product_category if provided

        If the above args are not provided, then default is to extract all product info
        If only one of the argument is provided, the tool will get product info based on the provided argument


        Return:
          status: status of execution of the tools, Success implies the successful call. Fail imples exception in the call.
          Exception_content: content of the exception thrown from the tools call if thrown
          extracted_info_directory: directory of the csv for agent to import dataset to analyze using analyze_pandas_dataset to 
    
    """
    try:
        product_info_df = get_product_info_from_database(product_id=product_id,
                                           product_name=product_name,
                                           product_category=product_category)

        product_info_df = [
                    {col.name: getattr(record, col.name) for col in Product_Info.__table__.columns}
                    for record in product_info_df
                    ]

        data_file_dir = f"product_info_{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}.csv"
        pd.DataFrame(product_info_df).to_csv(data_file_dir, index=False)

        print(f"[Agent]------Successfully executing get_product_info", flush=True)
        return ["Success", "", data_file_dir]
    
    except Exception as e:
        print(f"[Agent]------Error thrown when executing get_product_info", flush=True)
        return ["Fail", str(e), ""]


@tool("purchase")
def purchase(product_id:str, purchase_quantity:int, config: RunnableConfig):
    """Execute the purchase action of the product

       This tool is to perform the purchase execution for the customer

       Args:
         1. product_id,
         2. purchase_quanatity

       Return:
         status: status of execution of the tools, Success implies the successful call. Fail imples exception in the call.
         Exception_content: content of the exception thrown from the tools call if thrown
       
    """

    configurable = config.get("configurable", {})
    customer_id = configurable.get("user_id")
    try: 
        product_info = get_product_info_from_database(product_id=product_id,product_name=None,product_category=None)

        if not product_info:

            print(f"[Agent]------No such product:{product_id} in database", flush=True)
            return ["Fail", f"database does not have product record with product_id:{product_id}"]
    
        elif product_info[0].stock_amount < int(purchase_quantity):

            print(f"[Agent]------Not enough stock for product:{product_id} in database", flush=True)
            return ["Fail", f"Not enough stock for product with product_id:{product_id}"]

        customer_info = get_customer_info_from_database(customer_id)

        if customer_info is None:
            print(f"[Agent]------No customer record found for user:{customer_id}", flush=True)
            return ["Fail", f"No customer record found for customer_id:{customer_id}"]

        if customer_info.account_balance < float(purchase_quantity)*float(product_info[0].product_price):

            print(f"[Agent]------Not enough account balance for customer:{customer_id}", flush=True)
            return ["Fail", f"Not enough account balance for customer:{customer_id}"]

        stock_deduction(product_id=product_id, quantity = purchase_quantity, in_stock_quantity= product_info[0].stock_amount )
        print(f"[Agent]------Successfully modify stock amount for product with product_id:{product_id}", flush=True)

        account_balance_deduction(customer_account_balance=customer_info.account_balance,
                                  quantity=purchase_quantity,
                                  product_price=product_info[0].product_price,
                                  customer_id=customer_id)
        
        print(f"[Agent]------Successfully modify the account balance for customer:{customer_id}", flush=True)


        purchase_record_append(customer_id=customer_id,
                               item_name = product_info[0].product_name,
                               item_id=product_info[0].product_id,
                               item_category=product_info[0].product_category,
                               item_price=product_info[0].product_price,
                               item_quantity=purchase_quantity)

        print(f"[Agent]------Successfully append the purchase record for customer:{customer_id}", flush=True)
        return ["Success", ""]
        
    except Exception as e:
        print(f"[Agent]------Exception thrown:{str(e)} when executing purchase action for user:{customer_id}", flush=True)
        return ["Fail", str(e)]
    




@tool("refund")
def refund(purchase_id:str, config: RunnableConfig):
    """Execute the refund request to manager

       This tool is to execute the refund request after customer raise the refund request

       Args:
          purchase_id: the id of the transaction the customer want to refund

        Return 
          status: status of execution of the tools, Success implies the successful call. Fail imples exception in the call.
          Exception_content: content of the exception thrown from the tools call if thrown
                 
    """
    configurable = config.get("configurable", {})
    customer_id = configurable.get("user_id")

    try:
        with smtplib.SMTP_SSL(SMTP_SERVER, SMTP_PORT) as server:
            server.login(SENDER_EMAIL, SENDER_PASSWORD)
            print(f"[Agent]------Login successful! Send Emails ...", flush=True)
        
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            email_message = EmailMessage()
            email_message["Subject"] = f"Refund Email"
            email_message["From"] = SENDER_EMAIL
            email_message["To"] = MANAGER_EMAIL
        
            message_content = f"""Dear Sir or Madam,
                                    This is an automated refund request from customer:{customer_id} for the transaction with purchase_id:{purchase_id}.
                                    Please help to follow up for the request. 
                                    Thank you! 
                                  Best,
                                  Automated customer agent
                                """
            email_message.set_content(message_content)
        
            server.send_message(email_message)
            print(f"[Agent]------Successfully send email refund request to manager for the purchase record:{purchase_id}", flush=True)
            return ["Success", ""]
        
    except Exception as e:
        print(f"[Agent]------Exception thrown:{str(e)} when executing refund request action for user:{customer_id}", flush=True)
        return ["Fail", str(e)]
    
