"""Set up an agreed help session through the same consent flow as the UI."""
from hpoint import database, services


def choose_helper(request_id,helper_id):
    request=database.get_request(request_id)
    if request and request["status"]=="in_progress" and request["helper_id"]==helper_id:
        return services.accept_open_request(request_id,helper_id,author_id=request["requester_id"])
    result=services.apply_to_request(request_id,helper_id)
    if result not in ("created","applied"):return result
    token=database.db.execute("SELECT offer_token FROM request_candidates WHERE request_id=? AND candidate_id=?",(request_id,helper_id)).fetchone()["offer_token"]
    return services.accept_open_request(request_id,helper_id,author_id=request["requester_id"],application_token=token)
