"""
Department Recommender Agent
两级导诊 + 图谱兜底，推荐就诊科室：
  Tier1 图谱候选（症状→疾病→科室 的宽松聚合）：作为可溯源参考喂给 LLM，含噪声，**不直接采用**。
  Tier2 LLM 取舍（结合 症状 + 图谱候选 + 对话历史 做最终决策）：过滤噪声科室、图谱缺失时据医学常识补正；
        明确就诊诉求（如拔牙→口腔科）无需症状也可直接给出。
  兜底：LLM 返回空时回退 Tier1 图谱候选；两者皆空则置 needs_clarification 追问。
解决"知识图谱症状词表覆盖不足导致推荐为空"的问题（如"左眼疼痛/上睑肿胀"）——由 Tier2 LLM 据医学常识补正。
"""

import sys
from pathlib import Path

_project_root = Path(__file__).parent.parent.parent.resolve()
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from pydantic import BaseModel, Field

from src.common.llm import get_llm
from src.common.logger import setup_logger
from src.common.memory import format_history
from src.agents.state import AgentState

logger = setup_logger(__name__, "agents.log")


class DeptFallback(BaseModel):
    """LLM 兜底导诊结果"""
    departments: list[str] = Field(description="推荐的最合适就诊科室 1-3 个；若信息确实不足则返回空列表")
    reason: str = Field(default="", description="推荐理由（简短）")
    follow_up: str = Field(default="", description="若信息不足，需要向用户追问的具体内容")


DEPT_FALLBACK_PROMPT = """你是资深医院导诊专家。请根据【症状】【本轮输入】【对话历史】推荐最合适的 1-3 个就诊科室。
【图谱参考候选科室】（由"症状→疾病→科室"宽松聚合而来，可能含噪声，仅供取舍参考）：{kg_candidates}

规则：
- 依据症状的解剖部位/系统判断科室（如眼部→眼科；头痛/头晕→神经内科；胸痛→心内科/急诊；腹痛→消化内科；咳嗽发热→呼吸内科；皮疹→皮肤科；拔牙/牙齿/口腔→口腔科）。
- 给出 1-3 个科室，按优先级排序，并简述理由。
- 可参考图谱候选，但**必须过滤掉与本次症状明显不符的**（如单纯头痛不应推荐儿科/感染科，除非确有相关症状）；图谱缺了正确科室时可据医学知识补上。
- 若本轮是明确的就诊诉求（如拔牙、配镜、体检），即使没有"症状"也直接给出对应科室。
- 只有当信息确实太少、无法判断时，departments 才返回空列表，并在 follow_up 写明需要追问的内容（部位、持续时间、伴随症状、诱因等）。
- 只输出结构化结果，不要寒暄。

示例：
- 本轮"我最近头痛、头晕" → departments:["神经内科"]（或 ["神经内科","全科医学科"]）
- 本轮"我想拔牙，挂什么科" → departments:["口腔科"]（明确诉求，无需症状）
- 本轮"我该挂什么科"（无任何症状/诉求）→ departments:[]，follow_up:"请描述具体不适部位、持续时间、伴随症状等"。"""


class DepartmentRecommenderAgent:
    """Department Recommender Agent with 3-tier fallback"""

    def __init__(self):
        self.llm = get_llm(temperature=0.1)
        # 显式指定 function_calling：langchain-openai 1.x 默认 method="json_schema"，
        # DashScope 兼容接口不支持该 response_format（报 400 要求 messages 含 "json"）
        self.fallback_chain = self.llm.with_structured_output(DeptFallback, method="function_calling")

    # ---------- Tier 1: 图谱精确 ----------
    def _tier_graph(self, symptoms: list[str]) -> list[str]:
        depts: list[str] = []
        try:
            from src.knowledge_graph.graph_queries import GraphQueries
            q = GraphQueries()
            for s in symptoms:
                for disease in q.get_symptom_diseases(s)[:3]:
                    depts.extend(q.get_disease_departments(disease))
            q.close()
        except Exception as e:
            logger.warning(f"[DepartmentRecommender] graph tier error: {e}")
        return list(dict.fromkeys(depts))

    # ---------- Tier 2: LLM 导诊（结合症状 + 图谱候选，做最终取舍） ----------
    def _tier_llm(self, symptoms: list[str], query: str, history: list, kg_candidates: list[str]) -> DeptFallback:
        from langchain_core.prompts import ChatPromptTemplate
        prompt = ChatPromptTemplate.from_messages([
            ("system", DEPT_FALLBACK_PROMPT),
            ("user", "【症状】{symptoms}\n【本轮输入】{query}\n【对话历史】{history}")
        ])
        msgs = prompt.format_messages(
            kg_candidates="、".join(kg_candidates) if kg_candidates else "（无）",
            symptoms="、".join(symptoms) if symptoms else "（未明确）",
            query=query,
            history=format_history(history),
        )
        return self.fallback_chain.invoke(msgs)

    def __call__(self, state: AgentState) -> dict:
        symptoms = state.get("symptoms", [])
        query = state.get("query", "")
        history = state.get("history", [])
        logger.info(f"[DepartmentRecommender] Symptoms: {symptoms}")

        # Tier 1：图谱候选（症状→疾病→科室的宽松聚合），用于溯源 + 给 LLM 当参考；含噪声，不直接采用
        kg_depts = self._tier_graph(symptoms) if symptoms else []

        # Tier 2：LLM 导诊做最终取舍——结合症状与图谱候选，过滤噪声（如头痛牵出的儿科/感染科），
        # 也能在图谱缺失时补上正确科室；明确就诊诉求（拔牙→口腔科）无需症状也可直接给出。
        departments: list[str] = []
        follow_up = ""
        try:
            fb = self._tier_llm(symptoms, query, history, kg_candidates=kg_depts)
            departments = (fb.departments or [])[:5]
            follow_up = fb.follow_up or ""
            logger.info(f"[DepartmentRecommender] LLM -> {departments} | reason={fb.reason}")
        except Exception as e:
            logger.error(f"[DepartmentRecommender] LLM error: {e}")

        # 融合：LLM 优先；LLM 为空时回退图谱候选
        if departments:
            source = "llm+graph" if kg_depts else "llm"
        elif kg_depts:
            departments = kg_depts[:5]
            source = "graph"
        else:
            source = "none"

        logger.info(f"[DepartmentRecommender] Recommended: {departments} (source={source}, kg={kg_depts})")

        update = {
            "departments": departments,
            "messages": [f"[DepartmentRecommender] Recommended: {departments} (source={source})"]
        }

        if departments:
            # 已能确定科室 → 取消上游"无症状→追问"的默认追问（如"我想拔牙"→口腔科，无需追问）
            update["needs_clarification"] = False
        elif follow_up:
            # 确实信息不足 → 追问
            update["needs_clarification"] = True
            update["clarification"] = follow_up

        return update


# Singleton instance
department_recommender = DepartmentRecommenderAgent()


if __name__ == "__main__":
    if sys.platform == "win32":
        sys.stdout.reconfigure(encoding="utf-8")

    print("=" * 60)
    print("DEPARTMENT RECOMMENDER AGENT TEST (3-tier)")
    print("=" * 60)

    for symptoms in [["头痛", "头晕"], ["左眼疼痛", "上眼睑肿胀", "上眼睑硬结", "触痛"]]:
        print(f"\nSymptoms: {symptoms}")
        result = department_recommender({"symptoms": symptoms, "query": "挂什么科", "history": []})
        print(f"  -> {result['departments']}")

    print("\n" + "=" * 60)
