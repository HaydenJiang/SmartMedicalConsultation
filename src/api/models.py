"""
API Request/Response Models
Pydantic models for API endpoints.
"""

from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime


# ============================================================
# Request Models
# ============================================================

class ConsultationRequest(BaseModel):
    """Consultation request model"""
    query: str = Field(..., description="User question", min_length=1, max_length=1000)
    session_id: str = Field(default="default", description="Session ID for tracking")

    class Config:
        json_schema_extra = {
            "example": {
                "query": "我最近头痛、头晕，应该挂什么科？",
                "session_id": "user123_session1"
            }
        }


# ============================================================
# Response Models
# ============================================================

class ConsultationResponse(BaseModel):
    """Consultation response model"""
    answer: str = Field(..., description="AI generated answer")
    intent: str = Field(default="", description="Detected intent type")
    symptoms: list[str] = Field(default_factory=list, description="Detected symptoms")
    departments: list[str] = Field(default_factory=list, description="Recommended departments")
    medications: list[dict] = Field(default_factory=list, description="Medication advice")
    disclaimers: list[str] = Field(default_factory=list, description="Medical disclaimers")
    warnings: list[str] = Field(default_factory=list, description="Emergency warnings")
    linked_entities: list[dict] = Field(
        default_factory=list,
        description="实体链接结果：用户口语词 → 图谱规范实体 "
                    "[{input_entity, matched_entity, type, similarity}]"
    )
    duration_ms: int = Field(default=0, description="Processing time in milliseconds")
    timestamp: str = Field(default_factory=lambda: datetime.now().isoformat())


class HealthResponse(BaseModel):
    """Health check response model"""
    status: str = Field(..., description="Service status: healthy/degraded/unhealthy")
    neo4j_connected: bool = Field(default=False, description="Neo4j connection status")
    vector_index_loaded: bool = Field(default=False, description="Vector index status")
    agent_system_ready: bool = Field(default=False, description="Agent system status")
    version: str = Field(default="1.0.0")
    timestamp: str = Field(default_factory=lambda: datetime.now().isoformat())


class StatsResponse(BaseModel):
    """System statistics response model"""
    knowledge_graph: dict = Field(default_factory=dict, description="Knowledge graph stats")
    vector_index: dict = Field(default_factory=dict, description="Vector index stats")
    api: dict = Field(default_factory=dict, description="API stats")
    timestamp: str = Field(default_factory=lambda: datetime.now().isoformat())


class ErrorResponse(BaseModel):
    """Error response model"""
    error: str = Field(..., description="Error message")
    detail: Optional[str] = Field(default=None, description="Error detail")
    timestamp: str = Field(default_factory=lambda: datetime.now().isoformat())


# ============================================================
# Conversation History Models（对话历史管理，§6 企业方案）
# ============================================================

class ConversationItem(BaseModel):
    """Conversation list item"""
    id: str = Field(..., description="对话 ID（= 前端 session_id）")
    title: str = Field(default="", description="对话标题（首问截断）")
    created_at: str = Field(default="", description="创建时间")
    updated_at: str = Field(default="", description="最后更新时间")


class ConversationListResponse(BaseModel):
    """Conversation list response"""
    conversations: list[ConversationItem] = Field(default_factory=list, description="按 updated_at 倒序")


class MessageItem(BaseModel):
    """Single message of a conversation"""
    role: str = Field(..., description="user / assistant")
    content: str = Field(..., description="消息内容")
    intent: str = Field(default="", description="意图类型")
    created_at: str = Field(default="", description="写入时间")


class ConversationDetailResponse(BaseModel):
    """Conversation detail response"""
    conversation_id: str = Field(..., description="对话 ID")
    messages: list[MessageItem] = Field(default_factory=list, description="按时间正序")


class DeleteConversationResponse(BaseModel):
    """Delete conversation response"""
    deleted: str = Field(..., description="被删除的对话 ID")
