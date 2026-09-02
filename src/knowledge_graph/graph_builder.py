"""
Knowledge Graph Builder
Imports entities and relations from JSON files into Neo4j database.
"""

import sys
import json
from pathlib import Path
from collections import Counter
from datetime import datetime

# Ensure project root is in sys.path
_project_root = Path(__file__).parent.parent.parent.resolve()
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from tqdm import tqdm

from config.settings import settings
from config.paths import DATA_KG_DIR, LOGS_DIR
from src.common.logger import setup_logger
from src.knowledge_graph.schema import NodeType, RelationType

logger = setup_logger(__name__, "graph_builder.log")


# ============================================================
# Default Paths
# ============================================================

ENTITIES_FILE = DATA_KG_DIR / "entities.json"
RELATIONS_FILE = DATA_KG_DIR / "relations.json"


# ============================================================
# Cypher Templates
# ============================================================

NODE_CYPHER_TEMPLATES = {
    NodeType.DISEASE.value: """
        MERGE (n:Disease {name: $name})
        ON CREATE SET
            n.description = $description,
            n.icd_code = $icd_code,
            n.created_at = datetime()
        ON MATCH SET
            n.description = coalesce($description, n.description),
            n.icd_code = coalesce($icd_code, n.icd_code),
            n.updated_at = datetime()
    """,
    NodeType.SYMPTOM.value: """
        MERGE (n:Symptom {name: $name})
        ON CREATE SET
            n.description = $description,
            n.severity = $severity
        ON MATCH SET
            n.description = coalesce($description, n.description),
            n.severity = coalesce($severity, n.severity)
    """,
    NodeType.MEDICATION.value: """
        MERGE (n:Medication {name: $name})
        ON CREATE SET
            n.category = $category,
            n.side_effects = $side_effects,
            n.contraindications = $contraindications
        ON MATCH SET
            n.category = coalesce($category, n.category),
            n.side_effects = coalesce($side_effects, n.side_effects),
            n.contraindications = coalesce($contraindications, n.contraindications)
    """,
    # Alias for backward compatibility  # legacy-alias（旧抽取产物别名 → Medication 节点）
    # 注意：注释必须放在字符串外——Cypher 不支持 # 注释，嵌入模板会导致 SyntaxError
    "Drug": """
        MERGE (n:Medication {name: $name})
        ON CREATE SET
            n.category = $category,
            n.side_effects = $side_effects,
            n.contraindications = $contraindications
        ON MATCH SET
            n.category = coalesce($category, n.category),
            n.side_effects = coalesce($side_effects, n.side_effects),
            n.contraindications = coalesce($contraindications, n.contraindications)
    """,
    NodeType.DEPARTMENT.value: """
        MERGE (n:Department {name: $name})
        ON CREATE SET
            n.description = $description,
            n.floor = $floor
        ON MATCH SET
            n.description = coalesce($description, n.description)
    """,
    NodeType.EXAMINATION.value: """
        MERGE (n:Examination {name: $name})
        ON CREATE SET
            n.type = $type,
            n.purpose = $purpose
        ON MATCH SET
            n.purpose = coalesce($purpose, n.purpose)
    """,
    # aux（辅助抽取类型，不在 NodeType 核心契约）
    "Treatment": """
        MERGE (n:Treatment {name: $name})
        ON CREATE SET
            n.description = $description
        ON MATCH SET
            n.description = coalesce($description, n.description)
    """,
    NodeType.BODY_PART.value: """
        MERGE (n:BodyPart {name: $name})
        ON CREATE SET
            n.description = $description,
            n.system = $system
        ON MATCH SET
            n.description = coalesce($description, n.description)
    """,
    # aux（辅助抽取类型，不在 NodeType 核心契约）
    "MedicalConcept": """
        MERGE (n:MedicalConcept {name: $name})
        ON CREATE SET
            n.definition = $definition
        ON MATCH SET
            n.definition = coalesce($definition, n.definition)
    """,
    NodeType.FOOD.value: """
        MERGE (n:Food {name: $name})
        ON CREATE SET
            n.type = $type,
            n.description = $description
        ON MATCH SET
            n.description = coalesce($description, n.description)
    """,
    NodeType.PRECAUTION.value: """
        MERGE (n:Precaution {content: $content})
        ON CREATE SET
            n.category = $category,
            n.importance = $importance
        ON MATCH SET
            n.category = coalesce($category, n.category)
    """,
}

# 历史命名 → 规范命名（schema.py RelationType）。
# 旧版抽取产物用过这两种拼写，导入时统一归一，保证旧 relations.json 仍可用。
RELATION_TYPE_ALIASES = {
    "BELONG_TO_DEPARTMENT": "BELONGS_TO_DEPARTMENT",  # legacy-alias
    "TREATED_BY_DRUG": "TREATED_BY_MEDICATION",       # legacy-alias
}

RELATION_CYPHER_TEMPLATES = {
    RelationType.HAS_SYMPTOM.value: """
        MATCH (d:Disease {name: $disease_name})
        MATCH (s:Symptom {name: $symptom_name})
        MERGE (d)-[r:HAS_SYMPTOM]->(s)
        ON CREATE SET r.frequency = $frequency
    """,
    RelationType.MAY_INDICATE.value: """
        MATCH (s:Symptom {name: $symptom_name})
        MATCH (d:Disease {name: $disease_name})
        MERGE (s)-[r:MAY_INDICATE]->(d)
        ON CREATE SET r.probability = $probability
    """,
    RelationType.BELONGS_TO_DEPARTMENT.value: """
        MATCH (d:Disease {name: $disease_name})
        MATCH (dep:Department {name: $department_name})
        MERGE (d)-[r:BELONGS_TO_DEPARTMENT]->(dep)
        ON CREATE SET r.priority = $priority
    """,
    RelationType.TREATED_BY_MEDICATION.value: """
        MATCH (d:Disease {name: $disease_name})
        MATCH (dr:Medication {name: $drug_name})
        MERGE (d)-[r:TREATED_BY_MEDICATION]->(dr)
        ON CREATE SET r.evidence_level = $evidence_level
    """,
    RelationType.TREATS_DISEASE.value: """
        MATCH (dr:Medication {name: $drug_name})
        MATCH (d:Disease {name: $disease_name})
        MERGE (dr)-[r:TREATS_DISEASE]->(d)
    """,
    RelationType.HAS_SIDE_EFFECT.value: """
        MATCH (dr:Medication {name: $drug_name})
        MATCH (s:Symptom {name: $symptom_name})
        MERGE (dr)-[r:HAS_SIDE_EFFECT]->(s)
        ON CREATE SET r.frequency = $frequency
    """,
    RelationType.INTERACTS_WITH.value: """
        MATCH (dr1:Medication {name: $drug1_name})
        MATCH (dr2:Medication {name: $drug2_name})
        MERGE (dr1)-[r:INTERACTS_WITH]->(dr2)
        ON CREATE SET r.severity = $severity
    """,
    RelationType.NEEDS_EXAMINATION.value: """
        MATCH (d:Disease {name: $disease_name})
        MATCH (e:Examination {name: $examination_name})
        MERGE (d)-[r:NEEDS_EXAMINATION]->(e)
        ON CREATE SET r.necessity = $necessity
    """,
    RelationType.AFFECTS_BODY_PART.value: """
        MATCH (d:Disease {name: $disease_name})
        MATCH (bp:BodyPart {name: $body_part_name})
        MERGE (d)-[r:AFFECTS_BODY_PART]->(bp)
    """,
    RelationType.HANDLES_DISEASE.value: """
        MATCH (dep:Department {name: $department_name})
        MATCH (d:Disease {name: $disease_name})
        MERGE (dep)-[r:HANDLES_DISEASE]->(d)
    """,
    RelationType.RECOMMENDS_FOOD.value: """
        MATCH (d:Disease {name: $disease_name})
        MATCH (f:Food {name: $food_name})
        MERGE (d)-[r:RECOMMENDS_FOOD]->(f)
        ON CREATE SET r.recommendation_type = $recommendation_type
    """,
    RelationType.HAS_PRECAUTION.value: """
        MATCH (d:Disease {name: $disease_name})
        MATCH (p:Precaution {content: $content})
        MERGE (d)-[r:HAS_PRECAUTION]->(p)
        ON CREATE SET r.importance = $importance
    """,
}


# R1 验收（导入即生效）：模板键必须全部出自契约枚举
# （辅助类型 Treatment/MedicalConcept 与历史别名 Drug 例外，见 check_contracts 白名单）
_AUX_NODE_TEMPLATE_KEYS = {"Treatment", "MedicalConcept", "Drug"}  # legacy-alias / aux
assert set(NODE_CYPHER_TEMPLATES) <= {nt.value for nt in NodeType} | _AUX_NODE_TEMPLATE_KEYS,     f"节点模板键越界: {set(NODE_CYPHER_TEMPLATES) - {nt.value for nt in NodeType} - _AUX_NODE_TEMPLATE_KEYS}"
assert set(RELATION_CYPHER_TEMPLATES) <= {rt.value for rt in RelationType},     f"关系模板键越界: {set(RELATION_CYPHER_TEMPLATES) - {rt.value for rt in RelationType}}"


# ============================================================
# Knowledge Graph Builder
# ============================================================

class KnowledgeGraphBuilder:
    """
    Knowledge Graph Builder

    Imports entities and relations from JSON files into Neo4j.

    Usage:
        >>> builder = KnowledgeGraphBuilder()
        >>> builder.build_all()
        >>> builder.print_statistics()
    """

    def __init__(
        self,
        entities_file: Path = ENTITIES_FILE,
        relations_file: Path = RELATIONS_FILE,
        batch_size: int = 500
    ):
        """
        Initialize the builder

        Args:
            entities_file: Path to entities JSON file
            relations_file: Path to relations JSON file
            batch_size: Number of records per transaction
        """
        self.entities_file = entities_file
        self.relations_file = relations_file
        self.batch_size = batch_size

        self.entities: list[dict] = []
        self.relations: list[dict] = []

        self.stats = {
            "nodes_created": Counter(),
            "relations_created": Counter(),
            "nodes_failed": 0,
            "relations_failed": 0,
        }

        self._driver = None

    def get_driver(self):
        """Get Neo4j driver (lazy initialization)"""
        if self._driver is None:
            try:
                from neo4j import GraphDatabase
                self._driver = GraphDatabase.driver(
                    settings.neo4j_uri,
                    auth=(settings.neo4j_user, settings.neo4j_password)
                )
                logger.info(f"[NEO4J] Connected to {settings.neo4j_uri}")
            except Exception as e:
                logger.error(f"[NEO4J] Connection failed: {e}")
                raise
        return self._driver

    def close(self):
        """Close Neo4j driver"""
        if self._driver:
            self._driver.close()
            self._driver = None
            logger.info("[NEO4J] Connection closed")

    def load_data(self) -> bool:
        """
        Load entities and relations from JSON files

        Returns:
            True if data loaded successfully
        """
        # Load entities
        if self.entities_file.exists():
            try:
                with open(self.entities_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                self.entities = data.get("entities", [])
                logger.info(f"[LOAD] Loaded {len(self.entities)} entities from {self.entities_file}")
            except Exception as e:
                logger.error(f"[LOAD] Failed to load entities: {e}")
                return False
        else:
            logger.warning(f"[LOAD] Entities file not found: {self.entities_file}")

        # Load relations
        if self.relations_file.exists():
            try:
                with open(self.relations_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                self.relations = data.get("relations", [])
                logger.info(f"[LOAD] Loaded {len(self.relations)} relations from {self.relations_file}")
            except Exception as e:
                logger.error(f"[LOAD] Failed to load relations: {e}")
                return False
        else:
            logger.warning(f"[LOAD] Relations file not found: {self.relations_file}")

        return True

    def build_nodes(self) -> int:
        """
        Build nodes in Neo4j using MERGE

        Returns:
            Number of nodes processed
        """
        if not self.entities:
            logger.warning("[BUILD] No entities to build")
            return 0

        driver = self.get_driver()
        processed = 0

        logger.info(f"[BUILD] Starting node build: {len(self.entities)} entities")

        for i in tqdm(range(0, len(self.entities), self.batch_size), desc="Building nodes", unit="batch"):
            batch = self.entities[i:i + self.batch_size]

            with driver.session() as session:
                for entity in batch:
                    try:
                        node_type = entity.get("type", "")
                        data = entity.get("data", {})

                        template = NODE_CYPHER_TEMPLATES.get(node_type)
                        if not template:
                            logger.warning(f"[BUILD] Unknown node type: {node_type}")
                            self.stats["nodes_failed"] += 1
                            continue

                        # Prepare parameters
                        params = self._prepare_node_params(node_type, data)

                        # Execute
                        session.run(template, params)
                        self.stats["nodes_created"][node_type] += 1
                        processed += 1

                    except Exception as e:
                        logger.error(f"[BUILD] Failed to create node: {e}")
                        self.stats["nodes_failed"] += 1

        logger.info(f"[BUILD] Node build complete: {processed} processed")
        return processed

    def build_relations(self) -> int:
        """
        Build relations in Neo4j using MERGE

        Returns:
            Number of relations processed
        """
        if not self.relations:
            logger.warning("[BUILD] No relations to build")
            return 0

        driver = self.get_driver()
        processed = 0

        logger.info(f"[BUILD] Starting relation build: {len(self.relations)} relations")

        for i in tqdm(range(0, len(self.relations), self.batch_size), desc="Building relations", unit="batch"):
            batch = self.relations[i:i + self.batch_size]

            with driver.session() as session:
                for relation in batch:
                    try:
                        rel_type = relation.get("type", "")
                        # 归一历史命名（如 BELONG_TO_DEPARTMENT → BELONGS_TO_DEPARTMENT）[legacy-alias]
                        rel_type = RELATION_TYPE_ALIASES.get(rel_type, rel_type)
                        data = relation.get("data", {})

                        template = RELATION_CYPHER_TEMPLATES.get(rel_type)
                        if not template:
                            logger.warning(f"[BUILD] Unknown relation type: {rel_type}")
                            self.stats["relations_failed"] += 1
                            continue

                        # Execute
                        session.run(template, data)
                        self.stats["relations_created"][rel_type] += 1
                        processed += 1

                    except Exception as e:
                        logger.error(f"[BUILD] Failed to create relation: {e}")
                        self.stats["relations_failed"] += 1

        logger.info(f"[BUILD] Relation build complete: {processed} processed")
        return processed

    def build_all(self) -> dict:
        """
        Build complete knowledge graph (nodes first, then relations)

        Returns:
            Statistics dictionary
        """
        print("=" * 60)
        print("KNOWLEDGE GRAPH BUILD")
        print("=" * 60)

        # Load data
        if not self.load_data():
            return {"error": "Failed to load data"}

        # Build nodes first
        print("\n[STEP 1] Building nodes...")
        nodes_count = self.build_nodes()

        # Build relations
        print("\n[STEP 2] Building relations...")
        relations_count = self.build_relations()

        # Print statistics
        self.print_statistics()

        return {
            "nodes": nodes_count,
            "relations": relations_count,
            "stats": self.stats
        }

    def _prepare_node_params(self, node_type: str, data: dict) -> dict:
        """Prepare parameters for node creation"""
        params = {"name": data.get("name", "")}

        if node_type == "Disease":
            params["description"] = data.get("description")
            params["icd_code"] = data.get("icd_code")
        elif node_type == "Symptom":
            params["description"] = data.get("description")
            params["severity"] = data.get("severity", "medium")
        elif node_type == "Medication" or node_type == "Drug":
            params["category"] = data.get("category")
            params["side_effects"] = data.get("side_effects", [])
            params["contraindications"] = data.get("contraindications", [])
        elif node_type == "Department":
            params["description"] = data.get("description")
            params["floor"] = data.get("floor_location")
        elif node_type == "Examination":
            params["type"] = data.get("category")
            params["purpose"] = data.get("purpose")
        elif node_type == "Treatment":
            params["description"] = data.get("description")
        elif node_type == "BodyPart":
            params["description"] = data.get("description")
            params["system"] = data.get("system")
        elif node_type == "MedicalConcept":
            params["definition"] = data.get("definition")
        elif node_type == "Food":
            params["type"] = data.get("type")
            params["description"] = data.get("description")
        elif node_type == "Precaution":
            params["content"] = data.get("content", data.get("name", ""))
            params["category"] = data.get("category")
            params["importance"] = data.get("importance")

        return params

    def print_statistics(self):
        """Print build statistics"""
        print("\n" + "=" * 60)
        print("BUILD STATISTICS")
        print("=" * 60)

        # Node statistics
        total_nodes = sum(self.stats["nodes_created"].values())
        print(f"\n[NODES] Total: {total_nodes}")
        for node_type, count in self.stats["nodes_created"].most_common():
            print(f"  {node_type}: {count}")

        if self.stats["nodes_failed"] > 0:
            print(f"  Failed: {self.stats['nodes_failed']}")

        # Relation statistics
        total_relations = sum(self.stats["relations_created"].values())
        print(f"\n[RELATIONS] Total: {total_relations}")
        for rel_type, count in self.stats["relations_created"].most_common():
            print(f"  {rel_type}: {count}")

        if self.stats["relations_failed"] > 0:
            print(f"  Failed: {self.stats['relations_failed']}")

        # Graph density (relations / nodes)
        if total_nodes > 0:
            density = total_relations / total_nodes
            print(f"\n[GRAPH DENSITY] {density:.2f} relations per node")

        print("\n" + "=" * 60)

    def get_graph_statistics(self) -> dict:
        """
        Get statistics from Neo4j database

        Returns:
            Dictionary with node and relation counts
        """
        driver = self.get_driver()

        with driver.session() as session:
            # Count nodes by label
            result = session.run("""
                MATCH (n)
                RETURN labels(n)[0] AS label, count(n) AS count
                ORDER BY count DESC
            """)
            nodes = {record["label"]: record["count"] for record in result}

            # Count relations by type
            result = session.run("""
                MATCH ()-[r]->()
                RETURN type(r) AS type, count(r) AS count
                ORDER BY count DESC
            """)
            relations = {record["type"]: record["count"] for record in result}

            # Total counts
            total_nodes = sum(nodes.values())
            total_relations = sum(relations.values())

            return {
                "nodes": nodes,
                "relations": relations,
                "total_nodes": total_nodes,
                "total_relations": total_relations,
                "density": total_relations / total_nodes if total_nodes > 0 else 0
            }

    def clear_graph(self, confirm: bool = False) -> bool:
        """
        Clear all nodes and relations (DANGEROUS!)

        Args:
            confirm: Must be True to proceed

        Returns:
            True if cleared successfully
        """
        if not confirm:
            logger.warning("[CLEAR] Set confirm=True to clear graph")
            return False

        logger.warning("[CLEAR] Clearing all nodes and relations!")

        driver = self.get_driver()

        with driver.session() as session:
            # Delete all relations first
            session.run("MATCH ()-[r]-() DELETE r")
            logger.info("[CLEAR] Deleted all relations")

            # Delete all nodes
            session.run("MATCH (n) DELETE n")
            logger.info("[CLEAR] Deleted all nodes")

        return True


# ============================================================
# Main: CLI Entry Point
# ============================================================

def main():
    import argparse

    if sys.platform == "win32":
        sys.stdout.reconfigure(encoding="utf-8")

    parser = argparse.ArgumentParser(description="Knowledge Graph Builder")
    parser.add_argument(
        "action",
        choices=["build", "stats", "clear"],
        help="Action to perform"
    )
    parser.add_argument(
        "--entities",
        type=str,
        default=str(ENTITIES_FILE),
        help="Entities JSON file path"
    )
    parser.add_argument(
        "--relations",
        type=str,
        default=str(RELATIONS_FILE),
        help="Relations JSON file path"
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=500,
        help="Batch size for transactions (default: 500)"
    )
    parser.add_argument(
        "--confirm",
        action="store_true",
        help="Confirm destructive action (for clear)"
    )

    args = parser.parse_args()

    builder = KnowledgeGraphBuilder(
        entities_file=Path(args.entities),
        relations_file=Path(args.relations),
        batch_size=args.batch_size
    )

    try:
        if args.action == "build":
            builder.build_all()

        elif args.action == "stats":
            stats = builder.get_graph_statistics()
            print("\n[DATABASE STATISTICS]")
            print(f"  Total nodes: {stats['total_nodes']}")
            print(f"  Total relations: {stats['total_relations']}")
            print(f"  Density: {stats['density']:.2f}")
            print("\n  Nodes by type:")
            for label, count in stats["nodes"].items():
                print(f"    {label}: {count}")
            print("\n  Relations by type:")
            for rel_type, count in stats["relations"].items():
                print(f"    {rel_type}: {count}")

        elif args.action == "clear":
            if args.confirm:
                builder.clear_graph(confirm=True)
                print("[SUCCESS] Graph cleared")
            else:
                print("[ERROR] Use --confirm to clear graph")

    finally:
        builder.close()


if __name__ == "__main__":
    main()
