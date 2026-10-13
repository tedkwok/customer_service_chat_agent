from datetime import datetime


def check_datetime_format(date_string:str, date_format:str):
    try:
        datetime.strptime(date_string, date_format)
        return True
    except ValueError:
        return False

