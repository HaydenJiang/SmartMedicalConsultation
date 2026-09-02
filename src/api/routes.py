"""
API Routes
FastAPI router with consultation, health, and stats endpoints.
Includes timeout handling, concurrency control, and request logging.
"""

import json
import sys
import time
import asyncio
from pathlib import Path
from datetime import datetime

_project_root = Path(__file__).parent.parent.parent.resolve()
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse

from src.common.logger import setup_logger
from src.history.store import history_store
from src.api.models import (
    ConsultationRequest,
    ConsultationResponse,
    HealthResponse,
    StatsResponse,
    ErrorResponse,
    ConversationListResponse,
    ConversationDetailResponse,
    DeleteConversationResponse
)

logger = setup_logger(__name__, "api.log")

router = APIRouter()

# Timeout configuration
# 安全上限：典型轮次 2-8s；带记忆+多 Agent+LLM 兜底的轮次偶有更慢，故放宽上限。
# 真正的体验优化应走流式输出（见 §5.4 性能优化），此处仅为防失控的天花板。
REQUEST_TIMEOUT = 60  # seconds


# ============================================================
# Request Logging Helper
# ============================================================

def log_request(
    query: str,
    intent: str,
    duration_ms: int,
    has_disclaimer: bool,
    success: bool
):
    """Log request details for monitoring"""
    status = "✅" if success else "❌"
    logger.info(
        f"[REQUEST] {status} "
        f"query='{query[:30]}...' | "
        f"intent={intent} | "
        f"duration={duration_ms}ms | "
        f"disclaimer={'Y' if has_disclaimer else 'N'}"
    )


# ============================================================
# POST /api/consult - Consultation Endpoint
# ============================================================

@router.post(
    "/consult",
    response_model=ConsultationResponse,
    responses={
        500: {"model": ErrorResponse},
        503: {"model": ErrorResponse},
        504: {"model": ErrorResponse}
    },
    tags=["问诊"],
    summary="智慧问诊接口",
    description="接收用户问题，返回 AI 生成的医疗建议（30秒超时，5并发限制）"
)
async def consult(req: ConsultationRequest):
    """
    Process user consultation request

    - Accepts user question
    - Runs through Agent system with timeout and concurrency control
    - Returns medical advice with disclaimers
    """
    from src.api.main import app_state

    # Check if agent system is ready
    if not app_state.agent_system_ready:
        raise HTTPException(
            status_code=503,
            detail="Agent system not ready. Please try again later."
        )

    start_time = time.time()
    app_state.total_requests += 1

    logger.info(f"[API] Consultation request: '{req.query[:50]}...' (session: {req.session_id})")

    try:
        # Acquire semaphore for concurrency control
        async with app_state.request_semaphore:
            # Call Agent system with timeout
            from src.agents.graph import run

            # 加载多轮上下文（三级命中：Redis 热缓存 → MySQL 回填）
            history = history_store.load_context(req.session_id)

            try:
                # Run in thread pool to not block event loop
                result = await asyncio.wait_for(
                    asyncio.get_event_loop().run_in_executor(
                        None, run, req.query, history
                    ),
                    timeout=REQUEST_TIMEOUT
                )

                duration_ms = int((time.time() - start_time) * 1000)

                # Build response
                disclaimers = result.get("disclaimers", [])
                response = ConsultationResponse(
                    answer=result.get("final_answer", ""),
                    intent=result.get("intent", ""),
                    symptoms=result.get("symptoms", []),
                    departments=result.get("departments", []),
                    medications=result.get("medications", []),
                    disclaimers=disclaimers,
                    warnings=result.get("warnings", []),
                    linked_entities=result.get("linked_entities", []),
                    duration_ms=duration_ms
                )

                # Log request
                log_request(
                    query=req.query,
                    intent=response.intent,
                    duration_ms=duration_ms,
                    has_disclaimer=len(disclaimers) > 0,
                    success=True
                )

                # 双写对话历史（先 MySQL 再 Redis；任一失败降级，不使请求失败）
                history_store.persist_turn(req.session_id, "user", req.query)
                history_store.persist_turn(
                    req.session_id, "assistant", response.answer, intent=response.intent
                )

                return response

            except asyncio.TimeoutError:
                duration_ms = int((time.time() - start_time) * 1000)
                app_state.total_errors += 1

                log_request(
                    query=req.query,
                    intent="timeout",
                    duration_ms=duration_ms,
                    has_disclaimer=False,
                    success=False
                )

                raise HTTPException(
                    status_code=504,
                    detail=f"Request timeout after {REQUEST_TIMEOUT}s. Please try a simpler question."
                )

    except HTTPException:
        raise
    except Exception as e:
        duration_ms = int((time.time() - start_time) * 1000)
        app_state.total_errors += 1

        log_request(
            query=req.query,
            intent="error",
            duration_ms=duration_ms,
            has_disclaimer=False,
            success=False
        )

        logger.error(f"[API] Consultation failed: {e}")

        err_answer = "抱歉，系统暂时无法处理您的请求。请稍后重试，或拨打医疗咨询热线 12320。"
        # 记录本轮，避免上下文断裂
        history_store.persist_turn(req.session_id, "user", req.query)
        history_store.persist_turn(req.session_id, "assistant", err_answer, intent="error")

        # Return friendly error
        return ConsultationResponse(
            answer=err_answer,
            intent="error",
            disclaimers=["🔴 重要声明：本建议仅供参考，不能替代专业医疗诊断。"],
            duration_ms=duration_ms
        )


# ============================================================
# POST /api/consult/stream - Streaming Consultation Endpoint (SSE)
# ============================================================

# 流结束哨兵：next(gen, _STREAM_DONE) 避免 StopIteration 穿越线程边界
# 进入 async 生成器（PEP 479 会把 async 生成器内的 StopIteration 转为 RuntimeError）
_STREAM_DONE = object()


def _sse_format(data: str, event: str | None = None) -> str:
    """把一条消息格式化为 SSE 帧：event:/data: 行 + 空行结尾（WHATWG SSE 规范）。"""
    lines = []
    if event is not None:
        lines.append(f"event: {event}")
    for line in data.splitlines() or [""]:
        lines.append(f"data: {line}")
    return "\n".join(lines) + "\n\n"


def _facts_from_delta(delta: dict) -> dict:
    """从节点 state 增量中提取可展示给用户的部分事实（progress 帧用）。"""
    facts = {}
    if delta.get("intent"):
        facts["intent"] = delta["intent"]
    if delta.get("symptoms"):
        facts["symptoms"] = delta["symptoms"]
    if delta.get("departments"):
        facts["departments"] = delta["departments"]
    if delta.get("linked_entities"):
        facts["linked_entities"] = [lk.get("matched_entity") for lk in delta["linked_entities"]]
    if delta.get("needs_clarification"):
        facts["needs_clarification"] = True
    return facts


def _build_response_from_state(state: dict, start_time: float) -> ConsultationResponse:
    """从终态构建标准响应（/consult 与 /consult/stream 共用字段口径）。"""
    return ConsultationResponse(
        answer=state.get("final_answer", ""),
        intent=state.get("intent", ""),
        symptoms=state.get("symptoms", []),
        departments=state.get("departments", []),
        medications=state.get("medications", []),
        disclaimers=state.get("disclaimers", []),
        warnings=state.get("warnings", []),
        linked_entities=state.get("linked_entities", []),
        duration_ms=int((time.time() - start_time) * 1000),
    )


@router.post(
    "/consult/stream",
    tags=["问诊"],
    summary="流式问诊接口（SSE）",
    description="与 /consult 相同的结果，但以 Server-Sent Events 流式推送："
                "event: progress（每个 Agent 节点完成的进度）→ event: answer（完整响应 JSON）"
                "→ event: done（[DONE] 结束标记）。客户端断开时提前终止。"
)
async def consult_stream(req: ConsultationRequest, request: Request):
    """SSE 流式问诊。

    桥接设计：LangGraph app.stream 是同步生成器，本端点是 async def。
    用 asyncio.to_thread(lambda: next(gen, _STREAM_DONE)) 逐个取值——
    每个节点一次线程调度，既能在每步之间检查客户端断开，又不长时间占用线程池。
    """
    from src.api.main import app_state

    if not app_state.agent_system_ready:
        raise HTTPException(
            status_code=503,
            detail="Agent system not ready. Please try again later."
        )

    start_time = time.time()
    app_state.total_requests += 1
    logger.info(f"[API] Streaming consultation request: '{req.query[:50]}...' (session: {req.session_id})")

    async def event_generator():
        from src.agents.graph import run_stream, NODE_LABELS_ZH

        final_state = None
        try:
            async with app_state.request_semaphore:
                history = history_store.load_context(req.session_id)
                gen = run_stream(req.query, history)
                while True:
                    # 先查客户端断开，再取下一块
                    if await request.is_disconnected():
                        logger.info("[API] Stream client disconnected, stopping early")
                        return
                    try:
                        chunk = await asyncio.wait_for(
                            asyncio.to_thread(lambda: next(gen, _STREAM_DONE)),
                            timeout=REQUEST_TIMEOUT,
                        )
                    except asyncio.TimeoutError:
                        app_state.total_errors += 1
                        logger.error(f"[API] Stream timeout after {REQUEST_TIMEOUT}s")
                        yield _sse_format(
                            json.dumps({"message": f"处理超时（{REQUEST_TIMEOUT}s），请简化问题后重试"},
                                       ensure_ascii=False),
                            event="error",
                        )
                        return
                    if chunk is _STREAM_DONE:
                        break

                    kind = chunk[0]
                    if kind == "progress":
                        _, node_name, delta = chunk
                        payload = {
                            "node": node_name,
                            "label": NODE_LABELS_ZH.get(node_name, node_name),
                            "facts": _facts_from_delta(delta),
                        }
                        yield _sse_format(json.dumps(payload, ensure_ascii=False), event="progress")
                    else:  # kind == "values"：完整快照，最后一个即终态
                        final_state = chunk[1]
        except Exception as e:
            app_state.total_errors += 1
            logger.error(f"[API] Streaming consultation failed: {e}")
            yield _sse_format(
                json.dumps({"message": f"系统错误：{e}"}, ensure_ascii=False),
                event="error",
            )
            return

        # 终答帧：与 /consult 同口径的完整响应
        if final_state is not None:
            response = _build_response_from_state(final_state, start_time)
            log_request(
                query=req.query,
                intent=response.intent,
                duration_ms=response.duration_ms,
                has_disclaimer=len(response.disclaimers) > 0,
                success=True,
            )
            # 双写对话历史（与 /consult 一致）
            history_store.persist_turn(req.session_id, "user", req.query)
            history_store.persist_turn(
                req.session_id, "assistant", response.answer, intent=response.intent
            )
            yield _sse_format(response.model_dump_json(), event="answer")

        yield _sse_format("[DONE]", event="done")

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # 防反向代理（Nginx 等）缓冲 SSE
        },
    )


# ============================================================
# GET /api/health - Health Check Endpoint
# ============================================================

@router.get(
    "/health",
    response_model=HealthResponse,
    tags=["系统"],
    summary="健康检查",
    description="检查服务状态、Neo4j 连接、模型加载状态"
)
async def health():
    """
    Health check endpoint

    Returns status of all system components.
    """
    from src.api.main import app_state

    # Determine overall status
    if app_state.agent_system_ready and app_state.vector_index_ready and app_state.neo4j_ready:
        status = "healthy"
    elif app_state.agent_system_ready:
        status = "degraded"
    else:
        status = "unhealthy"

    return HealthResponse(
        status=status,
        neo4j_connected=app_state.neo4j_ready,
        vector_index_loaded=app_state.vector_index_ready,
        agent_system_ready=app_state.agent_system_ready
    )


# ============================================================
# GET /api/stats - System Statistics Endpoint
# ============================================================

@router.get(
    "/stats",
    response_model=StatsResponse,
    tags=["系统"],
    summary="系统统计",
    description="返回知识图谱、向量索引、API 统计信息"
)
async def stats():
    """
    System statistics endpoint

    Returns knowledge graph stats, vector index stats, and API stats.
    """
    from src.api.main import app_state

    # Knowledge graph stats
    kg_stats = {}
    try:
        from src.knowledge_graph.graph_queries import GraphQueries
        queries = GraphQueries()
        kg_data = queries.get_statistics()
        kg_stats = {
            "total_nodes": kg_data.get("total_nodes", 0),
            "total_relations": kg_data.get("total_relations", 0),
            "nodes_by_type": kg_data.get("nodes", {}),
            "relations_by_type": kg_data.get("relations", {}),
            "density": round(kg_data.get("density", 0), 2)
        }
        queries.close()
    except Exception as e:
        kg_stats = {"error": str(e)}

    # Vector index stats
    vi_stats = {}
    try:
        from config.paths import DATA_INDEXES_DIR
        import json

        index_file = DATA_INDEXES_DIR / "faiss.index"
        entities_file = DATA_INDEXES_DIR / "entities.json"

        if index_file.exists():
            import faiss
            index = faiss.read_index(str(index_file))
            vi_stats["total_vectors"] = index.ntotal
            vi_stats["dimension"] = index.d

        if entities_file.exists():
            with open(entities_file, encoding="utf-8") as f:
                entities = json.load(f)
            vi_stats["total_entities"] = len(entities)

    except Exception as e:
        vi_stats = {"error": str(e)}

    # API stats
    api_stats = {
        "version": "1.0.0",
        "total_requests": app_state.total_requests,
        "total_errors": app_state.total_errors,
        "concurrency_limit": 5,
        "request_timeout": REQUEST_TIMEOUT
    }

    return StatsResponse(
        knowledge_graph=kg_stats,
        vector_index=vi_stats,
        api=api_stats
    )


# ============================================================
# 对话历史管理（Redis 热缓存 + MySQL 冷存储，讲义 §6）
# 历史接口用 def 同步路由：FastAPI 自动放入线程池，匹配
# store 层"MySQL 每请求新开连接、用完即关"的连接管理约定。
# ============================================================

@router.get(
    "/conversations",
    response_model=ConversationListResponse,
    tags=["对话历史"],
    summary="对话历史列表",
    description="按 updated_at 倒序分页列出对话（LIMIT ≤ 200），读 MySQL"
)
def list_conversations(limit: int = 50):
    """对话历史列表（左侧历史栏数据源）"""
    return ConversationListResponse(
        conversations=history_store.list_conversations(limit=min(max(limit, 1), 200))
    )


@router.get(
    "/conversations/{conversation_id}",
    response_model=ConversationDetailResponse,
    tags=["对话历史"],
    summary="恢复单个对话",
    description="返回该对话全部消息（时间正序），读 MySQL"
)
def get_conversation(conversation_id: str):
    """恢复单个对话（单击历史栏项时调用）"""
    if not history_store.conversation_exists(conversation_id):
        raise HTTPException(status_code=404, detail="Conversation not found")
    return ConversationDetailResponse(
        conversation_id=conversation_id,
        messages=history_store.get_messages(conversation_id),
    )


@router.delete(
    "/conversations/{conversation_id}",
    response_model=DeleteConversationResponse,
    tags=["对话历史"],
    summary="删除对话",
    description="同步清空 MySQL 两表 + 对应 Redis key"
)
def delete_conversation(conversation_id: str):
    """删除对话（MySQL 与 Redis 同步清空）"""
    history_store.delete_conversation(conversation_id)
    return DeleteConversationResponse(deleted=conversation_id)
