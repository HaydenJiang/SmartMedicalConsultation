"""
药物属性增强（独立 pass · 安全路线）
对 entities.json 里的去重药名，各调 LLM 一次，补 类别 / 常见副作用 / 禁忌，
写回 entities.json，并尽力 MERGE 更新 Neo4j 的 Medication 节点。

设计原则（真实工程 / 安全）：
- 独立 pass，**不重抽全量疾病、不改 schema**——最小爆破半径。
- 幂等：已有 category 的药名跳过（可断点续跑）。
- **不编造**：LLM 不知道的返回空，绝不幻觉副作用/禁忌（医疗安全）。
- Neo4j 不可达时只警告、不中断（entities.json 仍会被增强；Neo4j 起来后重跑本脚本或 build_graph 即可同步）。

用法：
    python scripts/enrich_medications.py            # 增量增强 + 同步 Neo4j
    python scripts/enrich_medications.py --force    # 忽略"已填充"，全部重做
"""

import sys
import json
import argparse
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed

_project_root = Path(__file__).parent.parent.resolve()
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")

from pydantic import BaseModel, Field

from config.paths import DATA_KG_DIR
from config.settings import settings
from src.common.llm import get_llm
from src.common.logger import setup_logger

logger = setup_logger(__name__, "extraction.log")

ENTITIES_FILE = DATA_KG_DIR / "entities.json"
MED_TYPES = {"Drug", "Medication"}          # 兼容历史 type 字符串
BATCH = 20                                  # 每批增量落盘
WORKERS = 4                                 # 并发（控制在常见限流线下）

ENTRICH_PROMPT = """你是药理学专家。给定一个药物或药物类别名称，给出它的：
- category：药理类别（若输入本身就是类别，则填该类别的上一级或同类描述）
- side_effects：常见副作用列表（3-6 条，没有则空列表）
- contraindications：禁忌/慎用列表（没有则空列表）

**只输出你确知的信息；不确定的一律留空，绝不编造**（这是医疗场景，编造副作用/禁忌是严重错误）。
只输出结构化结果，不要寒暄。"""


class MedEnrich(BaseModel):
    category: str = Field(default="", description="药理类别")
    side_effects: list[str] = Field(default_factory=list, description="常见副作用")
    contraindications: list[str] = Field(default_factory=list, description="禁忌/慎用")


def _enrich_one(llm, name: str) -> tuple[str, dict]:
    """单个药名的 LLM 增强；任何失败都返回空，不抛异常。"""
    try:
        chain = llm.with_structured_output(MedEnrich)
        res = chain.invoke(ENTRICH_PROMPT + f"\n\n药物/类别名称：{name}")
        return name, {
            "category": (res.category or "").strip(),
            "side_effects": [str(x).strip() for x in (res.side_effects or []) if str(x).strip()],
            "contraindications": [str(x).strip() for x in (res.contraindications or []) if str(x).strip()],
        }
    except Exception as e:
        logger.warning(f"[ENRICH] LLM failed for '{name}': {e}")
        return name, {"category": "", "side_effects": [], "contraindications": []}


def _neo4j_driver():
    """尝试连接 Neo4j；失败返回 None（不中断）。"""
    try:
        from neo4j import GraphDatabase
        d = GraphDatabase.driver(settings.neo4j_uri, auth=(settings.neo4j_user, settings.neo4j_password))
        d.verify_connectivity()
        return d
    except Exception as e:
        logger.warning(f"[ENRICH] Neo4j 不可达，跳过图同步（entities.json 仍会增强）：{e}")
        return None


def _sync_neo4j(driver, name: str, info: dict):
    try:
        with driver.session() as s:
            s.run(
                "MERGE (n:Medication {name: $name}) "
                "SET n.category = $category, n.side_effects = $side_effects, n.contraindications = $contraindications",
                name=name, **info,
            )
    except Exception as e:
        logger.warning(f"[ENRICH] Neo4j MERGE failed for '{name}': {e}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--force", action="store_true", help="忽略已填充，全部重做")
    args = parser.parse_args()

    with open(ENTITIES_FILE, encoding="utf-8") as f:
        blob = json.load(f)
    entities = blob["entities"]

    # 收集去重药名（跳过已填充，幂等）
    targets = []
    seen = set()
    for e in entities:
        if e.get("type") not in MED_TYPES:
            continue
        name = (e.get("data") or {}).get("name", "").strip()
        if not name or name in seen:
            continue
        seen.add(name)
        if (not args.force) and (e.get("data") or {}).get("category"):
            continue
        targets.append(name)

    print(f"[ENRICH] 待增强药名：{len(targets)}（共去重 {len(seen)}）")
    if not targets:
        print("[ENRICH] 无需增强。")
        return

    llm = get_llm(temperature=0.1)
    driver = _neo4j_driver()
    enrich_map: dict[str, dict] = {}

    # 分批并发增强 + 增量落盘
    for i in range(0, len(targets), BATCH):
        batch = targets[i:i + BATCH]
        with ThreadPoolExecutor(max_workers=WORKERS) as ex:
            futs = [ex.submit(_enrich_one, llm, n) for n in batch]
            for fut in as_completed(futs):
                name, info = fut.result()
                enrich_map[name] = info
                if driver:
                    _sync_neo4j(driver, name, info)
        # 增量写回 entities.json
        for e in entities:
            if e.get("type") in MED_TYPES:
                nm = (e.get("data") or {}).get("name", "").strip()
                if nm in enrich_map:
                    e["data"]["category"] = enrich_map[nm]["category"]
                    e["data"]["side_effects"] = enrich_map[nm]["side_effects"]
                    e["data"]["contraindications"] = enrich_map[nm]["contraindications"]
        with open(ENTITIES_FILE, "w", encoding="utf-8") as f:
            json.dump(blob, f, ensure_ascii=False, indent=2)
        filled = sum(1 for n in batch if enrich_map[n]["category"])
        print(f"[ENRICH] batch {i // BATCH + 1}: +{len(batch)}（本批填充类别 {filled}）")

    if driver:
        driver.close()

    total_filled = sum(1 for n in enrich_map if enrich_map[n]["category"])
    print("=" * 60)
    print(f"[ENRICH] 完成：增强 {len(enrich_map)} 个药名，其中 {total_filled} 个填充了类别")
    print(f"[ENRICH] Neo4j 同步：{'是' if driver else '否（Neo4j 不可达，起来后重跑本脚本即可）'}")
    print("=" * 60)


if __name__ == "__main__":
    main()
