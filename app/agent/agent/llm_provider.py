import os
from string import Template
import json

from litellm import Router
from langchain_litellm import ChatLiteLLMRouter

# All chat/embedding traffic goes through the litellm gateway deployed in
# docker-compose.yaml (service "litellm", port 4000). The gateway fronts the
# Z.AI coding-plan models (glm-5.3 / glm-5.2 / glm-5.1) and the vLLM CPU
# embedding server (see litellm_config.yaml).
api_base = os.getenv("LITELLM_API_BASE", "http://litellm:4000")
api_key = os.environ["LITELLM_API_KEY"]
primary_model = os.getenv("LLM_PRIMARY_MODEL", "glm-5.3")
# LLM_MODEL_LIST=glm-5.3|glm-5.2|glm-5.1 -> ["glm-5.3", "glm-5.2", "glm-5.1"]
model_llm_list = [model.strip() for model in os.getenv("LLM_MODEL_LIST", "glm-5.3|glm-5.2|glm-5.1").split("|") if model.strip()]

# Stable alias the whole service requests; the router falls back to the other
# provisioned models when the primary deployment fails or rate-limits.
ROUTER_MODEL_NAME = "customer-service-llm"

model_list = []

# One named deployment per provisioned model so the fallback chain can target
# them individually.
for model in model_llm_list:
    model_list.append({
        "model_name": model,
        "litellm_params": {
            "model": f"openai/{model}",
            "api_key": api_key,
            "custom_llm_provider": "openai",
            "api_base": api_base
        }
    })

# The alias itself resolves to the primary model.
model_list.append({
    "model_name": ROUTER_MODEL_NAME,
    "litellm_params": {
        "model": f"openai/{primary_model}",
        "api_key": api_key,
        "custom_llm_provider": "openai",
        "api_base": api_base
    }
})

litellm_router = Router(model_list=model_list,
                        fallbacks=[{ROUTER_MODEL_NAME: model_llm_list}])

llm = ChatLiteLLMRouter(router=litellm_router,
                        model_name=ROUTER_MODEL_NAME,
                        temperature=0.1)
