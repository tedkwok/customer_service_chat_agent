import os

import aiomysql


async def get_aiomysql_pool():

    pool = await aiomysql.create_pool(
        host=os.environ["AIOMYSQL_HOST"],
        port=int(os.getenv("AIOMYSQL_PORT", "3306")),
        user=os.environ["AIOMYSQL_USER"],
        password=os.environ["AIOMYSQL_PASSWORD"],
        db=os.environ["AIOMYSQL_DB"],
        minsize=int(os.getenv("AIOMYSQL_MIN_SIZE", "5")),
        maxsize=int(os.getenv("AIOMYSQL_MAX_SIZE", "10"))
    )

    return pool
