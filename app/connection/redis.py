import hashlib
import os
from typing import Optional

import jwt
from redis import asyncio as aioredis
from redis.asyncio.cluster import RedisCluster, ClusterNode

redis_host = os.getenv("REDIS_HOST", "redis")
redis_port = int(os.getenv("REDIS_PORT", "6379"))
redis_auth = os.environ["REDIS_AUTH"]
redis_ttl = int(os.getenv("REDIS_TTL", "20"))
secret_key = os.environ["REDIS_SECRET_KEY"]


def build_redis_connection() -> Optional[aioredis.Redis]:
    """Build the redis client from environment configuration.

    REDIS_CLUSTER_MODE=false (default) -> single-node redis.asyncio.Redis, which
    matches the shared standalone redis container in docker-compose.yaml.
    REDIS_CLUSTER_MODE=true           -> redis.asyncio.cluster.RedisCluster for
    the staging cluster (comma separated REDIS_HOST / REDIS_PORT lists).
    """

    if os.getenv("REDIS_CLUSTER_MODE", "false").strip().lower() in ("1", "true", "yes", "on"):
        host_list = redis_host.split(",")
        port_list = str(redis_port).split(",")
        nodes = [ClusterNode(host=host_list[i].strip(), port=int(port_list[i]))
                 for i in range(len(host_list))]
        return RedisCluster(
            startup_nodes=nodes,
            password=redis_auth,
            decode_responses=True,
            socket_timeout=5.0,
            max_connections_per_node=50
        )

    return aioredis.Redis(
        host=redis_host,
        port=redis_port,
        password=redis_auth,
        decode_responses=True,
        socket_timeout=5.0,
        max_connections=50
    )


# All consumers use this client inside async contexts (`async with
# redis_connection.pubsub(...)`), so it must be the asyncio client.
redis_connection = build_redis_connection()


def form_tokenized_string(request, user_id):

    payload = {"user_id": user_id,
               "request_id":request
            }
    return jwt.encode(payload, secret_key, algorithm="HS256")


async def check_idempotency(request, user_id):

    idempotent_key = form_tokenized_string(request, user_id)
    new_key = await redis_connection.set(idempotent_key, "IN_PROGRESS", nx=True, ex=redis_ttl)

    return new_key
