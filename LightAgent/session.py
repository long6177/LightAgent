"""Event-sourced sessions, persistence, replay, and context projection."""

from __future__ import annotations

import json
import os
import sqlite3
import threading
import hashlib
from copy import deepcopy
from dataclasses import asdict, dataclass, field, is_dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Protocol
from uuid import uuid4


SESSION_SCHEMA_VERSION = 1
_SENSITIVE_KEYS = {
    "api_key",
    "apikey",
    "authorization",
    "credential",
    "credentials",
    "password",
    "secret",
    "token",
}


def _utc_now() -> str:
    """
    Return the current UTC time as an ISO 8601 string.
    """
    return datetime.now(timezone.utc).isoformat()


class SessionMigrationRegistry:
    """Ordered migrations for persisted Session payloads and events."""

    def __init__(self):
        self._session_migrations: dict[int, Callable[[dict[str, Any]], dict[str, Any]]] = {}
        self._event_migrations: dict[int, Callable[[dict[str, Any]], dict[str, Any]]] = {}

    def register_session(self, from_version: int, migration: Callable[[dict[str, Any]], dict[str, Any]]) -> None:
        self._session_migrations[from_version] = migration

    def register_event(self, from_version: int, migration: Callable[[dict[str, Any]], dict[str, Any]]) -> None:
        self._event_migrations[from_version] = migration

    def migrate(self, value: dict[str, Any]) -> dict[str, Any]:
        payload = deepcopy(value)
        version = int(payload.get("schema_version", 1))
        if version > SESSION_SCHEMA_VERSION:
            raise ValueError(
                f"unsupported Session schema_version={version}; maximum supported={SESSION_SCHEMA_VERSION}"
            )
        while version < SESSION_SCHEMA_VERSION:
            migration = self._session_migrations.get(version)
            if migration is None:
                raise ValueError(f"missing Session migration from schema_version={version}")
            payload = migration(payload)
            version = int(payload.get("schema_version", version + 1))
        payload["events"] = [self.migrate_event(event) for event in payload.get("events", [])]
        return payload

    def migrate_event(self, value: dict[str, Any]) -> dict[str, Any]:
        payload = deepcopy(value)
        version = int(payload.get("schema_version", 1))
        if version > SESSION_SCHEMA_VERSION:
            raise ValueError(
                f"unsupported SessionEvent schema_version={version}; maximum supported={SESSION_SCHEMA_VERSION}"
            )
        while version < SESSION_SCHEMA_VERSION:
            migration = self._event_migrations.get(version)
            if migration is None:
                raise ValueError(f"missing SessionEvent migration from schema_version={version}")
            payload = migration(payload)
            version = int(payload.get("schema_version", version + 1))
        return payload


session_migrations = SessionMigrationRegistry()


def _json_safe(value: Any, *, key: str | None = None) -> Any:
    """Return a JSON-safe copy while removing common credential fields."""
    if key is not None and key.lower() in _SENSITIVE_KEYS: # 检测是否包含敏感字段
        return "[redacted]"
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if is_dataclass(value):
        return _json_safe(asdict(value))
    if hasattr(value, "to_dict") and callable(value.to_dict):
        try:
            return _json_safe(value.to_dict())
        except TypeError:
            pass
    if isinstance(value, dict):
        return {str(item_key): _json_safe(item, key=str(item_key)) for item_key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(item) for item in value]
    return repr(value)


@dataclass
class SessionEvent:
    """One immutable(不变的) fact in a session event log."""

    type: str # 事件类型
    session_id: str # 事件所属会话的id
    data: dict[str, Any] = field(default_factory=dict) # 业务数据
    event_id: str = field(default_factory=lambda: uuid4().hex)
    timestamp: str = field(default_factory=_utc_now)
    sequence: int = 0
    schema_version: int = SESSION_SCHEMA_VERSION
    turn_id: str | None = None # 属于哪一轮对话
    step_id: str | None = None
    run_id: str | None = None
    agent_id: str | None = None
    parent_event_id: str | None = None # 可用于表达事件之间的父子关系

    def __post_init__(self) -> None: # 在类实例化之后运行, 用于验证
        if not self.type or not isinstance(self.type, str):
            raise ValueError("SessionEvent.type must be a non-empty string")
        if not self.session_id:
            raise ValueError("SessionEvent.session_id must not be empty")
        if self.sequence < 0:
            raise ValueError("SessionEvent.sequence must be non-negative")
        if self.schema_version < 1:
            raise ValueError("SessionEvent.schema_version must be at least 1")
        self.data = _json_safe(self.data) # 将数据转换为JSON安全的格式, 并移除敏感信息

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "session_id": self.session_id,
            "type": self.type,
            "data": deepcopy(self.data),
            "timestamp": self.timestamp,
            "sequence": self.sequence,
            "schema_version": self.schema_version,
            "turn_id": self.turn_id,
            "step_id": self.step_id,
            "run_id": self.run_id,
            "agent_id": self.agent_id,
            "parent_event_id": self.parent_event_id,
        }

    @classmethod # 声明是类方法, 可以通过类名调用, 也可以通过实例调用
    def from_dict(cls, value: dict[str, Any]) -> "SessionEvent":
        """
        Create a SessionEvent from a dictionary, validating required fields.
        """
        if not isinstance(value, dict):
            raise TypeError("SessionEvent payload must be a dictionary")
        return cls( # 会自动执行__post_init__方法, 用于验证字段
            event_id=str(value.get("event_id") or uuid4().hex),
            session_id=str(value["session_id"]),
            type=str(value["type"]),
            data=dict(value.get("data") or {}),
            timestamp=str(value.get("timestamp") or _utc_now()),
            sequence=int(value.get("sequence", 0)),
            schema_version=int(value.get("schema_version", SESSION_SCHEMA_VERSION)),
            turn_id=value.get("turn_id"),
            step_id=value.get("step_id"),
            run_id=value.get("run_id"),
            agent_id=value.get("agent_id"),
            parent_event_id=value.get("parent_event_id"),
        )


@dataclass
class SessionCheckpoint:
    """
    A checkpoint in a session, representing a specific point in the event log.

    一个session的事件流的一个检查点, 不记录事件数据, 只记录check的事件序号

    ### 职能
    - 保存checktpoint信息;
    - 转成JSON友好的字典;
    - 嵌入session.checkpointed事件
    """
    checkpoint_id: str
    session_id: str
    sequence: int # 创建 checkpoint之前最后一个业务事件的序号
    label: str | None = None # 人类可读的名字
    created_at: str = field(default_factory=_utc_now)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return _json_safe(asdict(self))


@dataclass
class SessionReplay:
    """A summary report generated by replaying and analyzing a session's event log."""
    session_id: str
    event_count: int
    completed_turns: list[str] = field(default_factory=list)
    incomplete_turns: list[str] = field(default_factory=list)
    failed_turns: list[str] = field(default_factory=list)
    last_sequence: int = 0
    last_event_type: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Session:
    # "event-sourced" session
    """Append-only session state reconstructed from versioned events."""

    session_id: str = field(default_factory=lambda: uuid4().hex)
    metadata: dict[str, Any] = field(default_factory=dict)
    events: list[SessionEvent] = field(default_factory=list) # 业务事件流, 按照sequence升序排列
    created_at: str = field(default_factory=_utc_now)
    updated_at: str = field(default_factory=_utc_now)
    schema_version: int = SESSION_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if not self.session_id:
            raise ValueError("Session.session_id must not be empty")
        self.metadata = _json_safe(self.metadata)
        self.events = sorted(list(self.events), key=lambda event: event.sequence)
        self.validate()

    @property
    def next_sequence(self) -> int:
        return self.events[-1].sequence + 1 if self.events else 1 # based-1

    def append(
            self,
            event_type: str,
            data: dict[str, Any] | None = None,
            *,
            turn_id: str | None = None,
            step_id: str | None = None,
            run_id: str | None = None,
            agent_id: str | None = None,
            parent_event_id: str | None = None,
    ) -> SessionEvent:
        event = SessionEvent( # 先构造
            type=event_type,
            session_id=self.session_id,
            data=data or {},
            sequence=self.next_sequence, # 自动单调递增 auto-increment sequence
            schema_version=self.schema_version,
            turn_id=turn_id,
            step_id=step_id,
            run_id=run_id,
            agent_id=agent_id,
            parent_event_id=parent_event_id,
        )
        self.events.append(event)
        self.updated_at = event.timestamp
        return event

    def append_event(self, event: SessionEvent) -> SessionEvent:
        """
        作用基本同 `Seesion.append`, 但是 `append_event` 允许用户传入一个已经构造好的 `SessionEvent` 对象，而不是通过传入事件类型和数据来创建新的事件。
        
        它会验证传入的事件是否符合当前会话的要求，包括 session_id 是否匹配、sequence 是否正确、以及 event_id 是否唯一。
        """
        if event.session_id != self.session_id:
            raise ValueError("event session_id does not match Session")
        expected = self.next_sequence
        if event.sequence == 0:
            event.sequence = expected
        if event.sequence != expected:
            raise ValueError(f"event sequence must be {expected}, got {event.sequence}")
        if any(existing.event_id == event.event_id for existing in self.events):
            raise ValueError(f"duplicate event_id: {event.event_id}")
        self.events.append(event)
        self.updated_at = event.timestamp
        return event

    def page(self, *, after: int = 0, limit: int = 100) -> list[SessionEvent]:
        """Return a page of events after a given sequence number `after`."""
        if limit < 1:
            raise ValueError("limit must be at least 1")
        return [event for event in self.events if event.sequence > after][:limit]

    def checkpoint(self, label: str | None = None, metadata: dict[str, Any] | None = None) -> SessionCheckpoint:
        checkpoint = SessionCheckpoint(
            checkpoint_id=uuid4().hex,
            session_id=self.session_id,
            sequence=self.events[-1].sequence if self.events else 0,
            label=label,
            metadata=_json_safe(metadata or {}),
        )
        self.append("session.checkpointed", {"checkpoint": checkpoint.to_dict()}) # 追加checkpointed事件
        return checkpoint

    def fork(
            self,
            *,
            new_session_id: str | None = None,
            through_sequence: int | None = None,
            metadata: dict[str, Any] | None = None,
    ) -> "Session":
        """
        从当前会话指定的历史位置创建一个新的会话分支。

        新会话会复制当前会话在 ``through_sequence``（包含该序号）之前的
        事件，并为复制出的事件生成新的事件 ID；原会话及其事件不会被修改。
        如果未指定 ``through_sequence``，则复制当前会话的全部事件。新会话的
        元数据会继承原会话，并记录来源会话 ID 和分支边界。

        Args:
            new_session_id: 新会话的 ID；未指定时自动生成。
            through_sequence: 要复制到的新会话中的最后一个事件序号；
                必须位于当前会话的事件序号范围内。
            metadata: 写入新会话并覆盖同名原会话元数据的附加信息。

        Returns:
            从当前会话指定历史位置创建的新 ``Session``。

        Raises:
            ValueError: ``through_sequence`` 小于 0，或超出当前会话的事件范围。
        """
        boundary = through_sequence if through_sequence is not None else (self.events[-1].sequence if self.events else 0)
        if boundary < 0 or boundary > (self.events[-1].sequence if self.events else 0):
            raise ValueError("through_sequence is outside the session event range")
        forked = Session(
            session_id=new_session_id or uuid4().hex,
            metadata={
                **deepcopy(self.metadata),
                **(metadata or {}),
                "forked_from": self.session_id,
                "forked_at_sequence": boundary,
            },
        )
        forked.append("session.started", {"forked_from": self.session_id, "through_sequence": boundary})
        for event in self.events:
            if event.sequence > boundary:
                break
            forked.append(
                event.type,
                {
                    **deepcopy(event.data),  # 深拷贝
                    "source_session_id": self.session_id,
                    "source_event_id": event.event_id,
                    "source_sequence": event.sequence,
                },
                turn_id=event.turn_id,
                step_id=event.step_id,
                run_id=event.run_id,
                agent_id=event.agent_id,
                parent_event_id=event.event_id,
            )
        forked.append("session.forked", {"source_session_id": self.session_id, "through_sequence": boundary})
        return forked

    def replay(self) -> SessionReplay:
        """统一当前会话中, agent执行的所有turn的状态, 即每轮Agent执行周期的状态,生成一个replay报告"""
        started: set[str] = set()
        completed: set[str] = set()
        failed: set[str] = set()
        for event in self.events:
            if not event.turn_id:
                continue
            if event.type == "turn.started":
                started.add(event.turn_id)
            elif event.type == "turn.completed":
                completed.add(event.turn_id)
            elif event.type == "turn.failed":
                failed.add(event.turn_id)
        return SessionReplay(
            session_id=self.session_id,
            event_count=len(self.events),
            completed_turns=sorted(completed), # 成功的轮次
            incomplete_turns=sorted(started - completed - failed), # 已经开始了但是没有最终状态的turn
            failed_turns=sorted(failed), # 失败的轮次
            last_sequence=self.events[-1].sequence if self.events else 0,
            last_event_type=self.events[-1].type if self.events else None,
        )

    def validate(self) -> None:
        """
        `Session`创建时, 会通过`__post_init__`自动调用, 用于检查当前的 `self.events`是否满足`Session`的基本不变量
        """
        seen_ids: set[str] = set()
        expected = 1
        for event in self.events:
            if event.session_id != self.session_id:
                raise ValueError("session contains an event for another session")
            if event.event_id in seen_ids:
                raise ValueError(f"duplicate event_id: {event.event_id}")
            if event.sequence != expected:
                raise ValueError(f"event sequence gap: expected {expected}, got {event.sequence}")
            if event.schema_version > SESSION_SCHEMA_VERSION:
                raise ValueError(
                    f"unsupported SessionEvent schema_version={event.schema_version}; "
                    f"maximum supported={SESSION_SCHEMA_VERSION}"
                )
            seen_ids.add(event.event_id)
            expected += 1

    def to_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "metadata": deepcopy(self.metadata),
            "events": [event.to_dict() for event in self.events], # 业务数据event['data']
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "schema_version": self.schema_version,
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "Session":
        value = session_migrations.migrate(value)
        return cls(
            session_id=str(value["session_id"]),
            metadata=dict(value.get("metadata") or {}),
            events=[SessionEvent.from_dict(event) for event in value.get("events", [])],
            created_at=str(value.get("created_at") or _utc_now()),
            updated_at=str(value.get("updated_at") or _utc_now()),
            schema_version=int(value.get("schema_version", SESSION_SCHEMA_VERSION)),
        )


class SessionStore(Protocol): # `Protocol` 的那些协议类`protocol class`的基类
    """
    `...`: 表示不提供具体实现, 只提供方法签名

    这个协议类(`protocol class`)定义了一个会话存储的接口, 任何实现了这个接口的类都可以作为会话存储使用

    但并不是传统意义上的通过"继承抽象基类"的方式去实现接口, 只要一个类的方法结构满足"协议", 静态类型检查器就会接受它
    
    `Protocol`的价值在于: 第三方用户可以自己实现一个存储后端, 不必修改和继承LightAgent的类.
    """
    def create(self, session: Session | None = None, *, metadata: dict[str, Any] | None = None) -> Session:
        """创建会话"""
        ...

    def get(self, session_id: str) -> Session | None:
        """读取会话"""
        ...

    def save(self, session: Session) -> None:
        """保存会话"""
        ...

    def list(self, *, limit: int = 100) -> list[Session]:
        """列出会话"""
        ...

    def delete(self, session_id: str) -> bool:
        """删除会话"""
        ...


class InMemorySessionStore:
    """Thread-safe dependency-free SessionStore."""

    def __init__(self):
        self._sessions: dict[str, Session] = {}
        self._lock = threading.RLock()

    def create(self, session: Session | None = None, *, metadata: dict[str, Any] | None = None) -> Session:
        with self._lock:
            value = session or Session(metadata=metadata or {})
            if value.session_id in self._sessions:
                raise ValueError(f"session already exists: {value.session_id}")
            self._sessions[value.session_id] = deepcopy(value)
            return deepcopy(value)

    def get(self, session_id: str) -> Session | None:
        with self._lock:
            value = self._sessions.get(str(session_id))
            return deepcopy(value) if value is not None else None

    def save(self, session: Session) -> None:
        session.validate()
        with self._lock:
            current = self._sessions.get(session.session_id)
            if current and current.events and session.events:
                if session.events[-1].sequence < current.events[-1].sequence:
                    raise ValueError("refusing to replace a Session with an older event sequence")
            self._sessions[session.session_id] = deepcopy(session)

    def list(self, *, limit: int = 100) -> list[Session]:
        if limit < 1:
            raise ValueError("limit must be at least 1")
        with self._lock:
            values = sorted(self._sessions.values(), key=lambda item: item.updated_at, reverse=True)
            return deepcopy(values[:limit])

    def delete(self, session_id: str) -> bool:
        with self._lock:
            return self._sessions.pop(str(session_id), None) is not None


class JsonlSessionStore:
    """One append-readable JSONL file per Session with atomic full saves.
    
    - 持久化
    - 无数据库 dependency
    - 人类可读
    """

    def __init__(self, directory: str | os.PathLike[str]):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()

    @staticmethod
    def _safe_id(session_id: str) -> str:
        value = str(session_id)
        if not value or any(character not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_" for character in value):
            raise ValueError("session_id contains unsafe characters")
        return value

    def _path(self, session_id: str) -> Path:
        return self.directory / f"{self._safe_id(session_id)}.jsonl"

    def create(self, session: Session | None = None, *, metadata: dict[str, Any] | None = None) -> Session:
        value = session or Session(metadata=metadata or {})
        with self._lock:
            if self._path(value.session_id).exists():
                raise ValueError(f"session already exists: {value.session_id}")
            self.save(value)
        return deepcopy(value)

    def get(self, session_id: str) -> Session | None:
        path = self._path(session_id)
        if not path.exists():
            return None
        with self._lock, path.open("r", encoding="utf-8") as handle:
            lines = [json.loads(line) for line in handle if line.strip()]
        if not lines or lines[0].get("kind") != "session":
            raise ValueError(f"invalid Session JSONL header: {path}")
        header = lines[0]["value"]
        events = [SessionEvent.from_dict(line["value"]) for line in lines[1:] if line.get("kind") == "event"]
        return Session(
            session_id=header["session_id"],
            metadata=header.get("metadata") or {},
            events=events,
            created_at=header.get("created_at") or _utc_now(),
            updated_at=header.get("updated_at") or _utc_now(),
            schema_version=int(header.get("schema_version", SESSION_SCHEMA_VERSION)),
        )

    def save(self, session: Session) -> None:
        session.validate()
        path = self._path(session.session_id)
        temporary = path.with_suffix(f".tmp-{uuid4().hex}")
        header = {
            "session_id": session.session_id,
            "metadata": session.metadata,
            "created_at": session.created_at,
            "updated_at": session.updated_at,
            "schema_version": session.schema_version,
        }
        with self._lock:
            with temporary.open("w", encoding="utf-8") as handle:
                handle.write(json.dumps({"kind": "session", "value": header}, ensure_ascii=False) + "\n")
                for event in session.events:
                    handle.write(json.dumps({"kind": "event", "value": event.to_dict()}, ensure_ascii=False) + "\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, path)

    def list(self, *, limit: int = 100) -> list[Session]:
        if limit < 1:
            raise ValueError("limit must be at least 1")
        sessions = []
        for path in sorted(self.directory.glob("*.jsonl"), key=lambda item: item.stat().st_mtime, reverse=True):
            session = self.get(path.stem)
            if session is not None:
                sessions.append(session)
            if len(sessions) >= limit:
                break
        return sessions

    def delete(self, session_id: str) -> bool:
        path = self._path(session_id)
        with self._lock:
            if not path.exists():
                return False
            path.unlink()
            return True


class SqliteSessionStore:
    """Standard-library SQLite SessionStore with transactional saves."""

    def __init__(self, path: str | os.PathLike[str]):
        self.path = str(path)
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock() # 读锁
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        """
        Return a new SQLite connection with WAL journaling and row factory.
        """
        connection = sqlite3.connect(self.path, timeout=30)
        connection.row_factory = sqlite3.Row
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS sessions (
                    session_id TEXT PRIMARY KEY,
                    metadata TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    schema_version INTEGER NOT NULL
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS session_events (
                    session_id TEXT NOT NULL,
                    sequence INTEGER NOT NULL,
                    event_id TEXT NOT NULL UNIQUE,
                    payload TEXT NOT NULL,
                    PRIMARY KEY (session_id, sequence),
                    FOREIGN KEY (session_id) REFERENCES sessions(session_id) ON DELETE CASCADE
                )
                """
            )

    def create(self, session: Session | None = None, *, metadata: dict[str, Any] | None = None) -> Session:
        value = session or Session(metadata=metadata or {})
        with self._lock, self._connect() as connection:
            existing = connection.execute(
                "SELECT 1 FROM sessions WHERE session_id = ?", (value.session_id,)
            ).fetchone()
            if existing:
                raise ValueError(f"session already exists: {value.session_id}")
        self.save(value)
        return deepcopy(value)

    def get(self, session_id: str) -> Session | None:
        with self._lock, self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM sessions WHERE session_id = ?", (str(session_id),)
            ).fetchone()
            if row is None:
                return None
            event_rows = connection.execute(
                "SELECT payload FROM session_events WHERE session_id = ? ORDER BY sequence",
                (str(session_id),),
            ).fetchall()
        return Session(
            session_id=row["session_id"],
            metadata=json.loads(row["metadata"]),
            events=[SessionEvent.from_dict(json.loads(event_row["payload"])) for event_row in event_rows],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            schema_version=row["schema_version"],
        )

    def save(self, session: Session) -> None:
        session.validate()
        with self._lock, self._connect() as connection:
            connection.execute("PRAGMA foreign_keys=ON")
            connection.execute(
                """
                INSERT INTO sessions(session_id, metadata, created_at, updated_at, schema_version)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(session_id) DO UPDATE SET
                    metadata=excluded.metadata,
                    updated_at=excluded.updated_at,
                    schema_version=excluded.schema_version
                """,
                (
                    session.session_id,
                    json.dumps(session.metadata, ensure_ascii=False),
                    session.created_at,
                    session.updated_at,
                    session.schema_version,
                ),
            )
            connection.execute("DELETE FROM session_events WHERE session_id = ?", (session.session_id,))
            connection.executemany(
                "INSERT INTO session_events(session_id, sequence, event_id, payload) VALUES (?, ?, ?, ?)",
                [
                    (
                        session.session_id,
                        event.sequence,
                        event.event_id,
                        json.dumps(event.to_dict(), ensure_ascii=False),
                    )
                    for event in session.events
                ],
            )

    def list(self, *, limit: int = 100) -> list[Session]:
        if limit < 1:
            raise ValueError("limit must be at least 1")
        with self._lock, self._connect() as connection:
            rows = connection.execute(
                "SELECT session_id FROM sessions ORDER BY updated_at DESC LIMIT ?", (int(limit),)
            ).fetchall()
        return [session for row in rows if (session := self.get(row["session_id"])) is not None]

    def delete(self, session_id: str) -> bool:
        with self._lock, self._connect() as connection:
            connection.execute("PRAGMA foreign_keys=ON")
            cursor = connection.execute("DELETE FROM sessions WHERE session_id = ?", (str(session_id),))
            return cursor.rowcount > 0


class ContextProjector: # 投影
    """Project model messages and runtime views from Session events."""

    def messages(self, session: Session, *, turn_id: str | None = None) -> list[dict[str, Any]]:
        """Reconstruct the exact messages ("ChatCompletion API Protocol" or ....) sent to the model for one turn (`turn_id`) or the latest turn."""
        requested = [ # 指定turn_id的请求模型时保存的"消息快照"
            event for event in session.events
            if event.type == "model.requested"
            and (turn_id is None or event.turn_id == turn_id)
            and isinstance(event.data.get("messages"), list)
        ]
        messages: list[dict[str, Any]] = []
        for event in session.events:
            if turn_id is not None and event.turn_id != turn_id:
                continue
            if event.type in {"message.received", "message.created"}:
                messages.append({"role": event.data.get("role", "user"), "content": event.data.get("content", "")})
            elif event.type in {"assistant.completed", "model.completed"} and event.data.get("content") is not None:
                messages.append({"role": "assistant", "content": event.data.get("content", "")})
            elif event.type == "tool.completed":
                messages.append({
                    "role": "tool",
                    "tool_call_id": event.data.get("tool_call_id"),
                    "content": str(event.data.get("output", "")),
                })
        if messages:
            return messages
        if requested: # 当普通事件无法重建消息时，使用最近一次实际模型请求的快照。
            return deepcopy(requested[-1].data["messages"])
        return []

    def model_request(
            self,
            session: Session,
            *,
            sequence: int | None = None,
    ) -> list[dict[str, Any]]:
        """Reconstruct the exact messages(完整的发送消息) sent for one persisted model request."""
        requested = [
            event for event in session.events
            if event.type == "model.requested"
            and isinstance(event.data.get("messages"), list)
            and (sequence is None or event.sequence == sequence)
        ]
        if not requested:
            raise LookupError("model request event was not found")
        return deepcopy(requested[-1].data["messages"]) # 如果没有指定 sequence, 则返回最近一次的 model.requested 事件的消息快照

    def trace(self, session: Session, *, turn_id: str | None = None) -> list[dict[str, Any]]:
        """Reconstruct the trace events for one turn (`turn_id`) or all turns."""
        trace = []
        for event in session.events:
            if turn_id is not None and event.turn_id != turn_id:
                continue
            trace_type = event.data.get("trace_type") # 事件数据中包含 trace_type 字段(来自traceRecoder的追加), 用于标识事件的类型
            if trace_type:
                trace.append({
                    "type": trace_type,
                    "data": deepcopy(event.data.get("trace_data") or {}),
                    "timestamp": event.timestamp,
                    "trace_id": event.data.get("trace_id"),
                    "parent_trace_id": event.data.get("parent_trace_id"),
                    "run_group_id": event.data.get("run_group_id"),
                })
        return trace


@dataclass
class CompactionResult:
    """The unifyed result of a context compaction operation,
    
    including the compacted messages, any spilled tool results, and an optional summary.

    Args:
        messages: 压缩之后的消息列表, 即为实际要发给模型的消息列表/上下文
        removed_count: 被从消息列表中移除的消息
        summary: 被删掉的历史消息经过摘要器`Summarizer`压缩后得到的总结文本, 
        spilled: 那些被移除模型上下文或者被改为引用占位符的较长的工具结果(`if len> max_inline_tool_chars`).
    """
    messages: list[dict[str, Any]]
    removed_count: int
    summary: str | None = None
    spilled: list[dict[str, Any]] = field(default_factory=list)


@dataclass(frozen=True)
class ContextBudget:
    """Dependency-free context budget using a conservative(保守) character estimate."""

    max_tokens: int = 8192 # 一个上下文的最大token, 注意并不是 "允许模型生成/返回的最大输出token数"
    reserved_output_tokens: int = 1024 # 预留给模型输出的token数
    chars_per_token: float = 4.0

    def __post_init__(self) -> None:
        """Post-initialization validation."""
        if self.max_tokens < 1 or self.reserved_output_tokens < 0:
            raise ValueError("context token limits must be non-negative")
        if self.reserved_output_tokens >= self.max_tokens:
            raise ValueError("reserved_output_tokens must be smaller than max_tokens")
        if self.chars_per_token <= 0:
            raise ValueError("chars_per_token must be positive")

    def estimate(self, messages: Iterable[dict[str, Any]]) -> int:
        """Estimate the number of tokens used by a list of `messages`."""
        rendered = json.dumps(list(messages), ensure_ascii=False, sort_keys=True)
        return max(1, int(len(rendered) / self.chars_per_token) + 1)

    def fits(self, messages: Iterable[dict[str, Any]]) -> bool:
        """Check if the estimated token usage of `messages` fits within the budget."""
        return self.estimate(messages) <= self.max_tokens - self.reserved_output_tokens


class ContextCompactor:
    """
    Deterministic message trimming with optional summary generation.
    确定性地裁剪消息，并可选择生成摘要。

    
    """

    def __init__(
            self,
            summarizer: Callable[[list[dict[str, Any]]], str] | None = None, # optional
            *,
            max_inline_tool_chars: int = 12000,
    ):
        self.summarizer = summarizer
        self.max_inline_tool_chars = max_inline_tool_chars

    def compact(self, messages: Iterable[dict[str, Any]], *, max_messages: int = 20) -> CompactionResult:
        """
        compact a list of messages according to `max_messages`.

        主要被 core.py: compact_session() 中被调用, 属于用户主动调用
        """
        values, spilled = self._spill_tool_results(messages) # 必处理超长工具结果
        if max_messages < 2:
            raise ValueError("max_messages must be at least 2")
        if len(values) <= max_messages:
            return CompactionResult(messages=values, removed_count=0, spilled=spilled)

        system = [message for message in values if message.get("role") == "system"][:1] #保留第一个system消息
        non_system = [message for message in values if message.get("role") != "system"]
        keep_count = max_messages - len(system)
        kept = non_system[-keep_count:] # 保留最后keep_count条非system消息
        removed = non_system[:-keep_count] #记录被移除的消息

        while kept and kept[0].get("role") == "tool": # 避免把留下来的非system的消息的第一条是tool消息, 因为tool消息可能是很长的工具调用结果, 依赖前面的assistant tool_call, tool_call_id
            removed.append(kept.pop(0))
        summary = self.summarizer(deepcopy(removed)) if self.summarizer and removed else None
        if summary:
            summary_message = {
                "role": "system",
                "content": f"Previous conversation summary:\n{summary}",
                "metadata": {"compacted": True, "removed_count": len(removed)},
            }
            result_messages = system + [summary_message] + kept
        else:
            result_messages = system + kept
        return CompactionResult(
            messages=result_messages,
            removed_count=len(removed),
            summary=summary,
            spilled=spilled,
        )

    def compact_to_budget(
            self,
            messages: Iterable[dict[str, Any]],
            budget: ContextBudget,
    ) -> CompactionResult:
        """
        compact a list of messages according to `budget`.

        主要被 core.py: _compact_model_context() 中被调用, 属于每次模型请求前自动检查(根据token预算)
        """
        values = list(messages)
        if budget.fits(values): # 如果当前消息列表已经在预算范围内, 则只spill tool results
            prepared, spilled = self._spill_tool_results(values)
            return CompactionResult(messages=prepared, removed_count=0, spilled=spilled)

        # 不符合就要进行compact, 包含spill tool results
        max_messages = max(2, len(values))
        while max_messages > 2:
            result = self.compact(values, max_messages=max_messages)
            if budget.fits(result.messages):
                return result
            max_messages -= 1
        return self.compact(values, max_messages=2)

    def _spill_tool_results(
            self,
            messages: Iterable[dict[str, Any]],
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        """将过长的工具调用结果移出上下文(用hash占位符取代，并为其生成可追踪的引用。

        Args:
            messages: 待处理的消息集合。每条消息应为包含 ``role`` 和
                ``content`` 字段的字典。

        Returns:
            一个二元组 ``(prepared, spilled)``：``prepared`` 是可继续提供
            给模型的消息列表，其中过长的工具结果已替换为引用提示；
            ``spilled`` 是被移出的完整工具结果及其哈希、大小和引用信息。
        """
        prepared: list[dict[str, Any]] = [] # 处理后的消息列表, 供模型继续使用
        spilled: list[dict[str, Any]] = [] # 被移出上下文的完整工具结果
        for message in messages:
            value = deepcopy(message)
            content = value.get("content")
            if value.get("role") == "tool" and isinstance(content, str) and len(content) > self.max_inline_tool_chars:
                digest = hashlib.sha256(content.encode("utf-8")).hexdigest()# 给移除的消息content 计算一个SHA-256 摘要
                reference = f"tool-result:sha256:{digest}"
                spilled.append({
                    "reference": reference,
                    "sha256": digest,
                    "size": len(content),
                    "content": content,
                })
                value["content"] = f"[Tool result stored outside context: {reference}, {len(content)} chars]"
                value.setdefault("metadata", {})["content_reference"] = reference
            prepared.append(value)
        return prepared, spilled


__all__ = [
    "SESSION_SCHEMA_VERSION",
    "SessionMigrationRegistry",
    "session_migrations",
    "SessionEvent",
    "SessionCheckpoint",
    "SessionReplay",
    "Session",
    "SessionStore",
    "InMemorySessionStore",
    "JsonlSessionStore",
    "SqliteSessionStore",
    "ContextProjector",
    "CompactionResult",
    "ContextBudget",
    "ContextCompactor",
]
