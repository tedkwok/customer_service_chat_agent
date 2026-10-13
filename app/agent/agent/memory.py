from deepagents.backends import CompositeBackend, StateBackend, StoreBackend, FilesystemBackend
from langchain.tools import tool, ToolRuntime
from langgraph.checkpoint.mysql.aio import AIOMySQLSaver
import json
from app.connection import aiomysql

def get_backend(user_id):

    backend=CompositeBackend(
            default=StateBackend(),
            routes={
            "/memories/": StoreBackend(
                namespace=lambda rt: (user_id,),
            ),
            "/skills/": StoreBackend(
                namespace=lambda rt: (user_id,),
            ),
        },
        )
    
    return backend



async def get_checkpointer():

    pool = await aiomysql.get_aiomysql_pool()
    checkpointer = AIOMySQLSaver(conn=pool)
    await checkpointer.setup()

    return checkpointer


@tool
async def search_user_episodic_memory(query: str, runtime: ToolRuntime) -> str:
    """a tools for searching the episodic memory for the user to better udnerstand their historical behaviour and preference to judge the response ,and if the current response is the continue of the previous response, then refere it."""
  

    configurable = runtime.config.get("configurable", {})
    user_id = configurable.get("user_id", {})

    if not user_id:
        return "user_id is null under configurable. No episodic memory management can be done on this user_id"
    
    checkpointer = await get_checkpointer()

    user_threads = checkpointer.alist(
        config={"configurable": {"thread_id": f"{user_id}:*"}}
    )
    
    relevant_history = []

    async for checkpoint_tuple in user_threads:

        checkpoint_data = checkpoint_tuple.checkpoint or {}
        channel_values = checkpoint_data.get("channel_values", {})
        messages = channel_values.get("messages", [])
        
        for msg in messages:
            
            content = getattr(msg, "content", None) or (msg.get("content") if isinstance(msg, dict) else "")
            msg_type = getattr(msg, "type", None) or (msg.get("type") if isinstance(msg, dict) else "unknown")
            
            if content and query.lower() in content.lower():
                relevant_history.append({"role": msg_type, "text": content})
                
            if len(relevant_history) >= 1000:
                break
                
        if len(relevant_history) >= 1000:
            break

    return json.dumps(relevant_history)
