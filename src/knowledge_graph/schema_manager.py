"""
Neo4j Schema Manager
Handles schema initialization, validation, and Cypher script generation.
"""

import sys
from pathlib import Path
from datetime import datetime

# Ensure project root is in sys.path
_project_root = Path(__file__).parent.parent.parent.resolve()
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from config.settings import settings
from config.paths import LOGS_DIR
from src.common.logger import setup_logger
from src.knowledge_graph.schema import (
    NodeType,
    RelationType,
    NODE_SCHEMAS,
    RELATION_SCHEMAS,
    generate_constraint_cypher,
    generate_index_cypher,
    generate_full_schema_cypher,
)

logger = setup_logger(__name__, "schema_manager.log")


class SchemaManager:
    """
    Neo4j Schema Manager

    Manages schema initialization, validation, and Cypher script export.

    Usage:
        >>> manager = SchemaManager()
        >>> manager.initialize_schema()  # Create constraints and indexes
        >>> manager.export_cypher("schema.cypher")  # Export to file
        >>> manager.validate_schema()  # Verify schema exists
    """

    def __init__(self):
        """Initialize schema manager"""
        self.constraints_created = 0
        self.indexes_created = 0

    def get_neo4j_driver(self):
        """Get Neo4j driver (lazy import to avoid dependency if not needed)"""
        try:
            from neo4j import GraphDatabase
            driver = GraphDatabase.driver(
                settings.neo4j_uri,
                auth=(settings.neo4j_user, settings.neo4j_password)
            )
            return driver
        except ImportError:
            logger.error("[ERROR] neo4j package not installed. Run: pip install neo4j")
            raise
        except Exception as e:
            logger.error(f"[ERROR] Failed to connect to Neo4j: {e}")
            raise

    def initialize_schema(self, dry_run: bool = False) -> dict:
        """
        Initialize Neo4j schema (constraints and indexes)

        Args:
            dry_run: If True, only print Cypher without executing

        Returns:
            dict with creation statistics
        """
        logger.info("[SCHEMA] Starting schema initialization")

        constraints = generate_constraint_cypher()
        indexes = generate_index_cypher()

        if dry_run:
            print("\n[DRY RUN] Constraints to create:")
            for stmt in constraints:
                print(f"  {stmt[:60]}...")

            print("\n[DRY RUN] Indexes to create:")
            for stmt in indexes:
                print(f"  {stmt[:60]}...")

            return {
                "constraints": len(constraints),
                "indexes": len(indexes),
                "dry_run": True
            }

        # Connect to Neo4j
        driver = self.get_neo4j_driver()

        try:
            with driver.session() as session:
                # Create constraints
                for stmt in constraints:
                    try:
                        session.run(stmt)
                        self.constraints_created += 1
                        logger.debug(f"[SCHEMA] Created constraint: {stmt[:50]}...")
                    except Exception as e:
                        if "already exists" in str(e).lower():
                            logger.debug(f"[SCHEMA] Constraint already exists")
                        else:
                            logger.warning(f"[SCHEMA] Failed to create constraint: {e}")

                # Create indexes
                for stmt in indexes:
                    try:
                        session.run(stmt)
                        self.indexes_created += 1
                        logger.debug(f"[SCHEMA] Created index: {stmt[:50]}...")
                    except Exception as e:
                        if "already exists" in str(e).lower():
                            logger.debug(f"[SCHEMA] Index already exists")
                        else:
                            logger.warning(f"[SCHEMA] Failed to create index: {e}")

        finally:
            driver.close()

        result = {
            "constraints": self.constraints_created,
            "indexes": self.indexes_created,
            "dry_run": False
        }

        logger.info(f"[SCHEMA] Schema initialized: {self.constraints_created} constraints, {self.indexes_created} indexes")
        return result

    def validate_schema(self) -> dict:
        """
        Validate that schema exists in Neo4j

        Returns:
            dict with validation results
        """
        logger.info("[VALIDATE] Starting schema validation")

        driver = self.get_neo4j_driver()

        try:
            with driver.session() as session:
                # Check constraints
                result = session.run("CALL db.constraints()")
                constraints = [record.data() for record in result]
                constraint_labels = {c.get("labelsOrTypes", [""])[0] for c in constraints}

                # Check indexes
                result = session.run("CALL db.indexes()")
                indexes = [record.data() for record in result]
                index_labels = {i.get("labelsOrTypes", [""])[0] for i in indexes}

                # Validate expected nodes have constraints
                expected_labels = {schema.label for schema in NODE_SCHEMAS.values() if schema.unique_constraint}
                missing_constraints = expected_labels - constraint_labels

                validation = {
                    "total_constraints": len(constraints),
                    "total_indexes": len(indexes),
                    "expected_constraints": len(expected_labels),
                    "missing_constraints": list(missing_constraints),
                    "valid": len(missing_constraints) == 0
                }

                if validation["valid"]:
                    logger.info("[VALIDATE] Schema validation passed")
                else:
                    logger.warning(f"[VALIDATE] Missing constraints: {missing_constraints}")

                return validation

        finally:
            driver.close()

    def export_cypher(self, output_path: str | Path | None = None) -> str:
        """
        Export schema as Cypher script

        Args:
            output_path: Optional file path to save the script

        Returns:
            Cypher script as string
        """
        cypher = generate_full_schema_cypher()

        if output_path:
            output_path = Path(output_path)
            output_path.parent.mkdir(parents=True, exist_ok=True)
            with open(output_path, "w", encoding="utf-8") as f:
                f.write(cypher)
            logger.info(f"[EXPORT] Schema exported to {output_path}")

        return cypher

    def print_schema_summary(self):
        """Print schema summary to console"""
        print("\n" + "=" * 60)
        print("KNOWLEDGE GRAPH SCHEMA SUMMARY")
        print("=" * 60)

        print(f"\n[NODE TYPES] {len(NodeType)} types")
        for nt in NodeType:
            schema = NODE_SCHEMAS[nt]
            props = ", ".join(schema.properties.keys())
            print(f"  :{nt.value} {{{props}}}")

        print(f"\n[RELATION TYPES] {len(RelationType)} types")
        for rt in RelationType:
            schema = RELATION_SCHEMAS[rt]
            props = ", ".join(schema.properties.keys()) if schema.properties else "no properties"
            print(f"  ({schema.start_node.value})-[:{rt.value}]->({schema.end_node.value}) {{{props}}}")

        print(f"\n[CONSTRAINTS] {len(generate_constraint_cypher())} unique constraints")
        print(f"[INDEXES] {len(generate_index_cypher())} indexes")

        print("\n" + "=" * 60)

    def clear_schema(self, confirm: bool = False) -> bool:
        """
        Clear all constraints and indexes (DANGEROUS!)

        Args:
            confirm: Must be True to proceed

        Returns:
            True if cleared successfully
        """
        if not confirm:
            logger.warning("[CLEAR] Set confirm=True to clear schema")
            return False

        logger.warning("[CLEAR] Clearing all constraints and indexes!")

        driver = self.get_neo4j_driver()

        try:
            with driver.session() as session:
                # Drop all constraints
                result = session.run("CALL db.constraints()")
                for record in result:
                    name = record.get("name")
                    if name:
                        session.run(f"DROP CONSTRAINT {name} IF EXISTS")
                        logger.info(f"[CLEAR] Dropped constraint: {name}")

                # Drop all indexes (except system indexes)
                result = session.run("CALL db.indexes()")
                for record in result:
                    name = record.get("name")
                    if name and not name.startswith("_"):
                        session.run(f"DROP INDEX {name} IF EXISTS")
                        logger.info(f"[CLEAR] Dropped index: {name}")

            logger.info("[CLEAR] Schema cleared")
            return True

        finally:
            driver.close()


# ============================================================
# Main: CLI Entry Point
# ============================================================

def main():
    import argparse

    if sys.platform == "win32":
        sys.stdout.reconfigure(encoding="utf-8")

    parser = argparse.ArgumentParser(description="Neo4j Schema Manager")
    parser.add_argument(
        "action",
        choices=["init", "validate", "export", "summary", "clear"],
        help="Action to perform"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print Cypher without executing (for init)"
    )
    parser.add_argument(
        "--output",
        type=str,
        default="scripts/schema.cypher",
        help="Output file for export (default: scripts/schema.cypher)"
    )
    parser.add_argument(
        "--confirm",
        action="store_true",
        help="Confirm destructive action (for clear)"
    )

    args = parser.parse_args()

    manager = SchemaManager()

    if args.action == "init":
        result = manager.initialize_schema(dry_run=args.dry_run)
        print(f"\n[RESULT] {result}")

    elif args.action == "validate":
        result = manager.validate_schema()
        print(f"\n[RESULT] {result}")

    elif args.action == "export":
        cypher = manager.export_cypher(args.output)
        print(f"\n[EXPORT] Saved to {args.output}")
        print(f"[EXPORT] Script length: {len(cypher)} characters")

    elif args.action == "summary":
        manager.print_schema_summary()

    elif args.action == "clear":
        if args.confirm:
            manager.clear_schema(confirm=True)
        else:
            print("[ERROR] Use --confirm to clear schema")


if __name__ == "__main__":
    main()
