import asyncio
import json
import os

from app.connection.redis import redis_connection

event_bus_request_queue = os.getenv("EVENT_BUS_REQUEST_QUEUE", "agent_request_queue")
number_request_receiver = int(os.getenv("NUMBER_REQUEST_RECEIVER", "8"))
request_receiver_task_list = []


def extract_request_text(request):
    """Extract the latest user message text from an AG-UI RunAgentInput.

    The request worker downstream expects the plain user text (it is fed to
    check_approval_wording and the agent as message content), so the raw
    RunAgentInput must be reduced to its newest user message before it is
    published to the event bus.
    """

    messages = getattr(request, "messages", None) or []
    for message in reversed(messages):
        if getattr(message, "role", None) != "user":
            continue
        content = getattr(message, "content", "")
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            parts = [getattr(part, "text", "") for part in content
                     if getattr(part, "type", None) == "text"]
            if parts:
                return "\n".join(parts)

    return str(request)


class request_submitor_connection():

    def __init__(self, connection_id, queue):
        self.connection_id = connection_id
        self.connection_queue = queue

    async def submit_request(self, request, user_id):
        try:
            message = {
                "connection_id": self.connection_id,
                # user_id (path param) and thread_id (RunAgentInput, falls back
                # to user_id) travel with the request so the worker can pin
                # the checkpointer thread and customer identity across turns
                # instead of using the per-request connection_id.
                "user_id": user_id,
                "thread_id": getattr(request, "thread_id", None) or user_id,
                "request_body": extract_request_text(request),
            }
            await self.connection_queue.put(message)
        except Exception as e:
            print(f"Exception throws for request submission for connection with id {self.connection_id} : {str(e)}")


async def request_receiver(id, request_queue):

    while True:
        try:
            request = await request_queue.get()

        except Exception as e:
            print(f"Request Receiver:{id} throws the exception: {str(e)}")
            continue

        if request is None:
            request_queue.task_done()
        else:
            try:
                received = await redis_connection.publish(event_bus_request_queue, json.dumps(request))
                await asyncio.sleep(1)
            except Exception as e:
                print(f"Request Receiver:{id} throws the exception:{str(e)}")


def init_request_receiver_process(request_queue_list):

    print(f"Start initialize {number_request_receiver} request receiver", flush=True)

    for i in range(number_request_receiver):
        worker_id = "request_receiver"+str(i)
        # Receivers run as asyncio tasks in this process so they share the
        # asyncio submit queues created in app/main.py.
        receiver_task = asyncio.create_task(request_receiver(worker_id, request_queue_list[i]))
        request_receiver_task_list.append(receiver_task)

    print(f"Finish initialize {number_request_receiver} request receiver", flush=True)
