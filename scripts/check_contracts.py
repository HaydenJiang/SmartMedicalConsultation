# -*- coding: utf-8 -*-
"""
契约验收器 —— TDD.md 第 0 章工程规范 R1/R3/R4/R5 的机器化验收
====================================================================
用法：
    python scripts/check_contracts.py            # 全部检查（Neo4j 不可达时 R5 自动跳过）
    python scripts/check_contracts.py --no-db    # 显式跳过 R5
    python scripts/check_contracts.py --r1 --r3  # 只跑指定检查

退出码：0 = 全绿（可有告警）；1 = 存在错误。AI 生成模块后自行运行，全绿才算交付（R7）。
输出用 ASCII 标记（[OK]/[FAIL]/[WARN]/[SKIP]），避免 GBK 终端 emoji 崩溃。
"""

import argparse
import json
import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

OK, FAIL, WARN, SKIP = "[OK]  ", "[FAIL]", "[WARN]", "[SKIP]"
errors: list[str] = []
warnings: list[str] = []


def ok(msg: str):
    print(f"{OK} {msg}")


def fail(msg: str):
    errors.append(msg)
    print(f"{FAIL} {msg}")


def warn(msg: str):
    warnings.append(msg)
    print(f"{WARN} {msg}")


def skip(msg: str):
    print(f"{SKIP} {msg}")


# ============================================================
# R1：名字唯一主人
# ============================================================

# 历史上真实出现过的错误命名（本项目事故档案）——出现即报错，零误报
HISTORICAL_BAD_NAMES = [
    r"\bBELONG_TO_DEPARTMENT\b",      # 正确：BELONGS_TO_DEPARTMENT（本次事故主角）
    r"\bTREATED_BY_DRUG\b",           # 正确：TREATED_BY_MEDICATION（本次事故主角）
    r"\bTREATED_BY\b(?!_MEDICATION)", # 旧讲义名，须带 _MEDICATION 后缀
    r"\bAFFECTS_BODYPART\b",          # 正确：AFFECTS_BODY_PART
    r"\bREQUIRES_EXAMINATION\b",      # 正确：NEEDS_EXAMINATION
    r"\bRECOMMEND_FOOD\b",            # 正确：RECOMMENDS_FOOD
    r"\bAVOID_FOOD\b",                # 代码中不存在（饮食建议统一走 RECOMMENDS_FOOD + recommendation_type）
    r"\bCAUSED_BY\b",                 # 代码中不存在
]

# 合法存放枚举定义的文件
ENUM_OWNER_FILES = {
    Path("src/knowledge_graph/schema.py"),   # NodeType / RelationType
    Path("src/agents/state.py"),             # IntentType
}

# 本身合法包含旧名字的文件（迁移工具/验收器自身）
R1_EXCLUDE_FILES = {
    Path("scripts/migrate_relation_types.py"),
    Path("scripts/check_contracts.py"),
}

SCAN_DIRS = ["src", "scripts", "crawler", "evals"]


def _iter_py_files():
    for d in SCAN_DIRS:
        base = PROJECT_ROOT / d
        if not base.exists():
            continue
        for f in base.rglob("*.py"):
            rel = f.relative_to(PROJECT_ROOT)
            if "__pycache__" in rel.parts or rel in R1_EXCLUDE_FILES:
                continue
            yield f, rel


def check_r1():
    print("\n===== R1 名字唯一主人 =====")

    # 1) 历史错误名扫描（零误报，出现即错）
    bad_hits = []
    for f, rel in _iter_py_files():
        text = f.read_text(encoding="utf-8")
        for pat in HISTORICAL_BAD_NAMES:
            for m in re.finditer(pat, text):
                # 带 "# legacy-alias" 标记的行是合法的历史兼容映射（graph_builder 别名表）
                ls = text.rfind("\n", 0, m.start()) + 1
                le = text.find("\n", m.start())
                if "legacy-alias" in text[ls:le if le != -1 else len(text)]:
                    continue
                line_no = text.count("\n", 0, m.start()) + 1
                bad_hits.append(f"{rel}:{line_no} -> {m.group(0)}")
    if bad_hits:
        for h in bad_hits:
            fail(f"历史错误命名残留：{h}")
        print("       修复：改为从 src/knowledge_graph/schema.py 的枚举导入；"
              "数据层问题执行 clear+build（R5）")
    else:
        ok("历史错误命名扫描：无残留")

    # 2) 枚举同名冲突检查：契约文件之外的 Enum 类不得与契约枚举同名
    #    （值域枚举如抽取层的 low/medium/high 只要不撞名即允许存在）
    protected_names = set()
    for owner in ENUM_OWNER_FILES:
        p = PROJECT_ROOT / owner
        if p.exists():
            protected_names |= set(re.findall(
                r"^class\s+(\w+)\s*\(", p.read_text(encoding="utf-8"), re.MULTILINE))
    rogue = []
    for f, rel in _iter_py_files():
        if rel in ENUM_OWNER_FILES:
            continue
        text = f.read_text(encoding="utf-8")
        for m in re.finditer(r"class\s+(\w+)\s*\([^)]*\bEnum\b[^)]*\)", text):
            if m.group(1) not in protected_names:
                continue  # 不撞名的值域枚举 → 放行
            line_no = text.count("\n", 0, m.start()) + 1
            rogue.append(f"{rel}:{line_no} -> class {m.group(1)}")
    if rogue:
        for r in rogue:
            fail(f"枚举与契约枚举同名：{r}（应改名，或并入 schema.py / state.py 后导入）")
    else:
        ok(f"枚举同名检查：无与契约枚举重名（受护名：{sorted(protected_names)}）")

    # 3) 未知 SCREAMING_SNAKE 类型名扫描（告警级，防未来漂移）
    try:
        from src.knowledge_graph.schema import NodeType, RelationType
        from src.agents.state import IntentType
        canonical = (
            {t.value for t in NodeType}
            | {r.value for r in RelationType}
            | {i for i in IntentType.ALL}
        )
    except Exception as e:
        skip(f"无法加载枚举契约（{e}），跳过未知名字扫描")
        return

    # 常见非关系名常量（环境变量名等）白名单
    env_whitelist = {
        "MODEL_BASE_URL", "MODEL_API_KEY", "MODEL_NAME",
        "NEO4J_URI", "NEO4J_USER", "NEO4J_PASSWORD",
        "EMBEDDING_MODEL_PATH", "LOG_LEVEL", "API_PORT",
        "ENABLE_REACT_LAYER", "ENTITY_LINK_THRESHOLD", "ENTITY_LINK_TOP_K",
        "TEXT2CYPHER_ENABLED", "TEXT2CYPHER_MAX_RECORDS",
        "JIMENG_AK", "JIMENG_SK",
        # 可观测 SDK 环境变量（evals/observe.py）
        "LANGFUSE_PUBLIC_KEY", "LANGFUSE_SECRET_KEY", "LANGFUSE_HOST",
        "LANGSMITH_TRACING", "LANGSMITH_API_KEY", "LANGSMITH_PROJECT",
        # 模块再导出清单（__all__ 中的契约对象名）
        "NODE_SCHEMAS", "RELATION_SCHEMAS",
    }
    literal_re = re.compile(r"""['"]([A-Z][A-Z0-9]*(?:_[A-Z0-9]+)+)['"]""")
    unknown = []
    for f, rel in _iter_py_files():
        text = f.read_text(encoding="utf-8")
        for m in literal_re.finditer(text):
            # legacy-alias 标记行是合法兼容映射，跳过
            ls = text.rfind("\n", 0, m.start()) + 1
            le = text.find("\n", m.start())
            if "legacy-alias" in text[ls:le if le != -1 else len(text)]:
                continue
            name = m.group(1)
            if name in canonical or name in env_whitelist:
                continue
            line_no = text.count("\n", 0, m.start()) + 1
            unknown.append(f"{rel}:{line_no} -> {name}")
    if unknown:
        for u in unknown[:10]:
            warn(f"代码中出现枚举之外的 SCREAMING_SNAKE 名字（确认是否为漂移）：{u}")
        if len(unknown) > 10:
            warn(f"...另有 {len(unknown) - 10} 处")
    else:
        ok("未知名字扫描：代码中类型名均出自枚举契约")

    # 4) Cypher 中引用的关系名必须 ∈ 契约枚举（[:REL] 与 [r:REL] 两种写法）
    #    —— Cypher 字符串难以枚举插值（花括号冲突），用扫描代替改写，检出力更强
    allowed_rels = {rt.value for rt in RelationType}
    cypher_rel_re = re.compile(r"\[\w*:([A-Z][A-Z_]+)\]")
    bad_cypher = []
    for f, rel in _iter_py_files():
        text = f.read_text(encoding="utf-8")
        for m in cypher_rel_re.finditer(text):
            ls = text.rfind("\n", 0, m.start()) + 1
            le = text.find("\n", m.start())
            if "legacy-alias" in text[ls:le if le != -1 else len(text)]:
                continue
            name = m.group(1)
            if name not in allowed_rels:
                line_no = text.count("\n", 0, m.start()) + 1
                bad_cypher.append(f"{rel}:{line_no} -> [:{name}]")
    if bad_cypher:
        for b in bad_cypher[:10]:
            fail(f"Cypher 引用了契约之外的关系名：{b}")
    else:
        ok("Cypher 关系名引用：全部出自 RelationType 契约")


# ============================================================
# R3：前后端字段契约
# ============================================================

SSE_WHITELIST = {"message", "node", "label", "facts"}  # SSE 帧载荷字段（非 models.py 定义）


def check_r3():
    print("\n===== R3 前后端字段契约 =====")
    try:
        from src.api.models import (
            ConsultationRequest, ConsultationResponse,
            HealthResponse, StatsResponse,
        )
    except Exception as e:
        fail(f"无法加载 src/api/models.py：{e}")
        return

    response_fields = set(ConsultationResponse.model_fields)
    request_fields = set(ConsultationRequest.model_fields)
    health_fields = set(HealthResponse.model_fields)
    stats_fields = set(StatsResponse.model_fields)
    allowed = response_fields | request_fields | health_fields | stats_fields | SSE_WHITELIST

    # 扫描前端对 data.<字段> 的引用
    frontend_src = PROJECT_ROOT / "frontend" / "src"
    if not frontend_src.exists():
        skip("frontend/src 不存在，跳过前端字段比对")
        return

    ref_re = re.compile(r"\bdata\.([a-zA-Z_][a-zA-Z0-9_]*)\b")
    referenced: dict[str, list[str]] = {}
    files = list(frontend_src.rglob("*.js")) + list(frontend_src.rglob("*.vue"))
    for f in files:
        text = f.read_text(encoding="utf-8")
        for m in ref_re.finditer(text):
            field = m.group(1)
            referenced.setdefault(field, []).append(str(f.relative_to(PROJECT_ROOT)))

    bad_refs = {k: v for k, v in referenced.items() if k not in allowed}
    if bad_refs:
        for field, where in bad_refs.items():
            fail(f"前端引用了 models.py 不存在的字段 data.{field}（{where[0]}）——字段漂移")
    else:
        ok(f"前端 data.* 引用均在契约内（{len(referenced)} 个字段）")

    # 后端提供但前端从未消费的响应字段（timestamp 除外）
    consumed = set(referenced)
    unused = (response_fields - consumed) - {"timestamp"}
    if unused:
        for field in sorted(unused):
            warn(f"ConsultationResponse 字段 {field} 前端从未消费（新增字段忘接？）")
    else:
        ok("ConsultationResponse 全部字段被前端消费")


# ============================================================
# R4：索引与嵌入契约
# ============================================================

EXPECTED_DIM = 1024  # BGE-M3 契约维度（TDD 第 0 章 R4 表）


def check_r4():
    print("\n===== R4 索引与嵌入契约 =====")

    # 1) 模型 config 维度
    model_config = PROJECT_ROOT / "models" / "bge-m3" / "config.json"
    model_dim = None
    if model_config.exists():
        try:
            cfg = json.loads(model_config.read_text(encoding="utf-8"))
            model_dim = cfg.get("hidden_size")
        except Exception as e:
            warn(f"读取 bge-m3/config.json 失败：{e}")
    if model_dim is None:
        skip("models/bge-m3/config.json 不可读，跳过模型维度检查")
    elif model_dim == EXPECTED_DIM:
        ok(f"模型 hidden_size = {model_dim}（符合契约 {EXPECTED_DIM}）")
    else:
        fail(f"模型 hidden_size = {model_dim}，契约要求 {EXPECTED_DIM}")

    # 2) FAISS 索引维度与条目一致性
    index_file = PROJECT_ROOT / "data" / "indexes" / "faiss.index"
    entities_file = PROJECT_ROOT / "data" / "indexes" / "entities.json"
    if not index_file.exists():
        skip("data/indexes/faiss.index 不存在（未构建索引），跳过索引检查")
        return
    try:
        import faiss
    except ImportError:
        skip("当前环境无 faiss，跳过索引维度检查（请在项目 conda 环境中运行）")
        return

    index = faiss.read_index(str(index_file))
    if index.d == EXPECTED_DIM:
        ok(f"FAISS 索引维度 = {index.d}（符合契约 {EXPECTED_DIM}）")
    else:
        fail(f"FAISS 索引维度 = {index.d}，契约要求 {EXPECTED_DIM}"
             f"——修复：python scripts/build_index.py 重建（R5）")

    if model_dim is not None and index.d != model_dim:
        fail(f"索引维度 {index.d} 与模型维度 {model_dim} 不一致——检索会静默失效")

    if entities_file.exists():
        try:
            entities = json.loads(entities_file.read_text(encoding="utf-8"))
            if len(entities) == index.ntotal:
                ok(f"entities.json 条目数 = 索引向量数 = {index.ntotal}")
            else:
                fail(f"entities.json 条目数 {len(entities)} != 索引向量数 {index.ntotal}"
                     f"——修复：python scripts/build_index.py 重建（R5）")
            required_keys = {"name", "type", "data"}
            bad = [i for i, e in enumerate(entities[:200]) if not required_keys.issubset(e)]
            if bad:
                fail(f"entities.json 条目键不完整（示例下标 {bad[:3]}），要求 {required_keys}")
            else:
                ok("entities.json 条目结构 {name, type, data} 完整")
        except Exception as e:
            fail(f"entities.json 解析失败：{e}")
    else:
        skip("data/indexes/entities.json 不存在，跳过条目检查")


# ============================================================
# R5：数据即产物（DB ↔ 枚举一致性）
# ============================================================

# 图谱中允许的辅助节点类型（抽取管线的中间类型，见 schema 实现备注）
AUX_LABELS = {"Treatment", "MedicalConcept"}


def check_r5():
    print("\n===== R5 数据即产物（DB ↔ 枚举）=====")
    try:
        from neo4j import GraphDatabase
        from config.settings import settings
        driver = GraphDatabase.driver(
            settings.neo4j_uri,
            auth=(settings.neo4j_user, settings.neo4j_password),
            connection_timeout=5,
        )
        driver.verify_connectivity()
    except Exception as e:
        skip(f"Neo4j 不可达（{type(e).__name__}），跳过 R5——启动 Neo4j 后重跑")
        return

    try:
        from src.knowledge_graph.schema import NodeType, RelationType
        allowed_labels = {t.value for t in NodeType} | AUX_LABELS
        allowed_rels = {r.value for r in RelationType}

        with driver.session() as s:
            db_labels = {r["label"] for r in s.run("CALL db.labels() YIELD label")}
            db_rels = {r["relationshipType"] for r in
                       s.run("CALL db.relationshipTypes() YIELD relationshipType")}

        # 节点标签：不允许出现枚举之外的类型
        rogue_labels = db_labels - allowed_labels
        if rogue_labels:
            fail(f"DB 出现枚举之外的节点类型：{rogue_labels}"
                 f"——修复：clear+build 重建（R5）")
        else:
            ok(f"DB 节点类型均在契约内：{sorted(db_labels)}")
        missing_labels = {t.value for t in NodeType} - db_labels
        if missing_labels:
            warn(f"DB 缺少节点类型（抽取覆盖问题，非漂移）：{sorted(missing_labels)}")

        # 关系类型：不允许出现枚举之外的类型（本次事故的直接检测项）
        rogue_rels = db_rels - allowed_rels
        if rogue_rels:
            fail(f"DB 出现枚举之外的关系类型：{rogue_rels}"
                 f"——这正是'关系名漂移'事故形态！"
                 f"修复：python -m src.knowledge_graph.graph_builder clear && "
                 f"python -m src.knowledge_graph.graph_builder build（R5）")
        else:
            ok(f"DB 关系类型均在契约内：{sorted(db_rels)}")
        missing_rels = allowed_rels - db_rels
        if missing_rels:
            warn(f"DB 缺少关系类型（抽取覆盖的子集，属正常）：{sorted(missing_rels)}")
    finally:
        driver.close()


# ============================================================
# Main
# ============================================================

def main():
    ap = argparse.ArgumentParser(description="契约验收器（TDD 第 0 章 R1/R3/R4/R5）")
    ap.add_argument("--no-db", action="store_true", help="跳过 R5（不连 Neo4j）")
    ap.add_argument("--r1", action="store_true", help="只跑 R1")
    ap.add_argument("--r3", action="store_true", help="只跑 R3")
    ap.add_argument("--r4", action="store_true", help="只跑 R4")
    ap.add_argument("--r5", action="store_true", help="只跑 R5")
    args = ap.parse_args()

    only = {k for k in ("r1", "r3", "r4", "r5") if getattr(args, k)}
    run_all = not only

    print("=" * 62)
    print("契约验收器 · TDD 第 0 章工程规范（R1/R3/R4/R5）")
    print("=" * 62)

    if run_all or "r1" in only:
        check_r1()
    if run_all or "r3" in only:
        check_r3()
    if run_all or "r4" in only:
        check_r4()
    if (run_all or "r5" in only) and not args.no_db:
        check_r5()
    elif args.no_db:
        print("\n===== R5 数据即产物（DB ↔ 枚举）=====")
        skip("--no-db：跳过 R5")

    print("\n" + "=" * 62)
    if errors:
        print(f"[FAIL] {len(errors)} 个错误，{len(warnings)} 个告警 —— 未通过，请修复后重跑")
        sys.exit(1)
    print(f"[OK] 全部通过（{len(warnings)} 个告警，不阻断）")
    sys.exit(0)


if __name__ == "__main__":
    main()
