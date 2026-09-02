"""
Knowledge Graph Queries
Provides query functions for Agents to access the knowledge graph.
"""

import re
import sys
from pathlib import Path
from typing import Optional

# Ensure project root is in sys.path
_project_root = Path(__file__).parent.parent.parent.resolve()
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from config.settings import settings
from src.common.logger import setup_logger

logger = setup_logger(__name__, "graph_queries.log")


class GraphQueries:
    """
    Knowledge Graph Query Interface

    Provides high-level query functions for Agents.

    Usage:
        >>> queries = GraphQueries()
        >>> symptoms = queries.get_disease_symptoms("高血压")
        >>> diseases = queries.get_symptom_diseases("头痛")
        >>> drugs = queries.get_disease_medications("高血压")
    """

    def __init__(self):
        self._driver = None

    def get_driver(self):
        """Get Neo4j driver"""
        if self._driver is None:
            from neo4j import GraphDatabase
            self._driver = GraphDatabase.driver(
                settings.neo4j_uri,
                auth=(settings.neo4j_user, settings.neo4j_password)
            )
        return self._driver

    def close(self):
        """Close driver"""
        if self._driver:
            self._driver.close()
            self._driver = None

    # ============================================================
    # Generic Cypher Execution (for Text2Cypher)
    # ============================================================

    # L2 安全层：写关键字拒绝正则（与只读事务构成双保险）
    _WRITE_KEYWORDS = re.compile(
        r"\b(CREATE|MERGE|DELETE|DETACH|SET|REMOVE|DROP|LOAD|FOREACH)\b|CALL\s+db",
        re.IGNORECASE,
    )

    def check_cypher_syntax(self, cypher: str, params: Optional[dict] = None) -> tuple[bool, str]:
        """
        Validate Cypher syntax with EXPLAIN (plans but does not execute).

        Args:
            cypher: Cypher query string
            params: Optional query parameters

        Returns:
            (is_valid, message) tuple
        """
        try:
            from neo4j.exceptions import CypherSyntaxError
        except ImportError:  # pragma: no cover
            return False, "neo4j 驱动未安装"
        try:
            driver = self.get_driver()
            with driver.session() as session:
                session.run(f"EXPLAIN {cypher}", params or {})
            return True, "语法正确"
        except CypherSyntaxError as e:
            return False, f"语法错误: {e}"
        except Exception as e:
            return False, f"校验失败: {e}"

    def run_readonly_cypher(self, cypher: str, params: Optional[dict] = None,
                            max_records: int = 50) -> list[dict]:
        """
        Execute an LLM-generated Cypher in a READ-ONLY transaction.

        供 Text2Cypher 引擎调用。三层安全防线：
        1. L2 写关键字拒绝：发送前正则拦截 CREATE/MERGE/DELETE/SET/... 与 CALL db* 过程调用
        2. L1 只读事务：session(default_access_mode=READ_ACCESS)，驱动层保证即使绕过
           关键字检查也无法写入（数据库直接拒绝）
        3. L5 记录数截断：枚举到 max_records 立即停止，防全表扫描打爆上下文

        Args:
            cypher: Cypher query string (must be read-only)
            params: Optional query parameters
            max_records: Maximum number of records to return

        Returns:
            List of record dicts (each record via record.data())

        Raises:
            ValueError: If the query contains write keywords (L2 rejection)
            Exception: Neo4j connection/execution errors propagate to caller
                       (Text2CypherEngine 负责兜底，绝不向上打断 ReAct 循环)
        """
        # L2: 写关键字拒绝
        if self._WRITE_KEYWORDS.search(cypher):
            logger.warning(f"[run_readonly_cypher] REJECTED write attempt: {cypher[:200]}")
            raise ValueError("仅允许执行只读 Cypher 查询（检测到写操作关键字）")

        from neo4j import READ_ACCESS

        driver = self.get_driver()
        records: list[dict] = []

        with driver.session(default_access_mode=READ_ACCESS) as session:
            def _work(tx):
                result = tx.run(cypher, params or {})
                for i, record in enumerate(result):
                    if i >= max_records:  # L5: 记录数截断
                        break
                    records.append(record.data())

            session.execute_read(_work)

        return records

    # ============================================================
    # Disease Queries
    # ============================================================

    def get_disease_info(self, disease_name: str) -> Optional[dict]:
        """
        Get basic information about a disease

        Args:
            disease_name: Name of the disease

        Returns:
            Dict with disease info or None
        """
        driver = self.get_driver()
        with driver.session() as session:
            result = session.run("""
                MATCH (d:Disease {name: $name})
                RETURN d.name AS name,
                       d.description AS description,
                       d.icd_code AS icd_code
            """, name=disease_name)
            record = result.single()
            if record:
                return {
                    "name": record["name"],
                    "description": record["description"],
                    "icd_code": record["icd_code"]
                }
            return None

    def get_disease_symptoms(self, disease_name: str) -> list[str]:
        """
        Get all symptoms of a disease

        Args:
            disease_name: Name of the disease

        Returns:
            List of symptom names
        """
        driver = self.get_driver()
        with driver.session() as session:
            result = session.run("""
                MATCH (d:Disease {name: $name})-[:HAS_SYMPTOM]->(s:Symptom)
                RETURN s.name AS symptom
                ORDER BY s.name
            """, name=disease_name)
            return [record["symptom"] for record in result]

    def get_disease_medications(self, disease_name: str) -> list[dict]:
        """
        Get all medications for a disease

        Args:
            disease_name: Name of the disease

        Returns:
            List of medication dicts
        """
        driver = self.get_driver()
        with driver.session() as session:
            result = session.run("""
                MATCH (d:Disease {name: $name})-[r:TREATED_BY_MEDICATION]->(m:Medication)
                RETURN m.name AS name,
                       m.category AS category,
                       r.evidence_level AS evidence_level
                ORDER BY m.name
            """, name=disease_name)
            return [
                {
                    "name": record["name"],
                    "category": record["category"],
                    "evidence_level": record["evidence_level"]
                }
                for record in result
            ]

    def get_disease_departments(self, disease_name: str) -> list[str]:
        """
        Get recommended departments for a disease

        Args:
            disease_name: Name of the disease

        Returns:
            List of department names (ordered by priority)
        """
        driver = self.get_driver()
        with driver.session() as session:
            result = session.run("""
                MATCH (d:Disease {name: $name})-[r:BELONGS_TO_DEPARTMENT]->(dep:Department)
                RETURN dep.name AS department
                ORDER BY r.priority
            """, name=disease_name)
            return [record["department"] for record in result]

    def get_disease_examinations(self, disease_name: str) -> list[str]:
        """
        Get recommended examinations for a disease

        Args:
            disease_name: Name of the disease

        Returns:
            List of examination names
        """
        driver = self.get_driver()
        with driver.session() as session:
            result = session.run("""
                MATCH (d:Disease {name: $name})-[:NEEDS_EXAMINATION]->(e:Examination)
                RETURN e.name AS examination
                ORDER BY e.name
            """, name=disease_name)
            return [record["examination"] for record in result]

    def get_disease_full_info(self, disease_name: str) -> Optional[dict]:
        """
        Get complete information about a disease

        Args:
            disease_name: Name of the disease

        Returns:
            Dict with all disease info
        """
        info = self.get_disease_info(disease_name)
        if not info:
            return None

        info["symptoms"] = self.get_disease_symptoms(disease_name)
        info["medications"] = self.get_disease_medications(disease_name)
        info["departments"] = self.get_disease_departments(disease_name)
        info["examinations"] = self.get_disease_examinations(disease_name)

        return info

    # ============================================================
    # Symptom Queries
    # ============================================================

    def get_symptom_diseases(self, symptom_name: str) -> list[str]:
        """
        Get diseases that may cause a symptom

        Args:
            symptom_name: Name of the symptom

        Returns:
            List of disease names
        """
        driver = self.get_driver()
        with driver.session() as session:
            result = session.run("""
                MATCH (s:Symptom {name: $name})<-[:HAS_SYMPTOM]-(d:Disease)
                RETURN d.name AS disease
                ORDER BY d.name
            """, name=symptom_name)
            return [record["disease"] for record in result]

    def get_symptom_info(self, symptom_name: str) -> Optional[dict]:
        """
        Get information about a symptom

        Args:
            symptom_name: Name of the symptom

        Returns:
            Dict with symptom info
        """
        driver = self.get_driver()
        with driver.session() as session:
            result = session.run("""
                MATCH (s:Symptom {name: $name})
                RETURN s.name AS name,
                       s.description AS description,
                       s.severity AS severity
            """, name=symptom_name)
            record = result.single()
            if record:
                return {
                    "name": record["name"],
                    "description": record["description"],
                    "severity": record["severity"]
                }
            return None

    # ============================================================
    # Medication Queries
    # ============================================================

    def get_medication_info(self, medication_name: str) -> Optional[dict]:
        """
        Get information about a medication

        Args:
            medication_name: Name of the medication

        Returns:
            Dict with medication info
        """
        driver = self.get_driver()
        with driver.session() as session:
            result = session.run("""
                MATCH (m:Medication {name: $name})
                RETURN m.name AS name,
                       m.category AS category,
                       m.side_effects AS side_effects,
                       m.contraindications AS contraindications
            """, name=medication_name)
            record = result.single()
            if record:
                return {
                    "name": record["name"],
                    "category": record["category"],
                    "side_effects": record["side_effects"] or [],
                    "contraindications": record["contraindications"] or []
                }
            return None

    def get_medication_diseases(self, medication_name: str) -> list[str]:
        """
        Get diseases treated by a medication

        Args:
            medication_name: Name of the medication

        Returns:
            List of disease names
        """
        driver = self.get_driver()
        with driver.session() as session:
            result = session.run("""
                MATCH (m:Medication {name: $name})-[:TREATS_DISEASE]->(d:Disease)
                RETURN d.name AS disease
                ORDER BY d.name
            """, name=medication_name)
            return [record["disease"] for record in result]

    def get_medication_interactions(self, medication_name: str) -> list[dict]:
        """
        Get drug interactions for a medication

        Args:
            medication_name: Name of the medication

        Returns:
            List of interaction dicts
        """
        driver = self.get_driver()
        with driver.session() as session:
            result = session.run("""
                MATCH (m1:Medication {name: $name})-[r:INTERACTS_WITH]->(m2:Medication)
                RETURN m2.name AS drug,
                       r.severity AS severity,
                       r.description AS description
            """, name=medication_name)
            return [
                {
                    "drug": record["drug"],
                    "severity": record["severity"],
                    "description": record["description"]
                }
                for record in result
            ]

    # ============================================================
    # Department Queries
    # ============================================================

    def get_department_diseases(self, department_name: str) -> list[str]:
        """
        Get diseases handled by a department

        Args:
            department_name: Name of the department

        Returns:
            List of disease names
        """
        driver = self.get_driver()
        with driver.session() as session:
            # Use BELONGS_TO_DEPARTMENT relation (Disease -> Department)
            result = session.run("""
                MATCH (d:Disease)-[:BELONGS_TO_DEPARTMENT]->(dep:Department {name: $name})
                RETURN d.name AS disease
                ORDER BY d.name
            """, name=department_name)
            return [record["disease"] for record in result]

    # ============================================================
    # Search Queries
    # ============================================================

    def search_diseases(self, keyword: str, limit: int = 10) -> list[str]:
        """
        Search diseases by keyword

        Args:
            keyword: Search keyword
            limit: Max results

        Returns:
            List of disease names
        """
        driver = self.get_driver()
        with driver.session() as session:
            result = session.run("""
                MATCH (d:Disease)
                WHERE d.name CONTAINS $keyword
                   OR d.description CONTAINS $keyword
                RETURN d.name AS name
                LIMIT $limit
            """, keyword=keyword, limit=limit)
            return [record["name"] for record in result]

    def search_symptoms(self, keyword: str, limit: int = 10) -> list[str]:
        """
        Search symptoms by keyword

        Args:
            keyword: Search keyword
            limit: Max results

        Returns:
            List of symptom names
        """
        driver = self.get_driver()
        with driver.session() as session:
            result = session.run("""
                MATCH (s:Symptom)
                WHERE s.name CONTAINS $keyword
                RETURN s.name AS name
                LIMIT $limit
            """, keyword=keyword, limit=limit)
            return [record["name"] for record in result]

    # ============================================================
    # Statistics Queries
    # ============================================================

    def get_statistics(self) -> dict:
        """
        Get graph statistics

        Returns:
            Dict with statistics
        """
        driver = self.get_driver()
        with driver.session() as session:
            # Node counts
            result = session.run("""
                MATCH (n)
                RETURN labels(n)[0] AS label, count(n) AS count
            """)
            nodes = {r["label"]: r["count"] for r in result}

            # Relation counts
            result = session.run("""
                MATCH ()-[r]->()
                RETURN type(r) AS type, count(r) AS count
            """)
            relations = {r["type"]: r["count"] for r in result}

            return {
                "nodes": nodes,
                "relations": relations,
                "total_nodes": sum(nodes.values()),
                "total_relations": sum(relations.values())
            }


def main():
    if sys.platform == "win32":
        sys.stdout.reconfigure(encoding="utf-8")

    print("=" * 60)
    print("Knowledge Graph Queries Test")
    print("=" * 60)

    queries = GraphQueries()

    try:
        # Test statistics
        print("\n[TEST 1] Graph Statistics")
        stats = queries.get_statistics()
        print(f"  Total nodes: {stats['total_nodes']}")
        print(f"  Total relations: {stats['total_relations']}")
        print(f"  Node types: {list(stats['nodes'].keys())}")

        # Test disease query
        print("\n[TEST 2] Disease Query (高血压)")
        info = queries.get_disease_full_info("高血压")
        if info:
            print(f"  Name: {info['name']}")
            print(f"  Symptoms: {info['symptoms']}")
            print(f"  Medications: {[m['name'] for m in info['medications']]}")
            print(f"  Departments: {info['departments']}")
        else:
            print("  Disease not found")

        # Test symptom query
        print("\n[TEST 3] Symptom Query (头痛)")
        diseases = queries.get_symptom_diseases("头痛")
        print(f"  Diseases: {diseases}")

        # Test search
        print("\n[TEST 4] Search Query (高)")
        results = queries.search_diseases("高")
        print(f"  Results: {results}")

        print("\n" + "=" * 60)
        print("[SUCCESS] All query tests completed!")
        print("=" * 60)

    finally:
        queries.close()


if __name__ == "__main__":
    main()
