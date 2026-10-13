import os

from fastapi import FastAPI, HTTPException, Request as FastAPIRequest
import asyncio
from app.BaseModel.request import Request
from app.BaseModel.response import Response
from app.event_bus import request_worker, response_receive, request_submit
from contextlib import asynccontextmanager
from ag_ui.core.types import RunAgentInput
from ag_ui.encoder import EventEncoder
from fastapi.responses import StreamingResponse
from app.event_bus.connection_manager import ConnectionManager
from app.connection.mysql import init_database
from app.routers import auth, account
import asyncio
from datetime import datetime
import multiprocessing

response_distributor_number = int(os.getenv("NUMBER_RESPONSE_DISTRIBUTOR", "8"))
request_receiver_number = int(os.getenv("NUMBER_REQUEST_RECEIVER", "8"))

# asyncio tasks inside this process and await put()/get() on them.
request_receiver_queue_list:list[asyncio.Queue] = [asyncio.Queue() for i in range(request_receiver_number)]
connectionManager = ConnectionManager(response_distributor_number, request_receiver_number, request_receiver_queue_list)


@asynccontextmanager
async def lifespan(app: FastAPI):

    # Business tables (customer_info / product_info / purchase history /
    # user_credentials) are created here because the repo has no migration
    # tooling; create_all only creates tables that are missing.
    init_database()

    request_submit.init_request_receiver_process(request_receiver_queue_list)
    response_receive.init_response_distributor_process(connectionManager)
    request_worker.init_request_worker_process()

    yield 


app = FastAPI(lifespan=lifespan)

app.include_router(auth.router)
app.include_router(account.router)

@app.get("/actuator/health")
async def get_health():
    return {"message":"System is healthy"}


@app.post("/stream/{user_id}")
async def langgraph_agent_endpoint(input_data: RunAgentInput, request: FastAPIRequest, user_id: str):


    connection_id = user_id + datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    accept_header = request.headers.get("accept")

    encoder = EventEncoder(accept = accept_header)

    await connectionManager.connect(connection_id, encoder)

    request_handler = connectionManager.request_submit_connection[connection_id]
    await request_handler.submit_request(input_data, user_id)

    async def consume():

        response_generator = connectionManager.response_receiver_connection[connection_id]
        try:

            async for encoded_response in response_generator.receive_response():
                yield encoded_response

        except Exception as e:


            print(f"Connection with connection_id: {connection_id} throws the following exception:{str(e)}")

        finally:
            await connectionManager.disconnect(connection_id)

    return StreamingResponse(
        consume(),
        media_type = encoder.get_content_type()

    )
