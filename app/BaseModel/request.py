from typing import Optional
from pydantic import BaseModel, Field
from datetime import datetime

class Request(BaseModel):
    id: str = Field(max_length = 100)
    sender_id: str
    chat_id: str
    request: str = Field(max_length = 10000)

