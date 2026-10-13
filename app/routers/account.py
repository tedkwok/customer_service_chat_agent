"""Account endpoints (balance top-up) backed by the customer_info table."""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.connection.mysql import account_balance_topup
from app.routers.auth import get_current_user_payload

router = APIRouter(prefix="/api/account", tags=["account"])


class TopUpRequest(BaseModel):
    amount: float = Field(gt=0, le=1_000_000)


@router.post("/topup")
def topup(body: TopUpRequest, payload: dict = Depends(get_current_user_payload)):
    customer_id = payload["sub"]
    try:
        # account_balance_topup raises ValueError for an unknown customer.
        new_balance = account_balance_topup(customer_id, body.amount)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Top-up failed: {str(e)}")

    return {"customer_id": customer_id,
            "amount": body.amount,
            "new_balance": new_balance}
