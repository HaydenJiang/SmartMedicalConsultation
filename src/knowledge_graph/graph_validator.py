"""
Knowledge Graph Validator
Validates data import and graph integrity.
"""

import sys
from pathlib import Path
from dataclasses import dataclass, field
from datetime import datetime

# Ensure project root is in sys.path
_project_root = Path(__file__).parent.parent.parent.resolve()
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from config.settings import settings
from src.common.logger import setup_logger

logger = setup_logger(__name__, "graph_validator.log")


@dataclass
class ValidationResult:
    """Result of a validation check"""
    name: str
    passed: bool
    message: str
    details: dict = field(default_factory=dict)


class GraphValidator:
    """
    Knowledge Graph Validator

    Validates Neo4j data import and graph integrity.

    Usage:
        >>> validator = GraphValidator()
        >>> report = validator.validate_all()
        >>> validator.print_report(report)
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

    def check_connection(self) -> ValidationResult:
        """Check Neo4j connection"""
        try:
            driver = self.get_driver()
            with driver.session() as session:
                result = session.run("RETURN 1 AS test")
                record = result.single()
                if record and record["test"] == 1:
                    return ValidationResult(
                        name="Connection",
                        passed=True,
                        message=f"Connected to {settings.neo4j_uri}"
                    )
        except Exception as e:
            return ValidationResult(
                name="Connection",
                passed=False,
                message=f"Connection failed: {e}"
            )

    def check_node_counts(self) -> ValidationResult:
        """Check node counts by label"""
        try:
            driver = self.get_driver()
            with driver.session() as session:
                result = session.run("""
                    MATCH (n)
                    RETURN labels(n)[0] AS label, count(n) AS count
                    ORDER BY count DESC
                """)
                counts = {record["label"]: record["count"] for record in result}
                total = sum(counts.values())

                passed = total > 0
                message = f"Total nodes: {total}" if passed else "No nodes found"

                return ValidationResult(
                    name="Node Counts",
                    passed=passed,
                    message=message,
                    details=counts
                )
        except Exception as e:
            return ValidationResult(
                name="Node Counts",
                passed=False,
                message=f"Query failed: {e}"
            )

    def check_relation_counts(self) -> ValidationResult:
        """Check relation counts by type"""
        try:
            driver = self.get_driver()
            with driver.session() as session:
                result = session.run("""
                    MATCH ()-[r]->()
                    RETURN type(r) AS type, count(r) AS count
                    ORDER BY count DESC
                """)
                counts = {record["type"]: record["count"] for record in result}
                total = sum(counts.values())

                passed = total > 0
                message = f"Total relations: {total}" if passed else "No relations found"

                return ValidationResult(
                    name="Relation Counts",
                    passed=passed,
                    message=message,
                    details=counts
                )
        except Exception as e:
            return ValidationResult(
                name="Relation Counts",
                passed=False,
                message=f"Query failed: {e}"
            )

    def check_orphan_nodes(self) -> ValidationResult:
        """Check for orphan nodes (nodes without relations)"""
        try:
            driver = self.get_driver()
            with driver.session() as session:
                result = session.run("""
                    MATCH (n)
                    WHERE NOT (n)--()
                    RETURN labels(n)[0] AS label, n.name AS name
                    LIMIT 20
                """)
                orphans = [{"label": r["label"], "name": r["name"]} for r in result]

                # Also get total orphan count
                count_result = session.run("""
                    MATCH (n)
                    WHERE NOT (n)--()
                    RETURN count(n) AS count
                """)
                total_orphans = count_result.single()["count"]

                passed = total_orphans == 0
                message = f"No orphan nodes" if passed else f"Found {total_orphans} orphan nodes"

                return ValidationResult(
                    name="Orphan Nodes",
                    passed=passed,
                    message=message,
                    details={"total": total_orphans, "samples": orphans}
                )
        except Exception as e:
            return ValidationResult(
                name="Orphan Nodes",
                passed=False,
                message=f"Query failed: {e}"
            )

    def check_disease_completeness(self) -> ValidationResult:
        """Check if diseases have required relations"""
        try:
            driver = self.get_driver()
            with driver.session() as session:
                # Diseases without symptoms
                result = session.run("""
                    MATCH (d:Disease)
                    WHERE NOT (d)-[:HAS_SYMPTOM]->()
                    RETURN d.name AS name
                    LIMIT 10
                """)
                no_symptoms = [r["name"] for r in result]

                # Diseases without departments
                result = session.run("""
                    MATCH (d:Disease)
                    WHERE NOT (d)-[:BELONGS_TO_DEPARTMENT]->()
                    RETURN d.name AS name
                    LIMIT 10
                """)
                no_departments = [r["name"] for r in result]

                # Total disease count
                result = session.run("MATCH (d:Disease) RETURN count(d) AS count")
                total_diseases = result.single()["count"]

                passed = len(no_symptoms) == 0 and len(no_departments) == 0
                message = f"All {total_diseases} diseases have symptoms and departments" if passed else \
                    f"Incomplete: {len(no_symptoms)} without symptoms, {len(no_departments)} without departments"

                return ValidationResult(
                    name="Disease Completeness",
                    passed=passed,
                    message=message,
                    details={
                        "total_diseases": total_diseases,
                        "without_symptoms": no_symptoms,
                        "without_departments": no_departments
                    }
                )
        except Exception as e:
            return ValidationResult(
                name="Disease Completeness",
                passed=False,
                message=f"Query failed: {e}"
            )

    def check_sample_queries(self) -> ValidationResult:
        """Test sample queries work correctly"""
        try:
            driver = self.get_driver()
            with driver.session() as session:
                # Query 1: Get disease symptoms
                result = session.run("""
                    MATCH (d:Disease)-[:HAS_SYMPTOM]->(s:Symptom)
                    RETURN d.name AS disease, collect(s.name) AS symptoms
                    LIMIT 1
                """)
                record = result.single()
                query1_works = record is not None

                # Query 2: Get symptom diseases
                result = session.run("""
                    MATCH (s:Symptom)<-[:HAS_SYMPTOM]-(d:Disease)
                    RETURN s.name AS symptom, collect(d.name) AS diseases
                    LIMIT 1
                """)
                record = result.single()
                query2_works = record is not None

                passed = query1_works and query2_works
                message = "Sample queries executed successfully" if passed else "Some queries failed"

                return ValidationResult(
                    name="Sample Queries",
                    passed=passed,
                    message=message,
                    details={
                        "disease_symptoms_query": query1_works,
                        "symptom_diseases_query": query2_works
                    }
                )
        except Exception as e:
            return ValidationResult(
                name="Sample Queries",
                passed=False,
                message=f"Query failed: {e}"
            )

    def validate_all(self) -> list[ValidationResult]:
        """
        Run all validation checks

        Returns:
            List of validation results
        """
        logger.info("[VALIDATE] Starting full validation")

        checks = [
            self.check_connection,
            self.check_node_counts,
            self.check_relation_counts,
            self.check_orphan_nodes,
            self.check_disease_completeness,
            self.check_sample_queries,
        ]

        results = []
        for check in checks:
            result = check()
            results.append(result)
            status = "[PASS]" if result.passed else "[FAIL]"
            logger.info(f"[VALIDATE] {status} {result.name}: {result.message}")

        return results

    def print_report(self, results: list[ValidationResult]):
        """Print validation report"""
        print("\n" + "=" * 60)
        print("KNOWLEDGE GRAPH VALIDATION REPORT")
        print(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print("=" * 60)

        passed_count = sum(1 for r in results if r.passed)
        total_count = len(results)

        for result in results:
            status = "✅ PASS" if result.passed else "❌ FAIL"
            print(f"\n{status} | {result.name}")
            print(f"       {result.message}")

            if result.details:
                for key, value in result.details.items():
                    if isinstance(value, dict):
                        print(f"       {key}:")
                        for k, v in value.items():
                            print(f"         {k}: {v}")
                    elif isinstance(value, list) and value:
                        print(f"       {key}: {value[:5]}{'...' if len(value) > 5 else ''}")
                    else:
                        print(f"       {key}: {value}")

        print("\n" + "=" * 60)
        print(f"SUMMARY: {passed_count}/{total_count} checks passed")
        if passed_count == total_count:
            print("STATUS: ✅ ALL VALIDATIONS PASSED")
        else:
            print("STATUS: ❌ SOME VALIDATIONS FAILED")
        print("=" * 60)

    def generate_report_dict(self, results: list[ValidationResult]) -> dict:
        """Generate report as dictionary"""
        return {
            "timestamp": datetime.now().isoformat(),
            "passed": sum(1 for r in results if r.passed),
            "total": len(results),
            "all_passed": all(r.passed for r in results),
            "checks": [
                {
                    "name": r.name,
                    "passed": r.passed,
                    "message": r.message,
                    "details": r.details
                }
                for r in results
            ]
        }


def main():
    import argparse

    if sys.platform == "win32":
        sys.stdout.reconfigure(encoding="utf-8")

    parser = argparse.ArgumentParser(description="Knowledge Graph Validator")
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output report as JSON"
    )

    args = parser.parse_args()

    validator = GraphValidator()

    try:
        results = validator.validate_all()

        if args.json:
            import json
            report = validator.generate_report_dict(results)
            print(json.dumps(report, indent=2, ensure_ascii=False))
        else:
            validator.print_report(results)

    finally:
        validator.close()


if __name__ == "__main__":
    main()
