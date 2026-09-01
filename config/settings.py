"""
Global Configuration Module
Reads configuration from .env file using pydantic_settings
"""

from pathlib import Path
from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# .env 锚定在项目根目录查找，不依赖运行时工作目录
# （从 scripts/、IDE 或其他 CWD 启动时都能读到同一份配置）
_PROJECT_ROOT = Path(__file__).parent.parent.resolve()


class Settings(BaseSettings):
    """
    Application settings loaded from environment variables and .env file.

    All settings can be overridden via environment variables or .env file.
    优先级：系统环境变量 > .env 文件 > 字段默认值。
    生产部署建议用环境变量/云密钥服务注入，不在服务器上放置 .env 文件。
    """

    model_config = SettingsConfigDict(
        env_file=str(_PROJECT_ROOT / ".env"),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ===== LLM Configuration =====
    model_base_url: str = Field(
        default="https://dashscope.aliyuncs.com/compatible-mode/v1",
        description="LLM API base URL (DashScope compatible with OpenAI)"
    )
    model_api_key: str = Field(
        default="",
        description="LLM API key (DashScope API Key)"
    )
    model_name: str = Field(
        # default="qwen-plus",
        default="qwen3.7-max-2026-06-08",
        description="LLM model name"
    )
    llm_enable_thinking: bool = Field(
        default=False,
        description="是否启用 qwen3 系列混合思考模型的 reasoning(思考)模式。"
                    "本系统多数 LLM 调用为意图分类/症状抽取/科室与用药择优等结构化小任务，"
                    "默认关闭思考可大幅降低单次延迟(常见 5-20s → 1-3s)与 token 消耗；"
                    "如需复杂医学推理，可在 .env 设为 true。对非 qwen3 模型此参数被服务端忽略，无副作用。"
    )
    llm_max_retries: int = Field(
        default=1,
        description="LLM 调用失败重试次数。延迟敏感路径建议 ≤1，避免慢调用重试导致耗时翻倍。"
    )

    # ===== Extraction LLM Configuration（微调模型，仅用于实体/关系抽取）=====
    # base_url 留空则抽取任务回退到主 LLM，行为与改动前完全一致
    extraction_model_base_url: str = Field(
        default="",
        description="微调模型 vLLM 服务地址（如 http://192.168.122.3:8000/v1）。"
                    "留空=不启用，实体/关系抽取仍走主 LLM"
    )
    extraction_model_api_key: str = Field(
        default="EMPTY",
        description="vLLM 服务不校验密钥，固定填 EMPTY"
    )
    extraction_model_name: str = Field(
        default="qwen2.5-merged",
        description="vLLM --served-model-name 指定的模型名"
    )

    # ===== Neo4j Configuration =====
    neo4j_uri: str = Field(
        default="bolt://localhost:7687",
        description="Neo4j database connection URI"
    )
    neo4j_user: str = Field(
        default="neo4j",
        description="Neo4j username"
    )
    neo4j_password: str = Field(
        default="12345678",
        description="Neo4j password"
    )

    # ===== Embedding Model Configuration =====
    embedding_model_path: str = Field(
        default="models/bge-m3",
        description="Local path to BGE-M3 embedding model (relative to project root or absolute)"
    )

    # ===== Conversation History Storage（Redis 热缓存 + MySQL 冷存储）=====
    redis_url: str = Field(
        default="redis://localhost:6379/0",
        description="Redis URL for session hot cache"
    )
    mysql_host: str = Field(default="localhost", description="MySQL host")
    mysql_port: int = Field(default=3306, description="MySQL port")
    mysql_user: str = Field(default="root", description="MySQL user")
    mysql_password: str = Field(default="123456", description="MySQL password")
    mysql_database: str = Field(default="smc_history", description="MySQL database for conversation history")

    # ===== Logging Configuration =====
    log_level: str = Field(
        default="INFO",
        description="Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL)"
    )

    # ===== Application Configuration =====
    app_name: str = Field(
        default="SmartMedicalConsultation",
        description="Application name"
    )
    app_version: str = Field(
        default="1.0.0",
        description="Application version"
    )
    api_port: int = Field(
        default=8000,
        description="FastAPI server port"
    )

    # ===== Agent Configuration =====
    enable_react_layer: bool = Field(
        default=True,
        description="医学知识分支是否在『强制检索』之上再启用可选 ReAct 多跳层（tool-calling）。"
                    "强制检索是 grounding 底线、必走；ReAct 仅作多跳补充与工具调用演示。关闭则纯强制检索，更快更省。"
    )

    # ===== Entity Linking Configuration =====
    entity_link_threshold: float = Field(
        default=0.85,
        description="实体链接相似度阈值（归一化余弦）。仅 ≥ 阈值 的图谱实体视为成功链接，"
                    "过高漏链、过低误链，可按 evals 结果调优。"
    )
    entity_link_top_k: int = Field(
        default=3,
        description="实体链接时每个输入词在 FAISS 中考察的候选数"
    )

    # ===== Text2Cypher Configuration =====
    text2cypher_enabled: bool = Field(
        default=True,
        description="是否为 ReAct 层提供 natural_language_graph_query 工具（LLM 生成只读 Cypher 查图谱）。"
                    "需同时开启 enable_react_layer 才生效。"
    )
    text2cypher_max_records: int = Field(
        default=50,
        description="Text2Cypher 单次查询返回的最大记录数（驱动层截断，防全表扫描）"
    )


@lru_cache()
def get_settings() -> Settings:
    """
    Get cached settings instance.
    Using lru_cache ensures we only load settings once.
    """
    return Settings()


# Global settings instance
settings = get_settings()
