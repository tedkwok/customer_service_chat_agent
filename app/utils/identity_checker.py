from app.connection.mysql import get_user_attribute


def check_user_identity(user_id):
    
    return get_user_attribute(user_id)