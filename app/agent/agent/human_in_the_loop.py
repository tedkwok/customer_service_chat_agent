from langchain.agents.middleware import HumanInTheLoopMiddleware 
from app.agent.tools.operation import refund



human_middleware = HumanInTheLoopMiddleware(
                    interrupt_on = {
                        "refund":{
                            "allowed_decisions": ["approve", "reject"],
                            "description" : "Once agree with the refund process. You are not allowed to cancel the refund request. Please reply 'agree' or 'disagree' for the refund request execution once you have confirmed the details. "
                        }
                    }
                    
                )