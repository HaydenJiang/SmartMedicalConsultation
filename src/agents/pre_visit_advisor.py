"""
Pre-visit Advisor Agent
根据症状与推荐科室，给出简洁、实用且**与症状相关**的就诊前建议。

为什么改：旧实现取"每个症状对应的第一个疾病"的检查项拼建议——该"第一个疾病"几乎是任意的，
会给出与症状无关的检查（如头痛 → 冠状动脉CTA / 踝臂指数）。改为 LLM 依据症状+科室生成、
并显式约束"检查建议必须与症状相关"，LLM 失败时退回确定性通用建议。
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
from src.agents.state import AgentState

logger = setup_logger(__name__, "agents.log")


class PreVisitAdvice(BaseModel):
    """Pre-visit advice result"""
    advice: list[str] = Field(description="3-5 条简洁的就诊前建议（每条一行，不含诊断/用药）")


SYSTEM_PROMPT = """你是资深导诊/就医指导专家。根据患者的【症状】与【推荐科室】，给出 3-5 条简洁、实用的就诊前建议。

要求：
- 通用准备酌情包含：携带医保卡/身份证及既往病历与检查报告；记录症状出现的时间、频率、持续时间。
- 针对症状给出合理的就诊准备与**可能涉及的检查方向**；检查建议必须与该症状合理相关（如腹部不适→建议空腹；头痛/头晕→避免剧烈运动、可能测血压或做神经系统查体），**绝不给出与症状无关的检查**。
- 不给出诊断结论，不给出具体用药与剂量。
- 每条一行、简洁，不要寒暄。"""


class PreVisitAdvisorAgent:
    """Pre-visit Advisor Agent (LLM-generated, symptom-relevant)."""

    def __init__(self):
        self.llm = get_llm(temperature=0.2)
        # 显式指定 function_calling：langchain-openai 1.x 默认 method="json_schema"，
        # DashScope 兼容接口不支持该 response_format（报 400 要求 messages 含 "json"）
        self.chain = self.llm.with_structured_output(PreVisitAdvice, method="function_calling")
        self.prompt = ChatPromptTemplate.from_messages([
            ("system", SYSTEM_PROMPT),
            ("user", "【症状】{symptoms}\n【推荐科室】{departments}")
        ])

    def __call__(self, state: AgentState) -> dict:
        symptoms = state.get("symptoms", [])
        departments = state.get("departments", [])
        logger.info(f"[PreVisitAdvisor] Symptoms: {symptoms}, Departments: {departments}")

        advice: list[str] = []
        try:
            msgs = self.prompt.format_messages(
                symptoms="、".join(symptoms) if symptoms else "（未明确）",
                departments="、".join(departments) if departments else "（未明确）",
            )
            advice = self.chain.invoke(msgs).advice or []
        except Exception as e:
            logger.warning(f"[PreVisitAdvisor] LLM advice failed: {e}")
            advice = []

        # 确定性兜底（LLM 失败时仍给出安全的通用建议）
        if not advice:
            advice = [
                "就诊前准备好医保卡、身份证",
                "记录症状出现的时间、频率、持续时间",
                "如有既往病历、检查报告，请一并携带",
            ]
            if departments:
                advice.append(f"建议挂号科室：{'、'.join(departments[:3])}")

        return {
            "advice": advice,
            "messages": [f"[PreVisitAdvisor] Generated {len(advice)} advice items"]
        }


pre_visit_advisor = PreVisitAdvisorAgent()
