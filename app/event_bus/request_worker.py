import asyncio, contextlib
import os
import json
import multiprocessing

from app.agent.implementation import agent_implementation
from app.connection.redis import redis_connection
from redis.exceptions import LockError
from app.BaseModel.response  import Response

number_request_worker = int(os.getenv("NUMBER_REQUEST_WORKER", "8"))
event_bus_request_queue = os.getenv("EVENT_BUS_REQUEST_QUEUE", "agent_request_queue")
event_bus_response_queue = os.getenv("EVENT_BUS_RESPONSE_QUEUE", "agent_response_queue")
worker_process_list = []

async def consume(worker_id):

    # Regular (non-sharded) pubsub: the request receivers in the web process
    # publish with PUBLISH, so subscribers must use plain SUBSCRIBE.
    async with redis_connection.pubsub() as channel_handler:
        await channel_handler.subscribe(event_bus_request_queue)


        async for request in channel_handler.listen():
            request_lock = None
            try:
                print(f"Request received by responsse worker:{worker_id} with request: {request}")

                if request["type"] == 'message':
                    raw_request = request['data']
                    request_body = raw_request.decode("utf-8") if isinstance(raw_request, bytes) else raw_request

                    request_json = json.loads(request_body)
                    request_connection_id = request_json.get("connection_id")
                    request_user_id = request_json.get("user_id") or request_connection_id
                    request_thread_id = request_json.get("thread_id") or request_user_id
                    request_body = request_json.get("request_body")

                    request_lock = redis_connection.lock(request_connection_id, timeout=10)

                    if await request_lock.acquire(blocking=False):

                        response_generator = agent_implementation(request_user_id, request_thread_id, request_body, worker_id)
                        async with contextlib.aclosing(response_generator) as stream:
                            async for response in stream:
                                # agent_implementation yields AG-UI protocol
                                # events (pydantic models); serialise each one
                                # into its own Response for the SSE pipeline.
                                response_json_string = response.model_dump_json()
                                response = Response(request_connection_id, response_json_string)
                                response = response.model_dump_json()
                                sent = await redis_connection.publish(event_bus_response_queue,response)

            except Exception as e:

                print(f"[Request_Worker]------Error occur in request_queue.get() with error: {str(e)}", flush=True)

            finally:

                if request_lock is not None:
                    try:
                        await request_lock.release()
                        print("Lock released")
                    except LockError:
                        print("Lock was already lost or released")


def run_request_worker(worker_id):
    # multiprocessing.Process needs a synchronous target; consume() is a
    # coroutine, so drive it with its own event loop inside the child process.
    asyncio.run(consume(worker_id))


def init_request_worker_process():

    print(f"Start initialize {number_request_worker} request workers", flush=True)

    for i in range(number_request_worker):
        worker_id = "request_worker"+str(i)
        worker_process = multiprocessing.Process(target = run_request_worker, args = (worker_id,))
        worker_process_list.append(worker_process)
        worker_process.start()

    print(f"Finish initialize {number_request_worker} request workers", flush=True)
