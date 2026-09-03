"""
FAISS Index Builder
Builds vector index from knowledge graph entities using BGE-M3 embeddings.

Usage:
    python scripts/build_index.py
"""

import sys
import json
import time
from pathlib import Path

# Ensure project root is in sys.path
PROJECT_ROOT = Path(__file__).parent.parent.resolve()
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# Fix Windows console encoding
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")

import numpy as np
import faiss
from tqdm import tqdm

from config.settings import settings
from config.paths import DATA_KG_DIR, DATA_INDEXES_DIR
from src.common.logger import setup_logger

logger = setup_logger(__name__, "index_builder.log")


# ============================================================
# Paths
# ============================================================

ENTITIES_FILE = DATA_KG_DIR / "entities.json"
FAISS_INDEX_FILE = DATA_INDEXES_DIR / "faiss.index"
ENTITIES_MAPPING_FILE = DATA_INDEXES_DIR / "entities.json"


# ============================================================
# Embedding Model
# ============================================================

class EmbeddingModel:
    """BGE-M3 Embedding Model wrapper"""

    def __init__(self, model_path: str):
        self.model_path = model_path
        self.model = None

    def load(self):
        """Load the embedding model"""
        logger.info(f"[MODEL] Loading BGE-M3 from {self.model_path}")
        try:
            from sentence_transformers import SentenceTransformer
            self.model = SentenceTransformer(self.model_path)
            logger.info("[MODEL] BGE-M3 loaded successfully")
        except Exception as e:
            logger.error(f"[MODEL] Failed to load model: {e}")
            raise

    def encode(self, texts: list[str], batch_size: int = 32) -> np.ndarray:
        """Encode texts to embeddings"""
        if self.model is None:
            self.load()

        embeddings = self.model.encode(
            texts,
            batch_size=batch_size,
            show_progress_bar=True,
            normalize_embeddings=True  # Normalize for cosine similarity
        )
        return np.array(embeddings, dtype="float32")


# ============================================================
# Index Builder
# ============================================================

class IndexBuilder:
    """
    FAISS Index Builder using IndexIVFFlat (enterprise-level mainstream)

    IVF (Inverted File) index:
    - Clusters vectors into nlist clusters during training
    - Searches only nprobe nearest clusters during query
    - ~95% recall with 10-50x speedup vs brute force
    """

    def __init__(
        self,
        dimension: int = 1024,
        nlist: int = 100,
        nprobe: int = 10
    ):
        """
        Initialize the index builder

        Args:
            dimension: Embedding dimension (BGE-M3 = 1024)
            nlist: Number of clusters (use 1024 for large datasets)
            nprobe: Number of clusters to search (5-10% of nlist)
        """
        self.dimension = dimension
        self.nlist = nlist
        self.nprobe = nprobe
        self.index = None
        self.entities = []

    def build_index(self, embeddings: np.ndarray, entities: list[dict]):
        """
        Build FAISS IndexIVFFlat index

        Args:
            embeddings: N x dimension array of embeddings
            entities: List of entity dicts
        """
        num_vectors = embeddings.shape[0]
        logger.info(f"[BUILD] Building IndexIVFFlat: {num_vectors} vectors, dim={self.dimension}")

        # Adjust nlist if dataset is small
        actual_nlist = min(self.nlist, num_vectors // 2)
        if actual_nlist < self.nlist:
            logger.warning(f"[BUILD] Dataset small, using nlist={actual_nlist} instead of {self.nlist}")

        # Create quantizer (used for cluster assignment)
        quantizer = faiss.IndexFlatIP(self.dimension)

        # Create IVF index with inner product metric
        self.index = faiss.IndexIVFFlat(
            quantizer,
            self.dimension,
            actual_nlist,
            faiss.METRIC_INNER_PRODUCT
        )

        # Train the index (learns cluster centers)
        logger.info(f"[BUILD] Training index with {actual_nlist} clusters...")
        self.index.train(embeddings)

        # Add vectors to the index
        logger.info("[BUILD] Adding vectors to index...")
        self.index.add(embeddings)

        # Set search parameters
        self.index.nprobe = self.nprobe

        self.entities = entities

        logger.info(f"[BUILD] Index built: {self.index.ntotal} vectors, nprobe={self.nprobe}")

    def save(self, index_path: Path, entities_path: Path):
        """Save index and entity mapping to files"""
        index_path.parent.mkdir(parents=True, exist_ok=True)

        # Save FAISS index
        faiss.write_index(self.index, str(index_path))
        logger.info(f"[SAVE] FAISS index saved to {index_path}")

        # Save entity mapping
        with open(entities_path, "w", encoding="utf-8") as f:
            json.dump(self.entities, f, ensure_ascii=False, indent=2)
        logger.info(f"[SAVE] Entity mapping saved to {entities_path}")

    def test_search(self, query_embedding: np.ndarray, top_k: int = 5) -> list[dict]:
        """Test search with a query embedding"""
        distances, indices = self.index.search(query_embedding, top_k)

        results = []
        for idx, score in zip(indices[0], distances[0]):
            if idx < len(self.entities):
                entity = self.entities[idx].copy()
                entity["score"] = float(score)
                results.append(entity)

        return results


# ============================================================
# Main Logic
# ============================================================

def load_entities(entities_file: Path) -> list[dict]:
    """Load entities from knowledge graph JSON"""
    if not entities_file.exists():
        logger.error(f"[ERROR] Entities file not found: {entities_file}")
        return []

    with open(entities_file, "r", encoding="utf-8") as f:
        data = json.load(f)

    entities = data.get("entities", [])
    logger.info(f"[LOAD] Loaded {len(entities)} entities from {entities_file}")

    return entities


def prepare_texts(entities: list[dict]) -> tuple[list[str], list[dict]]:
    """
    Prepare texts for embedding and entity mapping

    Returns:
        (texts, entity_mapping)
    """
    texts = []
    entity_mapping = []

    for idx, entity in enumerate(entities):
        entity_type = entity.get("type", "")
        data = entity.get("data", {})

        # Build text based on entity type
        name = data.get("name", "")
        description = data.get("description", "")

        # Combine name and description for better embeddings
        if description:
            text = f"{name}。{description}"
        else:
            text = name

        if text.strip():
            texts.append(text)
            entity_mapping.append({
                "index": len(texts) - 1,
                "type": entity_type,
                "name": name,
                "data": data
            })

    logger.info(f"[PREPARE] Prepared {len(texts)} texts for embedding")
    return texts, entity_mapping


def main():
    print("=" * 60)
    print("FAISS INDEX BUILDER (IndexIVFFlat)")
    print("=" * 60)

    start_time = time.time()

    # 1. Load entities
    print("\n[STEP 1] Loading entities...")
    entities = load_entities(ENTITIES_FILE)
    if not entities:
        print("[ERROR] No entities to process")
        return

    # 2. Prepare texts
    print("\n[STEP 2] Preparing texts...")
    texts, entity_mapping = prepare_texts(entities)
    print(f"  Prepared {len(texts)} texts")

    # 3. Load embedding model and encode
    print("\n[STEP 3] Encoding texts with BGE-M3...")
    model = EmbeddingModel(settings.embedding_model_path)
    embeddings = model.encode(texts)
    print(f"  Generated embeddings: shape={embeddings.shape}")

    # 4. Build FAISS index
    print("\n[STEP 4] Building FAISS IndexIVFFlat...")
    builder = IndexBuilder(
        dimension=embeddings.shape[1],
        nlist=100,  # Use 1024 for larger datasets
        nprobe=10
    )
    builder.build_index(embeddings, entity_mapping)

    # 5. Save index
    print("\n[STEP 5] Saving index...")
    builder.save(FAISS_INDEX_FILE, ENTITIES_MAPPING_FILE)

    # 6. Test search
    print("\n[STEP 6] Testing search...")
    test_query = "高血压的症状"
    test_embedding = model.encode([test_query])
    results = builder.test_search(test_embedding, top_k=5)
    print(f"  Query: '{test_query}'")
    print(f"  Results:")
    for r in results:
        print(f"    - [{r['type']}] {r['name']} (score: {r['score']:.4f})")

    # 7. Statistics
    elapsed = time.time() - start_time
    print("\n" + "=" * 60)
    print("BUILD STATISTICS")
    print("=" * 60)
    print(f"  Total entities: {len(entities)}")
    print(f"  Indexed vectors: {builder.index.ntotal}")
    print(f"  Index type: IndexIVFFlat (nlist={builder.nlist}, nprobe={builder.nprobe})")
    print(f"  Build time: {elapsed:.2f}s")
    print(f"  Index file: {FAISS_INDEX_FILE}")
    print(f"  Mapping file: {ENTITIES_MAPPING_FILE}")
    print("=" * 60)

    print("\n[SUCCESS] Index build completed!")


if __name__ == "__main__":
    main()
