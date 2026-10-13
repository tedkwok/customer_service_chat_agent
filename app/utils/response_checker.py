
def check_approval_wording(request:str):

    process_request = request.strip().lower()

    if process_request in ["approve", "approved"]:
        return "approve"

    if process_request in ["reject", "disapprove", "disapproved"]:
        return "reject"
    
    return None
