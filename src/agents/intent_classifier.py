"""
Intent Classifier Agent
Classifies user query into intent types: appointment/medication/knowledge/emergency/general
"""

import sys
from pathlib import Path

_project_root = Path(__file__).parent.parent.parent.resolve()
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from langchain_core.prompts import ChatPromptTemplate
from pydantic import BaseModel, Field

from src.common.llm import get_llm
from src.common.logger import setup_logger
from src.common.memory import format_history
from src.agents.state import AgentState, IntentType

logger = setup_logger(__name__, "agents.log")


class IntentResult(BaseModel):
    """Intent classification result"""
    intent: str = Field(description="Intent type: appointment/medication/knowledge/emergency/general")
    confidence: float = Field(description="Confidence score: 0-1")


SYSTEM_PROMPT = """你是一个专业的医疗问诊意图识别专家。请分析用户的问题，判断其意图类型。

意图类型定义：
1. appointment（看病挂号）：用户描述症状，想知道该挂什么科、看什么医生
2. medication（用药建议）：用户询问吃什么药、怎么用药、药物副作用等
3. knowledge（医学知识）：用户咨询疾病定义、病因、预防措施等医学知识
4. emergency（急症）：用户描述紧急症状，如胸痛、呼吸困难、意识模糊、大出血等
5. general（通用对话）：非医疗相关问题，如问候、闲聊等

判断规则：
- 如果包含"挂什么科"、"看什么医生"、"去哪里看病"等，判断为 appointment
- 如果包含"吃什么药"、"用什么药"、"药物副作用"等，判断为 medication
- 如果包含"什么是"、"为什么会"、"如何预防"等，判断为 knowledge
- 如果包含"胸痛"、"呼吸困难"、"昏迷"、"大出血"等急症关键词，判断为 emergency
- 其他非医疗问题判断为 general

Few-shot 示例：
用户：我最近头痛、头晕，应该挂什么科？
意图：appointment，置信度：0.95

用户：高血压吃什么药好？
意图：medication，置信度：0.90

用户：什么是高血压？为什么会得高血压？
意图：knowledge，置信度：0.92

用户：我突然胸痛、呼吸困难，怎么办？
意图：emergency，置信度：0.98

用户：你好，今天天气怎么样？
意图：general，置信度：0.99

用户：我最近总是头晕，想去医院看看
意图：appointment，置信度：0.88

多轮示例：
历史：助手：为了推荐科室，请补充您的症状… / 用户：就是头疼
→ 结合历史，本轮是在补充挂号所需症状，意图仍为 appointment。

请结合【对话历史】与【本轮用户输入】，返回意图类型和置信度。"""


class IntentClassifierAgent:
    """Intent Classifier Agent"""

    def __init__(self):
        self.llm = get_llm(temperature=0.1)
        # 显式指定 function_calling：langchain-openai 1.x 默认 method="json_schema"，
        # DashScope 兼容接口不支持该 response_format（报 400 要求 messages 含 "json"）
        self.chain = self.llm.with_structured_output(IntentResult, method="function_calling")
        self.prompt = ChatPromptTemplate.from_messages([
            ("system", SYSTEM_PROMPT),
            ("user", "【对话历史】\n{history}\n\n【本轮用户输入】\n{query}")
        ])

    def __call__(self, state: AgentState) -> dict:
        """Process state and return update"""
        query = state.get("query", "")
        history_text = format_history(state.get("history", []))
        logger.info(f"[IntentClassifier] Processing: {query[:50]}...")

        try:
            messages = self.prompt.format_messages(history=history_text, query=query)
            result = self.chain.invoke(messages)

            logger.info(f"[IntentClassifier] Result: {result.intent} ({result.confidence:.2f})")

            return {
                "intent": result.intent,
                "intent_confidence": result.confidence,
                "messages": [f"[IntentClassifier] Detected: {result.intent} ({result.confidence:.2f})"]
            }

        except Exception as e:
            logger.error(f"[IntentClassifier] Error: {e}")
            return {
                "intent": IntentType.GENERAL,
                "intent_confidence": 0.5,
                "messages": [f"[IntentClassifier] Error, default to general: {e}"]
            }


# Singleton instance
intent_classifier = IntentClassifierAgent()


if __name__ == "__main__":
    if sys.platform == "win32":
        sys.stdout.reconfigure(encoding="utf-8")

    print("=" * 60)
    print("INTENT CLASSIFIER AGENT TEST")
    print("=" * 60)

    test_queries = [
        "我最近头痛、头晕，应该挂什么科？",
        "高血压吃什么药好？",
        "什么是高血压？",
        "我突然胸痛、呼吸困难，怎么办？",
        "你好"
    ]

    for query in test_queries:
        print(f"\nQuery: {query}")
        state = {"query": query}
        result = intent_classifier(state)
        print(f"  Intent: {result['intent']} (confidence: {result['intent_confidence']:.2f})")

    print("\n" + "=" * 60)
    print("[SUCCESS] Intent classifier tests completed!")
