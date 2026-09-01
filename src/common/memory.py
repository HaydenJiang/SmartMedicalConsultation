"""
Session Memory (会话记忆)
基于 session_id 的多轮对话记忆，支持上下文延续与跨轮症状累积。

设计说明：
- 单进程内使用内存 LRU（OrderedDict）存储，按 session_id 隔离会话。
- 每个会话保存最近 N 轮 {role, content, 以及可选的 intent/symptoms/departments}。
- 生产环境可替换为 Redis / 数据库（接口不变：get_history / add_turn / clear）。
- 单线程 asyncio 下无需加锁；若改用多 worker，请换成带锁或外置存储。
"""

from collections import OrderedDict

from src.common.logger import setup_logger

logger = setup_logger(__name__, "memory.log")


class SessionMemory:
    """会话记忆管理器"""

    def __init__(self, max_sessions: int = 512, max_turns: int = 12):
        self._store: OrderedDict = OrderedDict()  # sid -> {"turns": [...]}
        self.max_sessions = max_sessions
        self.max_turns = max_turns

    # ---------- 读取 ----------
    def get_history(self, session_id: str, n: int | None = None) -> list[dict]:
        """返回该会话的历史轮次（不含本轮），n 为最近 n 轮"""
        rec = self._store.get(session_id)
        if not rec:
            return []
        turns = rec["turns"]
        return turns[-n:] if n else list(turns)

    def get_known_symptoms(self, session_id: str) -> list[str]:
        """跨轮累积已出现的症状（去重保序）"""
        seen: list[str] = []
        for t in self.get_history(session_id):
            for s in t.get("symptoms", []) or []:
                if s and s not in seen:
                    seen.append(s)
        return seen

    # ---------- 写入 ----------
    def add_turn(self, session_id: str, role: str, content: str, **extra) -> None:
        """追加一轮对话；extra 可携带 intent/symptoms/departments 等结构化信息"""
        rec = self._store.setdefault(session_id, {"turns": []})
        self._store.move_to_end(session_id)  # LRU：标记为最近使用

        turn = {"role": role, "content": content}
        turn.update({k: v for k, v in extra.items() if v not in (None, "", [])})
        rec["turns"].append(turn)

        # 轮次上限
        if len(rec["turns"]) > self.max_turns:
            rec["turns"] = rec["turns"][-self.max_turns:]
        # 会话数上限（LRU 淘汰最久未用）
        while len(self._store) > self.max_sessions:
            evicted, _ = self._store.popitem(last=False)
            logger.debug(f"[MEMORY] LRU evicted session {evicted}")

    # ---------- 清理 ----------
    def clear(self, session_id: str) -> None:
        self._store.pop(session_id, None)

    def stats(self) -> dict:
        return {"sessions": len(self._store)}


# 全局单例
memory = SessionMemory()


def format_history(turns: list[dict]) -> str:
    """把历史轮次格式化为可放入提示词的文本"""
    if not turns:
        return "（无历史对话，这是首轮提问）"
    lines = []
    for t in turns:
        who = "用户" if t.get("role") == "user" else "助手"
        lines.append(f"{who}：{t.get('content', '')}")
    return "\n".join(lines)
