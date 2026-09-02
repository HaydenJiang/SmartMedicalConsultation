"""
Answer Fusion Agent
Combines all agent outputs into a coherent final answer
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


SYSTEM_PROMPT = """你是一个专业的医疗客服。请将以下信息整合成一条连贯、专业的回答。

要求：
1. 语言专业但易懂
2. 结构清晰，可以使用标题和列表
3. 确保免责声明在回答末尾
4. 如果有紧急警告，放在回答开头

用户问题：{query}

意图类型：{intent}

检测到的症状：{symptoms}

推荐科室：{departments}

药物建议：{medications}

医学知识：{knowledge}

就医建议：{advice}

免责声明：{disclaimers}

紧急警告：{warnings}

请整合以上信息，生成最终回答。"""


class AnswerFusionAgent:
    """Answer Fusion Agent"""

    def __init__(self):
        self.llm = get_llm(temperature=0.3)
        self.prompt = ChatPromptTemplate.from_messages([
            ("system", SYSTEM_PROMPT),
            ("user", "请整合信息生成回答")
        ])

    def __call__(self, state: AgentState) -> dict:
        """Process state and return update"""
        logger.info("[AnswerFusion] Fusing answers...")

        query = state.get("query", "")
        intent = state.get("intent", "")
        symptoms = state.get("symptoms", [])
        departments = state.get("departments", [])
        medications = state.get("medications", [])
        knowledge = state.get("knowledge_answer", "")
        advice = state.get("advice", [])
        disclaimers = state.get("disclaimers", [])
        warnings = state.get("warnings", [])
        needs_clarify = state.get("needs_clarification", False)
        clarification = state.get("clarification", "")

        # 正文只放"前端未单独结构化渲染"的散文：
        #   症状/科室/药物 → 前端标签区(chips)；急症警告 → 前端 el-alert；免责声明 → 前端免责块。
        #   故正文不再嵌入这些，避免同一条科室/免责声明在界面出现两次。
        parts = []

        if needs_clarify and clarification:
            # 追问话术没有对应的结构化字段，必须放进正文
            parts.append("❓ " + clarification)
        elif intent == "appointment":
            if not departments:
                # 有症状但仍未命中科室时的兜底引导（科室若有则由前端标签展示）
                parts.append("🏥 科室建议：建议先到**全科/导诊台**初筛，或补充症状细节后我再为您精确推荐。")
                parts.append("")
            if advice:
                parts.append("💡 就医建议：")
                for a in advice:
                    parts.append(f"  - {a}")
        elif intent == "medication":
            if knowledge:
                parts.append(knowledge)
        elif intent == "knowledge":
            if knowledge:
                parts.append(knowledge)
        elif intent == "emergency":
            parts.append("您描述的情况可能较为紧急，请立即就医或拨打 120（详见上方紧急警告）。")

        final_answer = "\n".join(parts).strip()

        logger.info(f"[AnswerFusion] Final answer: {len(final_answer)} chars")

        return {
            "final_answer": final_answer,
            "messages": [f"[AnswerFusion] Generated final answer: {len(final_answer)} chars"]
        }


answer_fusion = AnswerFusionAgent()
