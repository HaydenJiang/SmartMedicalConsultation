"""
Text2Cypher Engine
让 LLM 根据自然语言生成 Cypher 并在知识图谱上执行，为 ReAct 层提供灵活图谱查询能力。
（模式来源：本草通项目 CypherQueryGeneratorAgent，按本项目的工程与安全标准重写。）

安全设计（五层防线）：
- L2 写关键字拒绝：正则拦截 CREATE/MERGE/DELETE/SET/...（GraphQueries.run_readonly_cypher 内）
- L1 只读事务：session(default_access_mode=READ_ACCESS)，驱动层保证写不进去（同上）
- L3 EXPLAIN 校验：执行前语法预检；追加 LIMIT 后校验失败则回退原句重试一次（本模块）
- L4 LIMIT 注入：查询无 LIMIT 时自动追加 LIMIT {max_records}（本模块）
- L5 记录数截断：枚举到 max_records 立即停止（GraphQueries.run_readonly_cypher 内）
- L6 异常兜底 + 审计日志：run() 绝不向外抛异常；每条 Cypher 经 logger.info 留痕
"""

import sys
from functools import lru_cache
from pathlib import Path

_project_root = Path(__file__).parent.parent.parent.resolve()
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from langchain_core.messages import SystemMessage, HumanMessage

from config.settings import settings
from src.common.logger import setup_logger

logger = setup_logger(__name__, "text2cypher.log")


_SYSTEM_PROMPT = """你是医疗知识图谱的查询专家。请根据下面的图谱结构，为用户问题生成一条 Cypher 只读查询。

{schema}

输出要求（严格遵守）：
1. 按如下两段式格式输出：
Cypher:
<cypher语句>
Explanation:
<一句话说明查询意图>
2. 只生成 MATCH / WHERE / WITH / UNWIND / RETURN 的只读查询，绝不允许 CREATE / MERGE / DELETE / SET 等写操作。
3. 查询末尾必须附带 LIMIT（不超过 {max_records}）。
4. 如果问题无法用该图谱结构回答，Cypher: 后输出空内容。
"""


class Text2CypherEngine:
    """自然语言 → Cypher 的 生成/校验/执行/格式化 引擎。

    无可变实例状态，线程安全；经 get_engine() 单例复用。
    """

    def __init__(self):
        from src.common.llm import get_llm
        from src.knowledge_graph.schema import generate_llm_schema_text

        self.llm = get_llm(temperature=0.1)
        self.max_records = settings.text2cypher_max_records
        self.system_prompt = _SYSTEM_PROMPT.format(
            schema=generate_llm_schema_text(),
            max_records=self.max_records,
        )

    # ---------------- Step 1: LLM 生成 ----------------
    def generate_cypher(self, query: str, entity_hints: str = "") -> tuple[str, str]:
        """让 LLM 生成 Cypher 与意图说明；解析失败返回 ("", "")。

        Args:
            query: 用户自然语言问题
            entity_hints: 实体链接给出的规范实体名（可选），提示 LLM 用作精确匹配条件
        """
        hint_line = (
            f"已链接实体（建议在查询中用这些规范名称做精确匹配）：{entity_hints}\n"
            if entity_hints else ""
        )
        messages = [
            SystemMessage(content=self.system_prompt),
            HumanMessage(content=f"{hint_line}用户问题：{query}"),
        ]
        response = self.llm.invoke(messages)
        content = response.content if isinstance(response.content, str) else str(response.content)
        try:
            cypher = content.split("Cypher:")[1].split("Explanation:")[0].strip()
            explanation = content.split("Explanation:")[1].strip()
        except (IndexError, AttributeError):
            logger.warning(f"[Text2Cypher] LLM output unparseable: {content[:300]}")
            return "", ""
        # 剥离可能的 markdown 代码块包裹
        if cypher.startswith("```"):
            cypher = cypher.strip("`")
            if cypher.lower().startswith("cypher"):
                cypher = cypher[6:]
            cypher = cypher.strip()
        return cypher, explanation

    # ---------------- L4: LIMIT 注入 ----------------
    def _ensure_limit(self, cypher: str) -> str:
        """无 LIMIT 的查询自动追加 LIMIT {max_records}。"""
        if "limit" in cypher.lower():
            return cypher
        return f"{cypher.rstrip().rstrip(';')} LIMIT {self.max_records}"

    # ---------------- 结果格式化 ----------------
    @staticmethod
    def format_results(records: list[dict], max_chars: int = 2000) -> str:
        """记录列表 → 紧凑行式文本。

        刻意不做二次 LLM 总结：medical_knowledge 末端的 grounded LLM 会统一合成答案，
        工具层返回原始结构化记录，让 ReAct Agent 看到真实数据、可据此多跳。
        """
        if not records:
            return "图谱查询无结果"
        lines = []
        for i, rec in enumerate(records, 1):
            fields = "；".join(
                f"{k}={v}" for k, v in rec.items() if v not in (None, "", [])
            )
            lines.append(f"{i}. {fields}")
        text = "\n".join(lines)
        if len(text) > max_chars:
            text = text[:max_chars] + f"\n…（已截断，共 {len(records)} 条记录）"
        return text

    # ---------------- 端到端编排 ----------------
    def run(self, query: str, entity_hints: str = "") -> dict:
        """生成 → EXPLAIN 校验(L3) → 只读执行(L1/L2/L5) → 格式化文本。

        绝不抛异常（L6）：失败时返回 ok=False 与说明文本，由上层工具原样转述。

        Returns:
            {"ok": bool, "text": str, "cypher": str, "explanation": str, "records": int}
        """
        from src.knowledge_graph.graph_queries import GraphQueries

        result = {"ok": False, "text": "", "cypher": "", "explanation": "", "records": 0}
        q = GraphQueries()
        try:
            cypher, explanation = self.generate_cypher(query, entity_hints)
            if not cypher:
                result["text"] = "该问题不适合用知识图谱查询（未能生成有效 Cypher）"
                return result
            result["cypher"], result["explanation"] = cypher, explanation
            logger.info(f"[Text2Cypher] AUDIT query={query!r} cypher={cypher!r}")

            # L4 注入 LIMIT；L3 EXPLAIN 预检（注入后不通过则回退原句再试一次）
            candidate = self._ensure_limit(cypher)
            ok, msg = q.check_cypher_syntax(candidate)
            if not ok:
                ok, msg = q.check_cypher_syntax(cypher)
                candidate = cypher
            if not ok:
                logger.warning(f"[Text2Cypher] EXPLAIN failed: {msg} | cypher={candidate!r}")
                result["text"] = f"生成的 Cypher 未通过语法校验（{msg}），已放弃本次查询"
                return result

            records = q.run_readonly_cypher(candidate, max_records=self.max_records)
            result.update(ok=True, records=len(records), text=self.format_results(records))
            return result
        except Exception as e:
            logger.warning(f"[Text2Cypher] run failed: {e}")
            result["text"] = f"图谱查询失败：{e}"
            return result
        finally:
            q.close()


@lru_cache(maxsize=1)
def get_engine() -> Text2CypherEngine:
    """全局单例：system prompt 与 LLM 客户端只构建一次。"""
    return Text2CypherEngine()


# ============================================================
# Main: Self-test（需要 Neo4j 与 LLM API Key）
# ============================================================

if __name__ == "__main__":
    if sys.platform == "win32":
        sys.stdout.reconfigure(encoding="utf-8")

    print("=" * 60)
    print("TEXT2CYPHER ENGINE TEST")
    print("=" * 60)

    engine = get_engine()
    for question in ["高血压应该挂什么科", "高血压有哪些常见症状", "阿司匹林能治疗哪些疾病"]:
        print(f"\nQ: {question}")
        r = engine.run(question)
        print(f"  ok={r['ok']} records={r['records']}")
        print(f"  cypher: {r['cypher']}")
        print(f"  text: {r['text'][:300]}")

    # 安全性验证：LLM 即使生成写语句也必须被拦截（直接测 run_readonly_cypher 的 L2）
    from src.knowledge_graph.graph_queries import GraphQueries
    gq = GraphQueries()
    try:
        gq.run_readonly_cypher("CREATE (n:HackTest {name: 'x'})")
        print("\n[FAIL] 写语句未被拦截！")
    except ValueError as e:
        print(f"\n[OK] 写语句被 L2 拦截: {e}")
    finally:
        gq.close()
