"""
General Chat Agent
Handles non-medical queries with friendly responses
"""

import sys
from pathlib import Path

_project_root = Path(__file__).parent.parent.parent.resolve()
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from langchain_core.prompts import ChatPromptTemplate

from src.common.llm import get_llm
from src.common.logger import setup_logger
from src.agents.state import AgentState

logger = setup_logger(__name__, "agents.log")


SYSTEM_PROMPT = """你是一个友好的医疗助手。当用户问非医疗问题时，礼貌地回应并引导用户使用医疗功能。

你可以回答的问题类型：
- 看病挂号：描述症状，推荐科室
- 用药建议：药物咨询
- 医学知识：疾病科普

示例回答：
用户：你好
回答：您好！我是智能医疗助手，可以帮您：
1. 根据症状推荐就诊科室
2. 提供用药参考建议
3. 解答医学知识问题

请问有什么可以帮您的吗？

请回答用户的问题。"""


class GeneralChatAgent:
    """General Chat Agent"""

    def __init__(self):
        self.llm = get_llm(temperature=0.5)
        self.prompt = ChatPromptTemplate.from_messages([
            ("system", SYSTEM_PROMPT),
            ("user", "{query}")
        ])

    def __call__(self, state: AgentState) -> dict:
        """Process state and return update"""
        query = state.get("query", "")
        logger.info(f"[GeneralChat] Query: {query[:50]}...")

        try:
            messages = self.prompt.format_messages(query=query)
            response = self.llm.invoke(messages)
            answer = response.content

        except Exception as e:
            logger.error(f"[GeneralChat] Error: {e}")
            answer = """您好！我是智能医疗助手，可以帮您：
1. 根据症状推荐就诊科室
2. 提供用药参考建议
3. 解答医学知识问题

请问有什么可以帮您的吗？"""

        return {
            "final_answer": answer,
            "messages": [f"[GeneralChat] Responded to general query"]
        }


general_chat = GeneralChatAgent()
