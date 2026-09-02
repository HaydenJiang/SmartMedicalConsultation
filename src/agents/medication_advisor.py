"""
Medication Advisor Agent
针对"有症状的用药咨询"，给出安全、保守的用药指导。

为什么重写：旧实现按"症状→疾病→药物"宽松聚合图谱并**直接列出药物**——会把与症状无关甚至危险的药
（如腹痛→某肿瘤→化疗药 多柔比星/环磷酰胺/利妥昔单抗）当成"用药建议"输出，是严重安全隐患；
且症状词对不上图谱时输出**空答案**。改为：图谱药物仅作参考，由 LLM 按医疗安全红线审慎取舍，
并正面回答用户的实际问题（如"自行用药还是去医院"）。
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
from src.agents.state import AgentState

logger = setup_logger(__name__, "agents.log")


class MedicationAdvice(BaseModel):
    """LLM 安全用药指导结果"""
    advice: str = Field(description="针对用户用药问题的安全指导（2-4 句）：可能的常见原因、能否自行用药、何时必须就医")
    medications: list[str] = Field(description="仅适合该常见症状的常规/OTC 药物通用名（0-3 个）；拿不准或不适合自行用药时返回空列表")


SYSTEM_PROMPT = """你是谨慎的用药指导专家。请根据【症状】【用户问题】给出**安全、保守**的用药指导。
【图谱参考药物】（由"症状→疾病→药物"宽松聚合而来，可能含与本次症状完全无关甚至危险的药物，仅供你判断参考，切勿直接照搬）：{kg_meds}

医疗安全红线：
1. **绝不**推荐与本次症状明显无关或高风险的药物（如化疗药、单克隆抗体、激素、处方降压/降糖药等）来应对普通轻微症状。
2. 仅当确属常见轻微症状时，提及 0-3 个对症的常规/OTC 药物通用名；拿不准就返回空列表并建议就医。
3. 必须正面回答用户的实际问题（如"自行用药还是去医院"）：轻微偶发可短期对症观察；持续、加重或伴危险信号（如呕血、黑便、剧烈腹痛、高热不退）则必须就医。
4. 始终强调"遵医嘱、按说明书"，不给出具体剂量，不下诊断。
只输出结构化结果，不要寒暄。"""


class MedicationAdvisorAgent:
    """Medication Advisor Agent (LLM-based, safety-first)."""

    def __init__(self):
        self.llm = get_llm(temperature=0.1)
        # 显式指定 function_calling：langchain-openai 1.x 默认 method="json_schema"，
        # DashScope 兼容接口不支持该 response_format（报 400 要求 messages 含 "json"）
        self.chain = self.llm.with_structured_output(MedicationAdvice, method="function_calling")
        self.prompt = ChatPromptTemplate.from_messages([
            ("system", SYSTEM_PROMPT),
            ("user", "【症状】{symptoms}\n【用户问题】{query}\n【对话历史】{history}")
        ])

    @staticmethod
    def _kg_meds(symptoms: list[str]) -> list[str]:
        """图谱候选药物（仅作参考，含噪声）"""
        names: list[str] = []
        try:
            from src.knowledge_graph.graph_queries import GraphQueries
            q = GraphQueries()
            diseases: list[str] = []
            for s in symptoms:
                diseases.extend(q.get_symptom_diseases(s))
            for disease in list(dict.fromkeys(diseases))[:3]:
                for med in q.get_disease_medications(disease):
                    if med.get("name"):
                        names.append(med["name"])
            q.close()
        except Exception as e:
            logger.warning(f"[MedicationAdvisor] kg meds failed: {e}")
        return list(dict.fromkeys(names))[:10]

    def __call__(self, state: AgentState) -> dict:
        query = state.get("query", "")
        symptoms = state.get("symptoms", [])
        history = state.get("history", [])
        logger.info(f"[MedicationAdvisor] Query: {query[:50]}..., symptoms={symptoms}")

        kg_meds = self._kg_meds(symptoms)
        advice_text = ""
        med_names: list[str] = []
        try:
            msgs = self.prompt.format_messages(
                kg_meds="、".join(kg_meds) if kg_meds else "（无）",
                symptoms="、".join(symptoms) if symptoms else "（未明确）",
                query=query,
                history=format_history(history),
            )
            res = self.chain.invoke(msgs)
            advice_text = res.advice or ""
            med_names = res.medications or []
            logger.info(f"[MedicationAdvisor] LLM meds={med_names}")
        except Exception as e:
            logger.error(f"[MedicationAdvisor] LLM error: {e}")

        # 兜底：LLM 失败也给安全建议，绝不输出空答案
        if not advice_text:
            advice_text = "该用药问题建议咨询医生或药师，结合个人情况评估后再用药，切勿自行用药。"

        medications = [{"name": n, "usage": "请遵医嘱", "side_effects": []} for n in med_names[:3]]

        return {
            "medications": medications,
            "knowledge_answer": advice_text,   # 用药指导文本，由 answer_fusion 渲染
            "messages": [f"[MedicationAdvisor] advice={len(advice_text)} chars, meds={med_names}"]
        }


medication_advisor = MedicationAdvisorAgent()
