import asyncio
import json
import os

from app.BaseModel.response import Response
from app.utils.augi_parse import agui_obj_parse
from app.connection.redis import redis_connection

number_response_distributor = int(os.getenv("NUMBER_RESPONSE_DISTRIBUTOR", "8"))
event_bus_response_queue = os.getenv("EVENT_BUS_RESPONSE_QUEUE", "agent_response_queue")
distributor_task_list = []

class response_receiver_connection():

    def __init__(self, connection_id, queue, encoder):
        self.connection_id = connection_id
        self.connection_queue = queue
        self.encoder = encoder

    async def receive_response(self):

        while True:

            try:
                response = await self.connection_queue.get()

            except Exception as e:

                print(f"response_receiver_connection with connection_id:{self.connection_id} throws the exception: {str(e)}")
                continue

            if response is None:

                print(f"Response_receiver_connection with connection_id:{self.connection_id} receiver empty response")
                self.connection_queue.task_done()

            else:
                try:
                    response_content = response.response
                    response_obj = agui_obj_parse(response_content)
                    yield self.encoder.encode(response_obj)

                except Exception as e:
                    print(f"response_receiver_connection with connection_id:{self.connection_id} throws the exception: {str(e)}")


async def response_distributor(id, connection_manager):

    async with redis_connection.pubsub() as channel_consumer:

        await channel_consumer.subscribe(event_bus_response_queue)

        try:
            async for message in channel_consumer.listen():

                if message['type'] != 'message':
                    continue

                try:
                    raw_response = message['data']
                    response_body = raw_response.decode("utf-8") if isinstance(raw_response, bytes) else raw_response
                    response = Response.model_validate_json(response_body)
                    response_connection_id = response.connection_id

                    if connection_manager.response_distributor_map.get(response_connection_id) != id:
                        continue

                    connection_response = connection_manager.response_receiver_connection.get(response_connection_id)

                    if connection_response is None:
                        print(f"Response_distributor:{id} skips response for unknown connection_id:{response_connection_id}")
                        continue

                    await connection_response.connection_queue.put(response)

                except Exception as e:
                    print(f"Response_distributor:{id} throws the exception:{str(e)}")

        except Exception as e:
            print(f"Response_distributor raise the following exception:{str(e)}")


def init_response_distributor_process(connection_manager):

    print(f"Start initialize {number_response_distributor} response distributor", flush=True)

    for i in range(number_response_distributor):
        # Distributor ids must match the values stored in
        # ConnectionManager.response_distributor_map ("0".."N-1").
        distributor_id = str(i)
        # Distributors must run in this process: they deliver into the live
        # per-connection asyncio queues held by the ConnectionManager, which
        # are not shareable across process boundaries.
        distributor_task = asyncio.create_task(response_distributor(distributor_id, connection_manager))
        distributor_task_list.append(distributor_task)

    print(f"Finish initialize {number_response_distributor} response distributor", flush=True)
