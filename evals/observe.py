"""
Observability hook (env-gated, no-op safe).

优先级：LANGFUSE_*  →  Langfuse；否则 LANGSMITH_TRACING  →  Langsmith（langchain 自动 trace）；
否则 no-op。离线评估（runner）与线上 API（day04）import 同一个 trace_span，即可共用一套 trace。
所有后端调用都 try/except 包裹，**绝不**因可观测失败而打断评估/请求；trace 通过 span.update(...)
携带 tool_calls / intent / latency 等元数据。
"""

import os
import contextlib

from src.common.logger import setup_logger

logger = setup_logger(__name__, "eval.log")


def _backend():
    """返回 (backend_name, handle)；不可用则 ('noop', None)。"""
    if os.getenv("LANGFUSE_PUBLIC_KEY") and os.getenv("LANGFUSE_SECRET_KEY"):
        try:
            from langfuse import Langfuse  # type: ignore
            return "langfuse", Langfuse()
        except Exception as e:
            logger.warning(f"[OBSERVE] Langfuse 初始化失败，降级 no-op：{e}")
    if os.getenv("LANGSMITH_TRACING", "").lower() in ("1", "true", "yes"):
        try:
            import langsmith  # type: ignore  # 设置该 env 后 langchain 调用会自动 trace
            return "langsmith", langsmith
        except Exception as e:
            logger.warning(f"[OBSERVE] Langsmith 不可用，降级 no-op：{e}")
    return "noop", None


class _Span:
    def __init__(self, backend, handle, name):
        self.backend = backend
        self.handle = handle
        self.name = name
        self.meta = {}

    def update(self, **kw):
        self.meta.update(kw)

    def flush(self):
        b, h = self.backend, self.handle
        if b == "noop" or h is None:
            return
        try:
            if b == "langfuse":
                try:
                    h.trace(name=self.name, metadata=self.meta)         # langfuse v2
                except Exception:
                    try:
                        h.create_trace(name=self.name, metadata=self.meta)  # langfuse v3
                    except Exception:
                        pass
            elif b == "langsmith":
                try:
                    from langsmith import Client  # type: ignore
                    Client().create_run(
                        name=self.name, run_type="chain",
                        inputs=self.meta.get("inputs", {}),
                        outputs=self.meta.get("outputs", {}),
                        extra={"metadata": self.meta},
                    )
                except Exception:
                    pass  # langchain 调用本身已因 env 自动 trace
        except Exception as e:
            logger.debug(f"[OBSERVE] flush ignored: {e}")


@contextlib.contextmanager
def trace_span(name: str, **meta):
    """可观测 span 上下文管理器；无后端时为 no-op。"""
    backend, handle = _backend()
    span = _Span(backend, handle, name)
    span.meta.update(meta)
    try:
        yield span
    finally:
        try:
            span.flush()
        except Exception:
            pass
