"""
Agent Tools (LangChain @tool)
把"已有且已测过的能力"（知识图谱查询 / 向量检索 / 药物查询）包装成工具，
供 ReAct 自主 Agent 在需要时调用。每个工具的 docstring 即模型判断"何时调用"的依据。

注意：工具返回值一律为 str（create_react_agent 的 ToolNode 需要可序列化文本）。
工具内部对 Neo4j / 向量库的失败做兜底，返回"查询失败/未找到"文本，绝不抛异常打断 ReAct 循环。
"""

import sys
from pathlib import Path

_project_root = Path(__file__).parent.parent.parent.resolve()
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from langchain_core.tools import tool

from src.common.logger import setup_logger

logger = setup_logger(__name__, "tools.log")


def _graph():
    from src.knowledge_graph.graph_queries import GraphQueries
    return GraphQueries()


@tool
def search_knowledge_graph(entity: str) -> str:
    """根据"疾病名"或"症状名"查询知识图谱，返回其 科室/症状/药物/相关疾病 的摘要文本。
    当用户询问某疾病的科室、症状、用药、检查，或某症状可能对应哪些疾病时使用。
    若图谱中查无该实体，返回"未找到"说明，不要据此编造。"""
    try:
        q = _graph()
        info = q.get_disease_info(entity)
        if info:
            syms = q.get_disease_symptoms(entity)
            depts = q.get_disease_departments(entity)
            meds = q.get_disease_medications(entity)
            meds_txt = "、".join(m.get("name", "") for m in meds if m.get("name"))
            parts = [f"疾病：{info.get('name', '')}"]
            if info.get("description"):
                parts.append(f"描述：{info['description']}")
            if syms:
                parts.append(f"常见症状：{'、'.join(syms)}")
            if depts:
                parts.append(f"就诊科室：{'、'.join(depts)}")
            if meds_txt:
                parts.append(f"常用药物：{meds_txt}")
            q.close()
            return "；".join(parts)
        diseases = q.get_symptom_diseases(entity)
        q.close()
        if diseases:
            return f"症状「{entity}」可能对应的疾病：{'、'.join(diseases)}"
        return f"未在知识图谱中找到实体「{entity}」"
    except Exception as e:
        logger.warning(f"[tool search_knowledge_graph] {e}")
        return f"查询知识图谱失败：{e}"


@tool
def semantic_search(query: str) -> str:
    """对知识库做语义（向量）检索，返回最相关实体列表（名称/类型/相似度）。
    当用户表述与图谱实体名不一致、需要模糊语义匹配时使用。"""
    try:
        # 进程级共享检索器（启动时已预热）：避免每次工具调用重读索引/重载模型
        from src.vector_store.search import get_shared_retriever
        vr = get_shared_retriever()
        hits = vr.search(query, top_k=5)
        if not hits:
            return "语义检索无相关结果"
        lines = [f"{h.get('name', '')}（{h.get('type', '')}, {h.get('score', 0):.2f}）" for h in hits]
        return "语义检索结果：" + "；".join(lines)
    except Exception as e:
        logger.warning(f"[tool semantic_search] {e}")
        return f"语义检索失败：{e}"


@tool
def get_medication_info(name: str) -> str:
    """查询某药物的 类别/副作用/禁忌，及其与其他药物的相互作用。
    当用户询问某药信息、副作用，或"能否与某药同服/有无相互作用"等问题时使用。"""
    try:
        q = _graph()
        info = q.get_medication_info(name)
        if not info:
            q.close()
            return f"未在知识图谱中找到药物「{name}」"
        parts = [f"药物：{info.get('name', '')}"]
        if info.get("category"):
            parts.append(f"类别：{info['category']}")
        se = info.get("side_effects") or []
        if se:
            parts.append(f"副作用：{'、'.join(se)}")
        ci = info.get("contraindications") or []
        if ci:
            parts.append(f"禁忌：{'、'.join(ci)}")
        inter = q.get_medication_interactions(name)
        q.close()
        itxt = "；".join(f"{i.get('drug', '')}（{i.get('severity', '')}）" for i in inter if i.get("drug"))
        if itxt:
            parts.append(f"相互作用：{itxt}")
        else:
            # 诚实声明：不编造相互作用（医疗安全红线）
            parts.append("相互作用：本系统未内置完整药物相互作用库，联用风险请以药师/权威数据库为准，切勿自行合用")
        return "；".join(parts)
    except Exception as e:
        logger.warning(f"[tool get_medication_info] {e}")
        return f"查询药物信息失败：{e}"


@tool
def natural_language_graph_query(query: str) -> str:
    """用自然语言灵活查询知识图谱（内部自动生成并执行只读 Cypher，即 Text2Cypher）。
    比 search_knowledge_graph 更适合复杂/灵活的查询：多跳关系、条件过滤、聚合列举等
    （如"高血压对应的科室和一线用药分别是什么""哪些疾病可以用阿司匹林治疗"）。
    建议在 query 中带上已知的规范实体名（可先参考 semantic_search 的链接结果）。
    查询在只读事务中执行并有记录数上限；返回结构化图谱记录，无法生成有效查询时返回说明文本。"""
    try:
        from src.knowledge_graph.text2cypher import get_engine
        result = get_engine().run(query)
        return result.get("text") or "图谱查询无结果"
    except Exception as e:
        logger.warning(f"[tool natural_language_graph_query] {e}")
        return f"图谱查询失败：{e}"
