"""
Build LlamaFactory (alpaca format) fine-tuning dataset for entity/relation extraction.

核心思路：逆向重建 day02 的「输入 -> 输出」训练对
-----------------------------------------------------
Day02 的抽取模块 (scripts/run_extraction.py) 是这样工作的：
    输入  = 把 processed/diseases.json 里某个疾病的各字段拼成一段文本，喂给大模型
    输出  = 该疾病的实体 + 关系，落盘到 knowledge_graph/entities.json / relations.json

因此可以"逆向重建"训练对，让微调的小模型学会和大模型一样的抽取：
    instruction = 抽取指令（固定，且与 5.2 节推理提示词一致）
    input       = 与 day02 完全一致的拼接文本
    output      = 该疾病在知识图谱中的实体 + 关系（结构化 JSON 字符串）

质量把关（grounding 过滤）
--------------------------
真实爬取文本含噪声，个别样本的金标实体几乎不出现在输入里（等于教模型"凭空编"）。
所以对每条样本计算"实体接地率"= 输出实体中能在输入文本里找到的比例，
低于 --min-grounding 的样本丢弃。这与本节"数据质量 > 数量"的要点一致。

Usage
-----
    python scripts/build_finetune_dataset.py
    python scripts/build_finetune_dataset.py --min-grounding 0.3      # 放宽，样本更多
    python scripts/build_finetune_dataset.py --out data/finetune/ft_extract.json
"""

import sys
import json
import argparse
from pathlib import Path
from collections import defaultdict

# Ensure project root is in sys.path
PROJECT_ROOT = Path(__file__).parent.parent.resolve()
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# Fix Windows console encoding
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")

from config.paths import DATA_PROCESSED_DIR, DATA_KG_DIR, DATA_DIR
from src.knowledge_graph.schema import NodeType, RelationType

# ============================================================
# Constants
# ============================================================

INPUT_FILE = DATA_PROCESSED_DIR / "diseases.json"
ENTITIES_FILE = DATA_KG_DIR / "entities.json"
RELATIONS_FILE = DATA_KG_DIR / "relations.json"
DEFAULT_OUT = DATA_DIR / "finetune" / "ft_extract.json"

# 与 notebook 5.2 节推理时的 SystemMessage 保持一致（训练/推理提示词对齐）
INSTRUCTION = "请从以下文本中抽取知识图谱结构，以 JSON 输出实体(含类型)与关系。"

# 关系类型 -> (头实体字段, 尾实体字段, 尾实体节点类型)
# 字段名与 knowledge_graph/relations.json 中 data 的键一一对应
RELATION_SCHEMA = {
    RelationType.HAS_SYMPTOM.value: ("disease_name", "symptom_name", NodeType.SYMPTOM.value),
    RelationType.TREATED_BY_MEDICATION.value: ("disease_name", "drug_name", NodeType.MEDICATION.value),
    RelationType.BELONGS_TO_DEPARTMENT.value: ("disease_name", "department_name", NodeType.DEPARTMENT.value),
    RelationType.NEEDS_EXAMINATION.value: ("disease_name", "examination_name", NodeType.EXAMINATION.value),
    RelationType.AFFECTS_BODY_PART.value: ("disease_name", "body_part_name", NodeType.BODY_PART.value),
}


# ============================================================
# Input text reconstruction (mirrors scripts/run_extraction.py)
# ============================================================

def build_input_text(disease: dict, max_treatment_chars: int = 1500) -> str:
    """Reconstruct the exact text that day02 fed to the LLM for this disease."""
    parts = [f"疾病名称：{disease.get('name', '')}"]

    if disease.get("description"):
        parts.append(f"疾病描述：{disease['description']}")
    if disease.get("symptoms"):
        parts.append(f"症状：{', '.join(disease['symptoms'])}")
    if disease.get("treatment"):
        treatment = disease["treatment"]
        if len(treatment) > max_treatment_chars:
            treatment = treatment[:max_treatment_chars] + "..."
        parts.append(f"治疗方法：{treatment}")
    if disease.get("department"):
        parts.append(f"就诊科室：{disease['department']}")
    if disease.get("medications"):
        parts.append(f"常用药物：{', '.join(disease['medications'])}")

    return "\n".join(parts)


# ============================================================
# Load knowledge graph, grouped by disease
# ============================================================

def load_kg_by_disease():
    """Return {disease_name: [relation_dict, ...]} from relations.json."""
    with open(RELATIONS_FILE, "r", encoding="utf-8") as f:
        relations = json.load(f)["relations"]

    by_disease = defaultdict(list)
    for rel in relations:
        disease_name = rel["data"].get("disease_name")
        if disease_name:
            by_disease[disease_name].append(rel)
    return by_disease


def dedupe_relations(relations: list) -> list:
    """Drop exact-duplicate (type, head, tail) triples."""
    seen, out = set(), []
    for rel in relations:
        rtype = rel["type"]
        schema = RELATION_SCHEMA.get(rtype)
        if not schema:
            continue
        head_f, tail_f, _ = schema
        key = (rtype, rel["data"].get(head_f), rel["data"].get(tail_f))
        if key in seen or not key[1] or not key[2]:
            continue
        seen.add(key)
        out.append(rel)
    return out


# ============================================================
# Build one alpaca sample for a disease
# ============================================================

def build_answer(disease: dict, relations: list) -> dict:
    """Build {'entities': [...], 'relations': [...]} answer for one disease."""
    name = disease.get("name", "")

    entities = {}  # name -> type, 去重

    def add_entity(ent_name: str, ent_type: str):
        if ent_name and ent_name not in entities:
            entities[ent_name] = ent_type

    add_entity(name, NodeType.DISEASE.value)  # 疾病本身

    out_relations = []
    for rel in relations:
        rtype = rel["type"]
        head_f, tail_f, tail_type = RELATION_SCHEMA[rtype]
        head = rel["data"].get(head_f)
        tail = rel["data"].get(tail_f)
        if not head or not tail:
            continue
        add_entity(head, NodeType.DISEASE.value)
        add_entity(tail, tail_type)
        out_relations.append({"from": head, "to": tail, "type": rtype})

    entity_list = [{"name": n, "type": t} for n, t in entities.items()]
    return {"entities": entity_list, "relations": out_relations}


def grounding_ratio(answer: dict, input_text: str) -> float:
    """输出实体（不含疾病本身）中，能在输入文本里找到的比例。"""
    names = [e["name"] for e in answer["entities"] if e["type"] != NodeType.DISEASE.value]
    if not names:
        return 0.0
    hit = sum(1 for n in names if n and n in input_text)
    return hit / len(names)


# ============================================================
# Main
# ============================================================

def build_dataset(max_input: int, max_output: int, min_grounding: float):
    with open(INPUT_FILE, "r", encoding="utf-8") as f:
        diseases = json.load(f)["diseases"]

    kg_by_disease = load_kg_by_disease()

    dataset = []
    skipped = defaultdict(int)

    for disease in diseases:
        name = disease.get("name", "")
        relations = dedupe_relations(kg_by_disease.get(name, []))
        if not relations:
            skipped["no_relations"] += 1
            continue

        input_text = build_input_text(disease)
        if len(input_text) > max_input:
            skipped["input_too_long"] += 1
            continue

        answer = build_answer(disease, relations)
        output_text = json.dumps(answer, ensure_ascii=False)
        if len(output_text) > max_output:
            skipped["output_too_long"] += 1
            continue

        if grounding_ratio(answer, input_text) < min_grounding:
            skipped["low_grounding"] += 1
            continue

        dataset.append({
            "instruction": INSTRUCTION,
            "input": input_text,
            "output": output_text,
        })

    return dataset, dict(skipped)


def main():
    parser = argparse.ArgumentParser(description="Build alpaca fine-tuning dataset from project KG")
    parser.add_argument("--out", type=str, default=str(DEFAULT_OUT), help="Output JSON path")
    parser.add_argument("--max-input", type=int, default=1200, help="Max input chars (cutoff budget)")
    parser.add_argument("--max-output", type=int, default=1500, help="Max output JSON chars")
    parser.add_argument("--min-grounding", type=float, default=0.5,
                        help="Drop samples whose entity-grounding ratio is below this")
    args = parser.parse_args()

    print("=" * 60)
    print("BUILD FINE-TUNING DATASET (alpaca format)")
    print("=" * 60)

    dataset, skipped = build_dataset(args.max_input, args.max_output, args.min_grounding)

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(dataset, f, ensure_ascii=False, indent=2)

    print(f"\n[OK] 生成 {len(dataset)} 条样本 -> {out_path}")
    print(f"[SKIP] {skipped}")
    if dataset:
        print("\n[SAMPLE 0]")
        print("instruction:", dataset[0]["instruction"])
        print("input:", dataset[0]["input"][:180], "...")
        print("output:", dataset[0]["output"][:260], "...")


if __name__ == "__main__":
    main()
