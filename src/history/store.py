"""
对话历史存储（冷热分层）
Redis 热缓存（最近 12 轮会话上下文，TTL 24h）+ MySQL 8.0 冷存储（全量历史，唯一事实源）。

设计说明（与讲义 §6.2 契约一致）：
- 读路径（三级命中）：先读 Redis `sess:{sid}` → 未命中从 MySQL 取最近 12 轮并回填 Redis → 返回。
- 写路径（双写容错）：**先写 MySQL（事实源）再写 Redis**；MySQL 失败则本轮不落 Redis
  （保证"缓存里绝不出现数据库没有的幻影数据"）；Redis 失败仅记日志降级，不影响主链路。
- Redis List 语义：LPUSH 插头（最新在头）+ LTRIM 保留 12 轮 + EXPIRE 24h；
  读出后反序即时间正序。
- 连接管理：Redis 用进程级连接池单例；MySQL 每请求新开、用完即关
  （历史接口为 def 同步路由，FastAPI 自动放入线程池，禁止跨线程共享连接）。
- `session_id == conversation_id`：一个 id 串起前端会话、Redis 热缓存、MySQL 冷存储。
"""

import json
from datetime import datetime

import mysql.connector
import redis

from config.settings import settings
from src.common.logger import setup_logger

logger = setup_logger(__name__, "history.log")

HOT_TURNS = 12                       # 热缓存保留轮次（与讲义契约一致）
HOT_TTL_SECONDS = 24 * 3600          # 热缓存 TTL：24h（滑动续期）
TITLE_MAX_LEN = 24                   # 对话标题截断长度


def _hot_key(session_id: str) -> str:
    return f"sess:{session_id}"


def _truncate(text: str, limit: int = TITLE_MAX_LEN) -> str:
    """截断对话标题。

    注：切片终点用小写参数——check_contracts 的 Cypher 关系名扫描器
    会把「[ 数字/冒号 + 大写标识符 ]」形式的切片误判为关系名引用。
    """
    return text[0:limit]


def _now() -> datetime:
    return datetime.now()


class HistoryStore:
    """对话历史管理器：MySQL 冷存储 + Redis 热缓存"""

    def __init__(self):
        self._redis_pool: redis.Redis | None = None
        self._schema_ready = False

    # ============================================================
    # Redis 层（热缓存）
    # ============================================================

    def _get_redis(self) -> redis.Redis:
        """连接池单例（惰性创建）"""
        if self._redis_pool is None:
            self._redis_pool = redis.Redis.from_url(
                settings.redis_url, decode_responses=True
            )
        return self._redis_pool

    def get_hot(self, session_id: str) -> list[dict] | None:
        """读热缓存；Redis 不可用/未命中返回 None（调用方回源 MySQL）。"""
        try:
            items = self._get_redis().lrange(_hot_key(session_id), 0, HOT_TURNS - 1)
        except Exception as e:
            logger.warning(f"[HISTORY] Redis read failed, fallback to MySQL: {e}")
            return None
        if not items:
            return None
        turns = []
        for raw in reversed(items):  # LPUSH 插头 → 反序即时间正序
            try:
                turns.append(json.loads(raw))
            except Exception:
                continue
        return turns or None

    def append_hot(self, session_id: str, turn: dict) -> bool:
        """写热缓存；失败仅记日志返回 False（缓存可缺，不可幻）。"""
        try:
            r = self._get_redis()
            key = _hot_key(session_id)
            r.lpush(key, json.dumps(turn, ensure_ascii=False))
            r.ltrim(key, 0, HOT_TURNS - 1)
            r.expire(key, HOT_TTL_SECONDS)  # 滑动续期
            return True
        except Exception as e:
            logger.warning(f"[HISTORY] Redis write failed, degraded (MySQL is source of truth): {e}")
            return False

    def _backfill_hot(self, session_id: str, turns: list[dict]) -> None:
        """把 MySQL 回源的轮次按时间正序逐条 LPUSH，重建与 append_hot 相同的头部布局。"""
        try:
            r = self._get_redis()
            key = _hot_key(session_id)
            for t in turns:
                r.lpush(key, json.dumps(t, ensure_ascii=False))
            r.expire(key, HOT_TTL_SECONDS)
        except Exception as e:
            logger.warning(f"[HISTORY] Redis backfill failed, degraded: {e}")

    def delete_hot(self, session_id: str) -> None:
        try:
            self._get_redis().delete(_hot_key(session_id))
        except Exception as e:
            logger.warning(f"[HISTORY] Redis delete failed: {e}")

    # ============================================================
    # MySQL 层（冷存储，唯一事实源）
    # ============================================================

    def _bootstrap_conn(self):
        """不带库连接，用于建库建表（首次使用自动执行）。"""
        return mysql.connector.connect(
            host=settings.mysql_host,
            port=settings.mysql_port,
            user=settings.mysql_user,
            password=settings.mysql_password,
            charset="utf8mb4",
            collation="utf8mb4_unicode_ci",
        )

    def _conn(self):
        """每请求新开的业务连接（用完即关，禁止跨线程共享）。"""
        if not self._schema_ready:
            self._ensure_schema()
        return mysql.connector.connect(
            host=settings.mysql_host,
            port=settings.mysql_port,
            user=settings.mysql_user,
            password=settings.mysql_password,
            database=settings.mysql_database,
            charset="utf8mb4",
            collation="utf8mb4_unicode_ci",
        )

    def _ensure_schema(self) -> None:
        """建库 + 建表（IF NOT EXISTS，幂等）。"""
        conn = self._bootstrap_conn()
        try:
            cur = conn.cursor()
            cur.execute(
                f"CREATE DATABASE IF NOT EXISTS `{settings.mysql_database}` "
                "CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"
            )
            cur.execute(f"USE `{settings.mysql_database}`")
            cur.execute("""
                CREATE TABLE IF NOT EXISTS conversations (
                    id         VARCHAR(64)  PRIMARY KEY,
                    title      VARCHAR(64)  NOT NULL DEFAULT '',
                    created_at DATETIME     NOT NULL,
                    updated_at DATETIME     NOT NULL
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS messages (
                    id              BIGINT AUTO_INCREMENT PRIMARY KEY,
                    conversation_id VARCHAR(64)  NOT NULL,
                    role            VARCHAR(16)  NOT NULL,
                    content         MEDIUMTEXT   NOT NULL,
                    intent          VARCHAR(32)  NOT NULL DEFAULT '',
                    created_at      DATETIME     NOT NULL,
                    INDEX idx_conv_id (conversation_id, id)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
            """)
            conn.commit()
            cur.close()
            self._schema_ready = True
            logger.info("[HISTORY] MySQL schema ensured (conversations / messages)")
        finally:
            conn.close()

    # ---------- 读 ----------

    def list_conversations(self, limit: int = 50) -> list[dict]:
        """对话列表，按 updated_at 倒序（LIMIT 分页）。"""
        conn = self._conn()
        try:
            cur = conn.cursor(dictionary=True)
            cur.execute(
                "SELECT id, title, created_at, updated_at FROM conversations "
                "ORDER BY updated_at DESC LIMIT %s",
                (limit,),
            )
            rows = cur.fetchall()
            cur.close()
            return [
                {
                    "id": r["id"],
                    "title": r["title"],
                    "created_at": r["created_at"].isoformat() if r["created_at"] else "",
                    "updated_at": r["updated_at"].isoformat() if r["updated_at"] else "",
                }
                for r in rows
            ]
        finally:
            conn.close()

    def conversation_exists(self, conversation_id: str) -> bool:
        conn = self._conn()
        try:
            cur = conn.cursor()
            cur.execute("SELECT 1 FROM conversations WHERE id = %s", (conversation_id,))
            row = cur.fetchone()
            cur.close()
            return row is not None
        finally:
            conn.close()

    def get_messages(self, conversation_id: str) -> list[dict]:
        """该对话全部消息，按写入顺序（id 正序）。"""
        conn = self._conn()
        try:
            cur = conn.cursor(dictionary=True)
            cur.execute(
                "SELECT role, content, intent, created_at FROM messages "
                "WHERE conversation_id = %s ORDER BY id ASC",
                (conversation_id,),
            )
            rows = cur.fetchall()
            cur.close()
            return [
                {
                    "role": r["role"],
                    "content": r["content"],
                    "intent": r["intent"] or "",
                    "created_at": r["created_at"].isoformat() if r["created_at"] else "",
                }
                for r in rows
            ]
        finally:
            conn.close()

    # ---------- 写 ----------

    def insert_message(self, conversation_id: str, role: str, content: str, intent: str = "") -> None:
        """写入一条消息；conversation 不存在则自动创建（title = 首条内容截断）。"""
        conn = self._conn()
        try:
            cur = conn.cursor()
            now = _now()
            cur.execute("SELECT id FROM conversations WHERE id = %s", (conversation_id,))
            if cur.fetchone() is None:
                title = _truncate(content)
                cur.execute(
                    "INSERT INTO conversations (id, title, created_at, updated_at) "
                    "VALUES (%s, %s, %s, %s)",
                    (conversation_id, title, now, now),
                )
            cur.execute(
                "INSERT INTO messages (conversation_id, role, content, intent, created_at) "
                "VALUES (%s, %s, %s, %s, %s)",
                (conversation_id, role, content, intent or "", now),
            )
            cur.execute(
                "UPDATE conversations SET updated_at = %s WHERE id = %s",
                (now, conversation_id),
            )
            conn.commit()
            cur.close()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def delete_conversation(self, conversation_id: str) -> None:
        """删除对话及全部消息：清 MySQL 两表 + DEL 对应 Redis key。"""
        conn = self._conn()
        try:
            cur = conn.cursor()
            cur.execute("DELETE FROM messages WHERE conversation_id = %s", (conversation_id,))
            cur.execute("DELETE FROM conversations WHERE id = %s", (conversation_id,))
            conn.commit()
            cur.close()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()
        self.delete_hot(conversation_id)

    # ============================================================
    # 统一入口
    # ============================================================

    def persist_turn(self, session_id: str, role: str, content: str, intent: str = "") -> bool:
        """双写一轮：先 MySQL（事实源）再 Redis（缓存）。

        MySQL 失败 → 本轮同样不落 Redis（防幻影数据），记错误日志，返回 False；
        MySQL 成功、Redis 失败 → 仅降级（读路径未命中会回源），返回 True。
        """
        turn = {"role": role, "content": content}
        if intent:
            turn["intent"] = intent
        try:
            self.insert_message(session_id, role, content, intent)
        except Exception as e:
            logger.error(f"[HISTORY] MySQL write failed (source of truth), skip Redis for this turn: {e}")
            return False
        self.append_hot(session_id, turn)
        return True

    def load_context(self, session_id: str) -> list[dict]:
        """三级命中读取多轮上下文：Redis → MySQL 回填 → 空列表。"""
        turns = self.get_hot(session_id)
        if turns is not None:
            return turns
        rows = self.get_messages(session_id)
        if not rows:
            return []
        turns = [
            {k: v for k, v in (
                ("role", r["role"]), ("content", r["content"]), ("intent", r["intent"])
            ) if v}
            for r in rows
        ][-HOT_TURNS:]
        self._backfill_hot(session_id, turns)
        logger.info(f"[HISTORY] Context backfilled from MySQL: session={session_id} turns={len(turns)}")
        return turns


# 全局单例
history_store = HistoryStore()
