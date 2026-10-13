from typing import Dict
import asyncio
from app.BaseModel.response import Response
from app.event_bus.response_receive import response_receiver_connection
from app.event_bus.request_submit import request_submitor_connection
from collections import Counter


class ConnectionManager:

    def __init__(self, response_distributor_number, request_receiver_number, request_receiver_queue_list):

        self.response_distributor_list = self.form_response_distributor_id(response_distributor_number)
        self.request_receiver_list = self.form_request_receiver_id(request_receiver_number)
        self.request_receiver_queue_list = request_receiver_queue_list

        self.response_distributor_map: Dict[str, str] = {}
        self.request_receiver_map: Dict[str, str] = {}
        self.active_submit_queue: Dict[str, asyncio.Queue] = {}
        self.active_receive_queue: Dict[str, asyncio.Queue] = {}
        self.response_receiver_connection: Dict[str, response_receiver_connection] = {}
        self.request_submit_connection: Dict[str, request_submitor_connection] = {}


    async def connect(self, connection_id:str, encoder):

        self.assign_response_distributor(connection_id)
        self.assign_request_receiver(connection_id)

        response_receive_queue:asyncio.Queue[Response] = asyncio.Queue()
        self.active_receive_queue[connection_id] = response_receive_queue
        self.response_receiver_connection[connection_id] = response_receiver_connection(connection_id, response_receive_queue, encoder)

        receiver_index = int(self.request_receiver_map[connection_id])
        request_submit_queue = self.request_receiver_queue_list[receiver_index]
        self.active_submit_queue[connection_id] = request_submit_queue
        self.request_submit_connection[connection_id] = request_submitor_connection(connection_id, request_submit_queue)



    async def disconnect(self, connection_id:str):

        self.response_distributor_map.pop(connection_id, None)
        self.request_receiver_map.pop(connection_id, None)

        self.active_submit_queue.pop(connection_id, None)
        self.active_receive_queue.pop(connection_id, None)

        self.response_receiver_connection.pop(connection_id, None)
        self.request_submit_connection.pop(connection_id, None)


    def assign_response_distributor(self,connection_id):

        if connection_id in self.response_distributor_map:

            print(f"Connection with connection_id:{connection_id} has been mapped with response_distributor")
            return

        in_use_distributor = set(self.response_distributor_map.values())

        distributor_available = self.response_distributor_list - in_use_distributor

        if distributor_available:

            self.response_distributor_map[connection_id] = distributor_available.pop()

        else:
            distributor_usage = Counter(self.response_distributor_map.values())
            self.response_distributor_map[connection_id] = min(self.response_distributor_list,
                                                               key=lambda distributor_id: distributor_usage.get(distributor_id, 0))


    def assign_request_receiver(self,connection_id):

        if connection_id in self.request_receiver_map:

            print(f"Connection with connection_id:{connection_id} has been mapped with request_receiver")
            return

        in_use_receiver = set(self.request_receiver_map.values())

        receiver_available = self.request_receiver_list - in_use_receiver

        if receiver_available:

            self.request_receiver_map[connection_id] = receiver_available.pop()

        else:
            receiver_usage = Counter(self.request_receiver_map.values())
            self.request_receiver_map[connection_id] = min(self.request_receiver_list,
                                                           key=lambda receiver_id: receiver_usage.get(receiver_id, 0))


    def form_response_distributor_id(self, response_distributor_number):

        return {f"{i}" for i in range(response_distributor_number)}

    def form_request_receiver_id(self, request_receiver_number):

        return {f"{i}" for i in range(request_receiver_number)}
