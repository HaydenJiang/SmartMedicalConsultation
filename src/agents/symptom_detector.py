"""
Symptom Detector Agent
Extracts symptoms from user description (with multi-turn history) and assesses severity.
当挂号/用药意图下检测不到任何症状时，触发追问（needs_clarification）。
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
from src.agents.state import AgentState, SeverityLevel, IntentType

logger = setup_logger(__name__, "agents.log")

# 信息不足时的标准追问话术
CLARIFY_PROMPT = (
    "为了准确为您推荐科室 / 给出建议，还需要您补充一些信息：\n"
    "① 不适的**具体部位**；② 症状**持续了多久**；③ 有无**伴随症状**（如发热、恶心、视力变化、疼痛放射等）；"
    "④ 症状的**严重程度**与诱因。\n"
    "您可以直接把上述情况描述给我，我来帮您判断。"
)


class SymptomResult(BaseModel):
    """Symptom detection result"""
    symptoms: list[str] = Field(description="本轮应抽取的症状列表（遵循'以本轮为主、历史仅承接'原则）")
    severity: str = Field(description="Severity level: low/medium/high/emergency")
    is_emergency: bool = Field(description="Whether this is an emergency situation")


SYSTEM_PROMPT = """你是一个专业的症状分析专家。请提取症状，严格遵守下面的原则。

【核心原则：以本轮为主，历史仅用于"承接"——绝不跨话题累加症状】
1. 优先提取【本轮用户输入】中描述的症状。
2. 历史对话**仅在本轮是承接/追问**时参考：本轮本身没有任何新症状、只是"那挂什么科""还要看吗""这种情况严重吗"等指代上文的句子时，才把上一轮的症状继承过来。
3. **一旦本轮提出新的不适或新的就诊诉求（换了话题），就只取本轮症状，绝不把历史里其他不相关的症状累加进来。**

【其他要求】
- 使用标准医学术语。
- 判断整体严重程度，并检测是否为急症。
- 注意：拔牙、洗牙、配镜、体检、开药等是"就诊诉求/操作"，不是症状，不要当作症状提取。

严重程度定义：
- low：轻微，不影响日常生活（偶尔头痛、轻微咳嗽）
- medium：中等，需要关注（持续头痛、发烧、乏力）
- high：严重，需尽快就医（剧烈疼痛、持续高烧、严重乏力）
- emergency：急症，需立即就医（胸痛、呼吸困难、意识模糊、大出血）

急症关键词：胸痛、胸闷、呼吸困难、喘不过气、意识模糊、昏迷、大出血、吐血、剧烈腹痛、突然失明、肢体麻木无力、抽搐、高烧不退(>40°C)

【对比示例（务必区分 A 与 B）】
示例 A（本轮是承接、无新症状 → 继承上一轮）：
历史：用户：我左眼疼，上眼皮肿了 / 助手：…
本轮：那应该挂什么科？
症状：["左眼疼痛", "上眼睑肿胀"]   ← 本轮无新症状，继承上一轮
严重程度：medium；是否急症：false

示例 B（本轮换了话题 → 只取本轮，绝不继承历史）：
历史：用户：我最近头痛、头晕 / 助手：…推荐神经内科…
本轮：我想拔牙，应该挂什么科？
症状：[]   ← 本轮是新的就诊诉求（拔牙非症状），不继承历史的头痛头晕
严重程度：low；是否急症：false

示例 C（本轮有新症状 → 取本轮；仅当确属同一病情延续时才并入上一轮相关症状，不并入无关历史症状）：
历史：用户：我最近总是咳嗽 / 助手：…
本轮：今天又开始发烧、恶心
症状：["咳嗽", "发热", "恶心"]   ← 同一呼吸道病情的延续，可合并；但绝不并入与本次无关的历史症状
严重程度：medium；是否急症：false

请分析下面的对话与本轮输入，按上述原则提取症状。"""


class SymptomDetectorAgent:
    """Symptom Detector Agent"""

    def __init__(self):
        self.llm = get_llm(temperature=0.1)
        # 显式指定 function_calling：langchain-openai 1.x 默认 method="json_schema"，
        # DashScope 兼容接口不支持该 response_format（报 400 要求 messages 含 "json"）
        self.chain = self.llm.with_structured_output(SymptomResult, method="function_calling")
        self.prompt = ChatPromptTemplate.from_messages([
            ("system", SYSTEM_PROMPT),
            ("user", "【对话历史】\n{history}\n\n【本轮用户输入】\n{query}")
        ])

    def __call__(self, state: AgentState) -> dict:
        """Process state and return update"""
        query = state.get("query", "")
        history = state.get("history", [])
        history_text = format_history(history)
        intent = state.get("intent", "")
        logger.info(f"[SymptomDetector] Processing: {query[:50]}... (history turns: {len(history)})")

        try:
            messages = self.prompt.format_messages(history=history_text, query=query)
            result = self.chain.invoke(messages)

            logger.info(f"[SymptomDetector] Found: {result.symptoms}, severity: {result.severity}")

            update = {
                "symptoms": result.symptoms,
                "severity": result.severity,
                "is_emergency": result.is_emergency,
                "messages": [f"[SymptomDetector] Symptoms: {result.symptoms}, Severity: {result.severity}"]
            }

            # 追问仅在「挂号意图 + 欠规格（无症状）」时触发：没症状就无法荐科，必须问。
            # 用药意图无症状是合法的（药名即锚点），不追问——交给 ReAct 知识 Agent 用工具答。
            if intent == IntentType.APPOINTMENT and not result.symptoms:
                update["needs_clarification"] = True
                update["clarification"] = CLARIFY_PROMPT
                logger.info("[SymptomDetector] appointment without symptoms -> needs clarification")

            return update

        except Exception as e:
            logger.error(f"[SymptomDetector] Error: {e}")
            return {
                "symptoms": [],
                "severity": SeverityLevel.MEDIUM,
                "is_emergency": False,
                "messages": [f"[SymptomDetector] Error: {e}"]
            }


# Singleton instance
symptom_detector = SymptomDetectorAgent()


if __name__ == "__main__":
    if sys.platform == "win32":
        sys.stdout.reconfigure(encoding="utf-8")

    print("=" * 60)
    print("SYMptom DETECTOR AGENT TEST")
    print("=" * 60)

    test_cases = [
        {"query": "我最近头痛、头晕，有时候还会恶心", "history": []},
        {"query": "我突然胸痛、呼吸困难", "history": []},
        # 多轮：本轮无症状，但历史里有
        {
            "query": "那应该挂什么科？",
            "history": [
                {"role": "user", "content": "我左眼疼，上眼皮肿了，摸起来硬硬的"},
                {"role": "assistant", "content": "了解到您左眼疼痛、上睑肿胀…"},
            ],
        },
    ]

    for tc in test_cases:
        print(f"\nQuery: {tc['query']}  | history turns: {len(tc['history'])}")
        state = {"query": tc["query"], "history": tc["history"], "intent": IntentType.APPOINTMENT}
        result = symptom_detector(state)
        print(f"  Symptoms: {result['symptoms']}")
        print(f"  Needs clarification: {result.get('needs_clarification', False)}")

    print("\n" + "=" * 60)
    print("[SUCCESS] Symptom detector tests completed!")
