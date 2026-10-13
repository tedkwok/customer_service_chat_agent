from app.agent.agent import prompt, llm_provider
from app.agent.tools import vector_search
from app.agent.tools.operation import get_customer_history, check_customer_info, register_membership, purchase, refund, get_product_info
from app.agent.tools.agent_tool_stack import get_current_timestamp, analyze_pandas_dataset

knowledge_subagent = {
    "name": "knowledge_agent",
    "description": "Used to search the policy information, product information, customer related policy, rule and principle of the store",
    "system_prompt": prompt.knowledge_agent_prompt,
    "tools": [vector_search.get_document_by_hybrid_search, vector_search.get_document_by_query_expansion],
    "model": llm_provider.llm
}

operation_subagent = {
    "name": "operation_agent",
    "description": "Used to perform the customer current history checking, membership checking, membership registration, purchase and refund request",
    "system_prompt": prompt.operation_agent_prompt,
    "tools": [get_customer_history, check_customer_info, register_membership, get_product_info, purchase, refund, get_current_timestamp, analyze_pandas_dataset],
    "model": llm_provider.llm
    }

subagent = [knowledge_subagent, operation_subagent]
