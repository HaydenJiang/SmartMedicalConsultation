"""
Vector Store Module
Provides semantic search using FAISS and hybrid search with Neo4j.
"""

from .search import VectorRetriever

__all__ = ["VectorRetriever"]
