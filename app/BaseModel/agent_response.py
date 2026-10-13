from dataclasses import dataclass

@dataclass
class AgentResponse:
    thinking_text:str
    output_text: str
    completion_token: int
    prompt_token: int
    total_token: int