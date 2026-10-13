from typing import Optional
from pydantic import BaseModel, Field
from datetime import datetime

class Response(BaseModel):
    connection_id: str = Field(max_length = 100)
    response: str = Field(max_length = 10000)

