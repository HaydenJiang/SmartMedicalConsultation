"""
Neo4j Knowledge Graph Schema Definitions
Defines 8 node types and 12 relation types for the medical knowledge graph.
"""

from enum import Enum
from dataclasses import dataclass, field
from typing import Optional


# ============================================================
# Node Types (8 types)
# ============================================================

class NodeType(str, Enum):
    """Neo4j node labels"""
    DISEASE = "Disease"
    SYMPTOM = "Symptom"
    MEDICATION = "Medication"
    DEPARTMENT = "Department"
    BODY_PART = "BodyPart"
    EXAMINATION = "Examination"
    FOOD = "Food"
    PRECAUTION = "Precaution"


@dataclass
class NodeSchema:
    """Schema definition for a node type"""
    label: str
    properties: dict[str, str]  # property_name: data_type
    unique_constraint: Optional[str] = None  # property for unique constraint
    indexes: list[str] = field(default_factory=list)  # properties to index
    description: str = ""


# Node schemas with properties and constraints
NODE_SCHEMAS: dict[NodeType, NodeSchema] = {
    NodeType.DISEASE: NodeSchema(
        label="Disease",
        properties={
            "name": "string",
            "description": "string",
            "icd_code": "string",
            "aliases": "list",
            "created_at": "datetime",
            "updated_at": "datetime",
        },
        unique_constraint="name",
        indexes=["name", "icd_code"],
        description="疾病节点，如：高血压、冠心病"
    ),
    NodeType.SYMPTOM: NodeSchema(
        label="Symptom",
        properties={
            "name": "string",
            "description": "string",
            "severity": "string",  # low/medium/high
            "duration": "string",
        },
        unique_constraint="name",
        indexes=["name", "severity"],
        description="症状节点，如：头痛、发热"
    ),
    NodeType.MEDICATION: NodeSchema(
        label="Medication",
        properties={
            "name": "string",
            "category": "string",
            "side_effects": "list",
            "contraindications": "list",
            "dosage": "string",
        },
        unique_constraint="name",
        indexes=["name", "category"],
        description="药物节点，如：氨氯地平、阿司匹林"
    ),
    NodeType.DEPARTMENT: NodeSchema(
        label="Department",
        properties={
            "name": "string",
            "description": "string",
            "floor": "string",
            "parent_department": "string",
        },
        unique_constraint="name",
        indexes=["name"],
        description="科室节点，如：心血管内科、骨科"
    ),
    NodeType.BODY_PART: NodeSchema(
        label="BodyPart",
        properties={
            "name": "string",
            "description": "string",
            "system": "string",  # 循环系统、消化系统等
        },
        unique_constraint="name",
        indexes=["name", "system"],
        description="身体部位节点，如：心脏、肝脏"
    ),
    NodeType.EXAMINATION: NodeSchema(
        label="Examination",
        properties={
            "name": "string",
            "type": "string",  # 实验室检查、影像学检查等
            "purpose": "string",
            "preparation": "string",
        },
        unique_constraint="name",
        indexes=["name", "type"],
        description="检查项目节点，如：血压测量、心电图"
    ),
    NodeType.FOOD: NodeSchema(
        label="Food",
        properties={
            "name": "string",
            "type": "string",  # 推荐/禁忌
            "description": "string",
        },
        unique_constraint="name",
        indexes=["name", "type"],
        description="食物节点，用于饮食建议"
    ),
    NodeType.PRECAUTION: NodeSchema(
        label="Precaution",
        properties={
            "content": "string",
            "category": "string",  # 生活方式、用药注意等
            "importance": "string",  # low/medium/high
        },
        indexes=["category"],
        description="注意事项节点，如：低盐饮食、定期复查"
    ),
}


# ============================================================
# Relation Types (12 types)
# ============================================================

class RelationType(str, Enum):
    """Neo4j relationship types"""
    HAS_SYMPTOM = "HAS_SYMPTOM"
    MAY_INDICATE = "MAY_INDICATE"
    BELONGS_TO_DEPARTMENT = "BELONGS_TO_DEPARTMENT"
    TREATED_BY_MEDICATION = "TREATED_BY_MEDICATION"
    TREATS_DISEASE = "TREATS_DISEASE"
    HAS_SIDE_EFFECT = "HAS_SIDE_EFFECT"
    INTERACTS_WITH = "INTERACTS_WITH"
    NEEDS_EXAMINATION = "NEEDS_EXAMINATION"
    AFFECTS_BODY_PART = "AFFECTS_BODY_PART"
    HANDLES_DISEASE = "HANDLES_DISEASE"
    RECOMMENDS_FOOD = "RECOMMENDS_FOOD"
    HAS_PRECAUTION = "HAS_PRECAUTION"


# ============================================================
# Value-Vocabulary Enums（抽取层与 Agent 层共用的值域契约）
# ============================================================

class SeverityLevel(str, Enum):
    """严重程度（超集契约：抽取层与 Agent 层共用此定义）"""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    EMERGENCY = "emergency"


class FrequencyLevel(str, Enum):
    """症状出现频率"""
    RARE = "rare"
    OCCASIONAL = "occasional"
    COMMON = "common"
    VERY_COMMON = "very_common"


class EvidenceLevel(str, Enum):
    """治疗推荐证据等级"""
    A = "A"  # Strong evidence
    B = "B"  # Moderate evidence
    C = "C"  # Weak evidence
    D = "D"  # Expert opinion


class DiseaseRelationType(str, Enum):
    """疾病-疾病关系的语义类别（抽取层概念）。

    注意：这不是图关系类型（RelationType），而是描述疾病间关联语义的抽取字段值。
    原名 RelationType，因与图关系契约重名而改名（R1 名字唯一主人）。
    """
    COMPLICATION = "complication"       # 并发症
    COMORBIDITY = "comorbidity"         # 合并症
    CAUSAL = "causal"                   # 因果关系
    SIMILAR = "similar"                 # 相似疾病


@dataclass
class RelationSchema:
    """Schema definition for a relation type"""
    type: str
    start_node: NodeType
    end_node: NodeType
    properties: dict[str, str] = field(default_factory=dict)
    description: str = ""


# Relation schemas with start/end nodes and properties
RELATION_SCHEMAS: dict[RelationType, RelationSchema] = {
    RelationType.HAS_SYMPTOM: RelationSchema(
        type="HAS_SYMPTOM",
        start_node=NodeType.DISEASE,
        end_node=NodeType.SYMPTOM,
        properties={"frequency": "string"},  # rare/occasional/common
        description="疾病-症状关系"
    ),
    RelationType.MAY_INDICATE: RelationSchema(
        type="MAY_INDICATE",
        start_node=NodeType.SYMPTOM,
        end_node=NodeType.DISEASE,
        properties={"probability": "string"},  # low/medium/high
        description="症状-疾病关系（反向）"
    ),
    RelationType.BELONGS_TO_DEPARTMENT: RelationSchema(
        type="BELONGS_TO_DEPARTMENT",
        start_node=NodeType.DISEASE,
        end_node=NodeType.DEPARTMENT,
        properties={"priority": "integer"},  # 1=首选, 2=次选
        description="疾病-科室关系"
    ),
    RelationType.TREATED_BY_MEDICATION: RelationSchema(
        type="TREATED_BY_MEDICATION",
        start_node=NodeType.DISEASE,
        end_node=NodeType.MEDICATION,
        properties={
            "evidence_level": "string",  # A/B/C/D
            "is_first_line": "boolean"
        },
        description="疾病-药物关系"
    ),
    RelationType.TREATS_DISEASE: RelationSchema(
        type="TREATS_DISEASE",
        start_node=NodeType.MEDICATION,
        end_node=NodeType.DISEASE,
        properties={},
        description="药物-疾病关系（反向）"
    ),
    RelationType.HAS_SIDE_EFFECT: RelationSchema(
        type="HAS_SIDE_EFFECT",
        start_node=NodeType.MEDICATION,
        end_node=NodeType.SYMPTOM,
        properties={"frequency": "string"},
        description="药物-副作用关系"
    ),
    RelationType.INTERACTS_WITH: RelationSchema(
        type="INTERACTS_WITH",
        start_node=NodeType.MEDICATION,
        end_node=NodeType.MEDICATION,
        properties={
            "severity": "string",  # low/medium/high
            "description": "string"
        },
        description="药物-药物相互作用"
    ),
    RelationType.NEEDS_EXAMINATION: RelationSchema(
        type="NEEDS_EXAMINATION",
        start_node=NodeType.DISEASE,
        end_node=NodeType.EXAMINATION,
        properties={"necessity": "string"},  # required/recommended/optional
        description="疾病-检查关系"
    ),
    RelationType.AFFECTS_BODY_PART: RelationSchema(
        type="AFFECTS_BODY_PART",
        start_node=NodeType.DISEASE,
        end_node=NodeType.BODY_PART,
        properties={},
        description="疾病-身体部位关系"
    ),
    RelationType.HANDLES_DISEASE: RelationSchema(
        type="HANDLES_DISEASE",
        start_node=NodeType.DEPARTMENT,
        end_node=NodeType.DISEASE,
        properties={},
        description="科室-疾病关系（反向）"
    ),
    RelationType.RECOMMENDS_FOOD: RelationSchema(
        type="RECOMMENDS_FOOD",
        start_node=NodeType.DISEASE,
        end_node=NodeType.FOOD,
        properties={"recommendation_type": "string"},  # recommended/avoid
        description="疾病-食物推荐关系"
    ),
    RelationType.HAS_PRECAUTION: RelationSchema(
        type="HAS_PRECAUTION",
        start_node=NodeType.DISEASE,
        end_node=NodeType.PRECAUTION,
        properties={"importance": "string"},
        description="疾病-注意事项关系"
    ),
}


# ============================================================
# Utility Functions
# ============================================================

def get_node_schema(node_type: NodeType) -> NodeSchema:
    """Get schema for a node type"""
    return NODE_SCHEMAS[node_type]


def get_relation_schema(relation_type: RelationType) -> RelationSchema:
    """Get schema for a relation type"""
    return RELATION_SCHEMAS[relation_type]


def get_all_node_types() -> list[NodeType]:
    """Get all node types"""
    return list(NodeType)


def get_all_relation_types() -> list[RelationType]:
    """Get all relation types"""
    return list(RelationType)


# ============================================================
# Cypher Generation
# ============================================================

def generate_constraint_cypher() -> list[str]:
    """Generate Cypher statements for unique constraints"""
    statements = []
    for node_type, schema in NODE_SCHEMAS.items():
        if schema.unique_constraint:
            prop = schema.unique_constraint
            stmt = f"""
CREATE CONSTRAINT {schema.label.lower()}_{prop}_unique IF NOT EXISTS
FOR (n:{schema.label}) REQUIRE n.{prop} IS UNIQUE"""
            statements.append(stmt.strip())
    return statements


def generate_index_cypher() -> list[str]:
    """Generate Cypher statements for indexes"""
    statements = []
    for node_type, schema in NODE_SCHEMAS.items():
        for prop in schema.indexes:
            if prop != schema.unique_constraint:  # Skip if already has constraint
                stmt = f"""
CREATE INDEX {schema.label.lower()}_{prop}_idx IF NOT EXISTS
FOR (n:{schema.label}) ON (n.{prop})"""
                statements.append(stmt.strip())
    return statements


def generate_full_schema_cypher() -> str:
    """Generate complete schema initialization Cypher script"""
    lines = [
        "// ============================================",
        "// Medical Knowledge Graph Schema",
        "// Generated by schema.py",
        "// ============================================",
        "",
        "// ===== Unique Constraints =====",
    ]

    for stmt in generate_constraint_cypher():
        lines.append(stmt + ";")
        lines.append("")

    lines.append("// ===== Indexes =====")

    for stmt in generate_index_cypher():
        lines.append(stmt + ";")
        lines.append("")

    lines.append("// ===== Verification =====")
    lines.append("CALL db.constraints();")
    lines.append("CALL db.indexes();")

    return "\n".join(lines)


def generate_llm_schema_text() -> str:
    """Generate a compact graph Schema description for LLM prompts (Text2Cypher).

    供 Text2Cypher 引擎注入系统提示词：让 LLM 看着 Schema 生成合法 Cypher。
    纯静态生成（基于 NODE_SCHEMAS / RELATION_SCHEMAS），不依赖数据库连接。
    三段式：节点类型（含属性）/ 关系类型（含方向三元组）/ 查询约定（只读+LIMIT）。
    """
    lines = ["【节点类型】"]
    for schema in NODE_SCHEMAS.values():
        props = ", ".join(schema.properties.keys())
        lines.append(f"- {schema.label}（{schema.description}）属性: {props}")

    lines.append("")
    lines.append("【关系类型】格式：(起点)-[:关系]->(终点)")
    for schema in RELATION_SCHEMAS.values():
        rel_props = (
            f"，关系属性: {', '.join(schema.properties.keys())}"
            if schema.properties else ""
        )
        lines.append(
            f"- ({schema.start_node.value})-[:{schema.type}]->({schema.end_node.value}) "
            f"{schema.description}{rel_props}"
        )

    lines.append("")
    lines.append("【查询约定】")
    lines.append("- 节点一般用 name 属性匹配；Precaution 节点用 content 属性")
    lines.append("- 只读查询：仅可用 MATCH / OPTIONAL MATCH / WHERE / WITH / UNWIND / RETURN，"
                 "禁止 CREATE / MERGE / DELETE / SET / REMOVE 等任何写操作")
    lines.append("- 查询末尾必须附带 LIMIT（不超过 50）")
    return "\n".join(lines)


# ============================================================
# Main: Self-test
# ============================================================

if __name__ == "__main__":
    import sys
    if sys.platform == "win32":
        sys.stdout.reconfigure(encoding="utf-8")

    print("=" * 60)
    print("Knowledge Graph Schema Validation")
    print("=" * 60)

    # Test node types
    print("\n[NODE TYPES] 8 types")
    for nt in get_all_node_types():
        schema = get_node_schema(nt)
        print(f"  {nt.value}: {len(schema.properties)} properties, constraint={schema.unique_constraint}")

    # Test relation types
    print("\n[RELATION TYPES] 12 types")
    for rt in get_all_relation_types():
        schema = get_relation_schema(rt)
        print(f"  {rt.value}: {schema.start_node.value} -> {schema.end_node.value}")

    # Generate Cypher
    print("\n[CONSTRAINTS]")
    constraints = generate_constraint_cypher()
    print(f"  Generated {len(constraints)} unique constraints")

    print("\n[INDEXES]")
    indexes = generate_index_cypher()
    print(f"  Generated {len(indexes)} indexes")

    # Show sample Cypher
    print("\n[SAMPLE CYPHER]")
    print("-" * 40)
    print(generate_full_schema_cypher()[:500])
    print("...")

    # LLM-facing schema text
    print("\n[LLM SCHEMA TEXT]")
    print("-" * 40)
    llm_text = generate_llm_schema_text()
    print(llm_text[:400])
    print(f"... ({len(llm_text)} chars total)")

    print("\n" + "=" * 60)
    print("[SUCCESS] Schema validation passed!")
    print("=" * 60)
