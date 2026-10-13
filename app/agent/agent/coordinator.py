import os

from deepagents import create_deep_agent
from app.agent.agent import memory, prompt, subagent, llm_provider
from app.BaseModel.context_schema import Context_Schema
from app.agent.agent.memory import get_checkpointer, get_backend
from app.agent.agent.copilotkit_middleware import copo_middleware
from app.agent.agent.human_in_the_loop import human_middleware
from app.agent.tools.render_tools import (
    render_product_card,
    render_membership_status,
    render_purchase_summary,
    render_refund_status,
)


memory_path = os.getenv("MEMORY_PATH", "/memories")

async def build_coordinator_agent(user_id, store):

    try:

        checkpointer = await get_checkpointer()
        backend = get_backend(user_id)

        coordinator_agent = create_deep_agent(
                        model = llm_provider.llm,
                        subagents = subagent.subagent,
                        memory=[f"{memory_path}/AGENTS.md", f"{memory_path}/perference.md"],
                        skills=["/skills/"],
                        backend= backend,
                        store=store,
                        checkpointer = checkpointer,
                        middleware=[copo_middleware, human_middleware],
                        system_prompt = prompt.coordinator_prompt,
                        tools = [memory.search_user_episodic_memory,
                                 render_product_card,
                                 render_membership_status,
                                 render_purchase_summary,
                                 render_refund_status],
                        context_schema  = Context_Schema
                )
        return coordinator_agent
    except Exception as e:
        print(f"[Agent]------ Error thrown when initializing the coordinator agent:{str(e)}")
        raise e