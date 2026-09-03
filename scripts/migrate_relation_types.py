# -*- coding: utf-8 -*-
"""一次性迁移脚本：历史关系类型命名 → 规范命名（schema.py RelationType）

    BELONG_TO_DEPARTMENT → BELONGS_TO_DEPARTMENT
    TREATED_BY_DRUG      → TREATED_BY_MEDICATION

做两件事（都是幂等的，可安全重复执行）：
1. 归一 data/knowledge_graph/relations.json 中的历史类型名（就地改写，仅动 type 字段）
2. 若 Neo4j 可达，把图中历史类型的关系按规范类型重建（复制属性）后删除旧关系；
   不可达则跳过——下次执行 build 前跑一次本脚本即可。

用法：
    python scripts/migrate_relation_types.py
"""
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from config.settings import settings  # noqa: E402

RENAMES = {
    "BELONG_TO_DEPARTMENT": "BELONGS_TO_DEPARTMENT",
    "TREATED_BY_DRUG": "TREATED_BY_MEDICATION",
}


def migrate_relations_json() -> None:
    """归一 relations.json 中的历史类型名（就地、幂等）。"""
    path = PROJECT_ROOT / "data" / "knowledge_graph" / "relations.json"
    if not path.exists():
        print(f"⏭  {path.name} 不存在，跳过")
        return

    with open(path, "r", encoding="utf-8") as f:
        payload = json.load(f)

    changed = 0
    for rel in payload.get("relations", []):
        old = rel.get("type")
        if old in RENAMES:
            rel["type"] = RENAMES[old]
            changed += 1

    if changed:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        print(f"✅ relations.json：{changed} 条关系类型已归一")
    else:
        print("✅ relations.json：无历史命名，无需修改")


def migrate_neo4j() -> None:
    """把 Neo4j 中的历史类型关系重建为规范类型（幂等）。"""
    try:
        from neo4j import GraphDatabase
        driver = GraphDatabase.driver(
            settings.neo4j_uri,
            auth=(settings.neo4j_user, settings.neo4j_password),
            connection_timeout=5,
        )
        driver.verify_connectivity()
    except Exception as e:
        print(f"⏭  Neo4j 不可达（{type(e).__name__}），跳过图迁移；启动 Neo4j 后重跑本脚本即可")
        return

    with driver.session() as session:
        for old, new in RENAMES.items():
            count = session.run(
                f"MATCH ()-[r:{old}]->() RETURN count(r) AS c"
            ).single()["c"]
            if count == 0:
                print(f"✅ {old}：图中无残留")
                continue
            session.run(f"""
                MATCH (a)-[old:{old}]->(b)
                MERGE (a)-[new:{new}]->(b)
                SET new += properties(old)
                DELETE old
            """)
            print(f"✅ {old} → {new}：迁移 {count} 条关系")

    driver.close()


if __name__ == "__main__":
    print("🔧 关系类型命名迁移（历史名 → 规范名）")
    migrate_relations_json()
    migrate_neo4j()
    print("🏁 完成")
