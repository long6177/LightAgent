#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
作者: [weego/WXAI-Team]
最后更新: 2026-02-20
"""

from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
import re
from typing import Any, Callable, Iterable, Protocol
from uuid import uuid4


class MemoryProtocol(Protocol):
    """
    The protocol for memory stotage and retrieval.

    记忆存储与检索协议, 通过 `user_id` 进行标识

    LightAgent 内置的协议的 implementer 是 `shared_memory.py:SharedMemoryPool` 和 `example/03memory_mem0.py:CustomMemory`。
    """
    def store(self, data: str, user_id: str) -> Any:
        ...

    def retrieve(self, query: str, user_id: str) -> Any:
        ...


@dataclass(frozen=True)
class MemoryScope:
    """
    Recommended metadata shape for memory provenance and retrieval policy.
    
    描述记忆的来源、作用域及检索策略等元数据。
    给记忆贴标签: 记忆由谁产生、适用于哪个范围、所属调用链以及可信度等信息，
    便于记忆适配器进行溯源、筛选和检索。

    Attributes:
        source: 记忆的来源，例如 ``user``、``reflection``、``delegation`` 或 ``tool``。
        scope: 记忆的作用域，例如 ``user``、``agent``、``shared`` 或 ``internal``。
        agent_name: 产生或拥有该记忆的 Agent 名称。
        trace_id: 产生该记忆的调用链追踪 ID。
        parent_trace_id: 上级调用链的追踪 ID。
        confidence: 对记忆内容准确性或可靠性的置信度。
        trust_level: 记忆的信任等级。
        metadata: 供适配器使用的其他自定义元数据。
    """

    source: str = "user" # 记忆来源, user, reflection, delegation, tool..
    scope: str = "user" # 记忆作用域, user, agent, shared, internal...
    agent_name: str | None = None # 产生会拥有这条记忆的Agent
    trace_id: str | None = None
    parent_trace_id: str | None = None
    confidence: float | None = None
    trust_level: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_metadata(self) -> dict[str, Any]:
        """Export scope fields as a memory adapter metadata dictionary."""
        data = dict(self.metadata)
        data["source"] = self.source
        data["scope"] = self.scope
        if self.agent_name is not None:
            data["agent_name"] = self.agent_name
        if self.trace_id is not None:
            data["trace_id"] = self.trace_id
        if self.parent_trace_id is not None:
            data["parent_trace_id"] = self.parent_trace_id
        if self.confidence is not None:
            data["confidence"] = self.confidence
        if self.trust_level is not None:
            data["trust_level"] = self.trust_level
        return data

    @classmethod
    def user(cls, *, agent_name: str | None = None, trace_id: str | None = None, **metadata: Any) -> "MemoryScope":
        """给记忆贴上用户来源的标签, 适用于用户输入的记忆"""
        return cls(source="user", scope="user", agent_name=agent_name, trace_id=trace_id, metadata=metadata)

    @classmethod
    def reflection(
            cls,
            *,
            agent_name: str | None = None,
            trace_id: str | None = None,
            parent_trace_id: str | None = None,
            **metadata: Any,
    ) -> "MemoryScope":
        """给记忆贴上反思来源的标签, 适用于模型自我反思产生的记忆"""
        return cls(
            source="reflection",
            scope="agent",
            agent_name=agent_name,
            trace_id=trace_id,
            parent_trace_id=parent_trace_id,
            metadata=metadata,
        )


MEMORY_PROMOTION_APPROVE = "approve"
MEMORY_PROMOTION_REJECT = "reject"
MEMORY_PROMOTION_REWRITE = "rewrite"
MEMORY_PROMOTION_KEEP = "keep"


@dataclass(frozen=True)
class MemoryCandidate:
    """**Non-injectable internal memory** evidence awaiting explicit promotion.

    等待明确审核/晋升的 non-injectable 记忆证据。

    Attributes:
        data: 候选记忆内容。
        memory_user_id: 保存该候选记忆的用户 ID。
        original_user_id: 最初生成该候选记忆的用户 ID。
        source: 候选记忆的来源，例如 ``user`` 或 ``reflection``。
        scope: 候选记忆可使用的范围。
        agent_name: 生成或拥有该候选记忆的智能体。
        trace_id: 生成该候选记忆的操作追踪 ID。
        parent_trace_id: 操作链中的父追踪 ID。
        run_id: 生成该候选记忆的运行 ID。
        run_group_id: 用于归类相关运行的 ID。
        confidence: 候选记忆的可选置信度评分。
        trust_level: 可选的信任级别分类。
        candidate_id: 该候选记忆的稳定唯一标识符。
        status: 晋升状态，例如 ``candidate`` 或 ``approved``。
        injectable: 是否可以将该候选记忆注入提示词。
        metadata: 适配器或应用专用的附加字段。
    """

    data: str
    memory_user_id: str
    original_user_id: str
    source: str
    scope: str
    agent_name: str | None = None
    trace_id: str | None = None
    parent_trace_id: str | None = None
    run_id: str | None = None
    run_group_id: str | None = None
    confidence: float | None = None
    trust_level: str | None = None
    candidate_id: str = field(default_factory=lambda: uuid4().hex)
    status: str = "candidate"
    injectable: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)

    def with_updates(self, **updates: Any) -> "MemoryCandidate":
        """Return a copy with selected fields changed."""
        return replace(self, **updates)

    def to_metadata(self) -> dict[str, Any]:
        """Export metadata for adapters that persist a promoted candidate."""
        data = dict(self.metadata)
        data["user_id"] = str(self.memory_user_id)
        data["original_user_id"] = str(self.original_user_id)
        data["source"] = self.source
        data["scope"] = self.scope
        data["candidate_id"] = self.candidate_id
        data["promotion_status"] = self.status
        data["injectable"] = self.injectable
        if self.agent_name is not None:
            data["agent_name"] = self.agent_name
        if self.trace_id is not None:
            data["trace_id"] = self.trace_id
        if self.parent_trace_id is not None:
            data["parent_trace_id"] = self.parent_trace_id
        if self.run_id is not None:
            data["run_id"] = self.run_id
        if self.run_group_id is not None:
            data["run_group_id"] = self.run_group_id
        if self.confidence is not None:
            data["confidence"] = self.confidence
        if self.trust_level is not None:
            data["trust_level"] = self.trust_level
        return data

    def to_dict(self, *, include_data: bool = True) -> dict[str, Any]:
        """Return a serializable representation for APIs, hooks, and tests."""
        data = {
            "candidate_id": self.candidate_id,
            "memory_user_id": str(self.memory_user_id),
            "original_user_id": str(self.original_user_id),
            "source": self.source,
            "scope": self.scope,
            "agent_name": self.agent_name,
            "trace_id": self.trace_id,
            "parent_trace_id": self.parent_trace_id,
            "run_id": self.run_id,
            "run_group_id": self.run_group_id,
            "confidence": self.confidence,
            "trust_level": self.trust_level,
            "status": self.status,
            "injectable": self.injectable,
            "metadata": dict(self.metadata),
        }
        if include_data:
            data["data"] = self.data
        return {key: value for key, value in data.items() if value is not None}


@dataclass(frozen=True)
class MemoryPromotionDecision:
    """
    Decision returned before internal memory can become prompt-injectable.

    在内部记忆内容被标记为 "`injectable`" 之前，先返回一个审核/处理决定，用来决定一条记忆是否可以被标记为可注入。

    Args:
        action: 处理动作，可选值为 ``approve``、``reject``、``rewrite`` 或
            ``keep``。
        reason: 可选的审核原因或补充说明。
        value: 可选的记忆内容；``approve`` 和 ``rewrite`` 决定可使用该值作为
            晋升后的内容。
        metadata: 与审核决定关联的额外结构化元数据。
    """

    action: str = MEMORY_PROMOTION_KEEP
    reason: str | None = None
    value: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        action = str(self.action).lower()
        if action not in {
            MEMORY_PROMOTION_APPROVE,
            MEMORY_PROMOTION_REJECT,
            MEMORY_PROMOTION_REWRITE,
            MEMORY_PROMOTION_KEEP,
        }:
            raise ValueError("MemoryPromotionDecision action must be approve, reject, rewrite, or keep")
        object.__setattr__(self, "action", action)

    @property
    def promotes(self) -> bool:
        """Return True **if** `self.action` is either `approve` or `rewrite`, indicating that the candidate memory can be promoted to prompt-injectable."""
        return self.action in {MEMORY_PROMOTION_APPROVE, MEMORY_PROMOTION_REWRITE}

    @classmethod
    def approve(
            cls,
            value: str | None = None,
            *,
            reason: str | None = None,
            metadata: dict[str, Any] | None = None,
    ) -> "MemoryPromotionDecision":
        return cls(action=MEMORY_PROMOTION_APPROVE, value=value, reason=reason, metadata=metadata or {})

    @classmethod
    def reject(
            cls,
            reason: str | None = None,
            *,
            metadata: dict[str, Any] | None = None,
    ) -> "MemoryPromotionDecision":
        return cls(action=MEMORY_PROMOTION_REJECT, reason=reason, metadata=metadata or {})

    @classmethod
    def rewrite(
            cls,
            value: str,
            *,
            reason: str | None = None,
            metadata: dict[str, Any] | None = None,
    ) -> "MemoryPromotionDecision":
        return cls(action=MEMORY_PROMOTION_REWRITE, value=value, reason=reason, metadata=metadata or {})

    @classmethod
    def keep(
            cls,
            reason: str | None = None,
            *,
            metadata: dict[str, Any] | None = None,
    ) -> "MemoryPromotionDecision":
        return cls(action=MEMORY_PROMOTION_KEEP, reason=reason, metadata=metadata or {})


@dataclass(frozen=True)
class MemoryAdmissionDecision:
    """Decision returned before a memory write is persisted."""

    allowed: bool
    reason: str | None = None
    value: str | None = None


@dataclass(frozen=True)
class MemoryPolicy:
    """
    Optional safety policy for shared memory backends.

    针对共享记忆后端的安全策略(可选) --- 并不负责记忆的保存和检索, 而是负责那些记忆可以保存, 那些记忆可以被检索注入.

    Args:
        namespace: Optional string prefix(前缀) for user IDs to isolate memory between agents or deployments.
        allow_unattributed_results: Whether to allow memory items without a user ID to be injected into context.
        allowed_sources: Optional list of allowed memory sources(记忆来源) for retrieval.
        allowed_scopes: Optional list of allowed memory scopes(基于作用域) for retrieval.
        allowed_agent_names: Optional list of allowed agent names for retrieval.
        allowed_trust_levels: Optional list of allowed trust levels for retrieval.
        min_confidence: Optional minimum confidence score for retrieval.
        enforce_expires_at: Whether to enforce expiration dates on retrieved memory items.
        memory_write_admission: Optional callable to determine whether a memory write should be persisted.
        max_writes_per_run: Optional maximum number of writes allowed per run.
        reject_duplicate_writes: Whether to reject duplicate writes within the same run.
        min_write_length: Optional minimum length for a memory write to be accepted.
        reject_write_patterns: Optional list of regex patterns that, if matched, will reject a memory write.
        memory_promotion_admission: Optional callable to determine whether a non-injectable candidate can be promoted.(回调函数, 决定是否晋升那些候选的内部记忆)
        require_promotion_for_internal_memory: Whether internal memory requires promotion before being injectable. (default: True)
        require_write_admission: Whether all writes require explicit admission approval.
    """

    namespace: str | None = None
    allow_unattributed_results: bool = True # 没有用户归属信息的记忆

    allowed_sources: Iterable[str] | None = None # 允许被召回的记忆来源, user, reflection, delegation, tool..
    allowed_scopes: Iterable[str] | None = None # 允许被召回的记忆作用域, user, agent, shared, internal...
    allowed_agent_names: Iterable[str] | None = None # 允许被召回的记忆所属的agent名称, verfied
    allowed_trust_levels: Iterable[str] | None = None # 允许被召回的记忆信任等级, 
    min_confidence: float | None = None # 允许被召回的记忆最小置信度
    enforce_expires_at: bool = False # 是否强制执行记忆过期时间

    memory_write_admission: Callable[[str, dict[str, Any]], Any] | None = None
    max_writes_per_run: int | None = None
    reject_duplicate_writes: bool = False
    min_write_length: int | None = None
    reject_write_patterns: Iterable[str] | None = None
    memory_promotion_admission: Callable[[MemoryCandidate, dict[str, Any]], Any] | None = None # 自定义的"候选记忆是否可注入"审核回调函数
    require_promotion_for_internal_memory: bool = True # 决定内部记忆是否需要进一步审核(allow_promotion)的关键字段
    require_write_admission: bool = False # 表示是否需要进行"持久化写入"的审核回调

    def __post_init__(self):
        """
        对记忆策略配置进行初始化后的规范化和校验。

        主要包括两件事：

        1. 将允许来源、作用域、Agent 名称、信任等级和拒绝模式等可迭代配置
           统一转换为元组，避免后续配置被外部可变列表意外修改。
        2. 校验 ``max_writes_per_run`` 和 ``min_write_length`` 不小于 0。

        如果这两个数值配置小于 0，会抛出 ``ValueError``。
        """
        for field_name in ("allowed_sources", "allowed_scopes", "allowed_agent_names", "allowed_trust_levels"):
            value = getattr(self, field_name)
            if value is not None and not isinstance(value, tuple):
                object.__setattr__(self, field_name, tuple(str(item) for item in value))
        if self.max_writes_per_run is not None and self.max_writes_per_run < 0:
            raise ValueError("max_writes_per_run must be greater than or equal to 0")
        if self.min_write_length is not None and self.min_write_length < 0:
            raise ValueError("min_write_length must be greater than or equal to 0")
        if self.reject_write_patterns is not None and not isinstance(self.reject_write_patterns, tuple):
            object.__setattr__(self, "reject_write_patterns", tuple(str(item) for item in self.reject_write_patterns))

    def scoped_user_id(self, user_id: str) -> str:
        """为用户 ID 添加当前策略配置的命名空间前缀。

        当配置了 ``namespace`` 时，返回 ``"{namespace}:{user_id}"``，
        用于在共享记忆后端中隔离不同租户、应用或部署的记忆。
        未配置命名空间时，返回字符串形式的原始用户 ID。

        Args:
            user_id: 原始用户 ID。

        Returns:
            可直接传给记忆后端的隔离后用户 ID。
        """
        user = str(user_id)
        if not self.namespace:
            return user
        return f"{self.namespace}:{user}"

    def allows_result(self, item: Any, scoped_user_id: str, original_user_id: str) -> bool:
        """判断检索到的记忆项是否允许注入模型上下文。

        方法会依次检查记忆项的格式、提示词注入状态、用户归属、来源、
        作用域、Agent 名称、信任等级、置信度和过期时间。只有全部通过
        当前策略配置的记忆项，才会返回 ``True``。

        对于无法解析为字典的结果，或缺少用户归属信息的结果，会根据
        ``allow_unattributed_results`` 决定是否放行。

        Args:
            item: 记忆后端返回的单条记忆结果，通常是字典。
            scoped_user_id: 加过命名空间的当前用户 ID。
            original_user_id: 未加命名空间的原始用户 ID。

        Returns:
            如果记忆可以安全地注入上下文则返回 ``True``，否则返回 ``False``。
        """
        if not isinstance(item, dict): # 不是字典就无法读取其中的用户/元数据信息
            return self.allow_unattributed_results

        metadata = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
        item_user_id = (
            item.get("user_id")
            or item.get("userId")
            or metadata.get("user_id")
            or metadata.get("userId")
        )
        # 如果该记忆或数据被拦截，则不将其注入到上下文中
        if self._blocks_prompt_injection(item, metadata):
            return False

        if item_user_id is None: # 如果提取不到用户ID, 则根据配置决定是否允许注入
            return self.allow_unattributed_results

        allowed = {str(original_user_id), str(scoped_user_id)}
        if str(item_user_id) not in allowed:
            return False

        return (
            self._allows_value(item, metadata, ("source", "memory_source"), self.allowed_sources)
            and self._allows_value(item, metadata, ("scope", "memory_scope"), self.allowed_scopes)
            and self._allows_value(item, metadata, ("agent_name", "agent"), self.allowed_agent_names)
            and self._allows_value(item, metadata, ("trust_level", "trust"), self.allowed_trust_levels)
            and self._allows_confidence(item, metadata)
            and self._allows_not_expired(item, metadata)
        )

    @staticmethod
    def _get_value(item: dict[str, Any], metadata: dict[str, Any], names: tuple[str, ...]) -> Any:
        """从记忆项本身或其 ``metadata`` 中读取第一个匹配的字段。

        优先读取记忆项顶层字段；顶层不存在时，再读取 ``metadata`` 中的
        同名字段。这个兼容逻辑允许适配不同记忆后端返回的字段结构。

        Args:
            item: 单条记忆结果的顶层字典。
            metadata: 从 ``item["metadata"]`` 提取出的元数据字典。
            names: 按优先顺序尝试读取的字段名。

        Returns:
            找到的字段值；所有字段都不存在时返回 ``None``。
        """
        for name in names:
            if name in item:
                return item.get(name)
            if name in metadata:
                return metadata.get(name)
        return None

    @classmethod
    def _allows_value(
            cls,
            item: dict[str, Any],
            metadata: dict[str, Any],
            names: tuple[str, ...],
            allowed_values: Iterable[str] | None,
    ) -> bool:
        """判断记忆项的某个字段是否符合允许值白名单。

        如果没有配置白名单，则不限制该字段；如果配置了白名单但记忆项
        缺少对应字段，则拒绝该记忆项。

        Args:
            item: 单条记忆结果的顶层字典。
            metadata: 单条记忆的元数据字典。
            names: 表示同一语义的候选字段名，例如 ``source`` 和
                ``memory_source``。
            allowed_values: 允许的字段值集合，``None`` 表示不限制。

        Returns:
            字段值存在且属于白名单，或未配置白名单时返回 ``True``；
            否则返回 ``False``。
        """
        if allowed_values is None:
            return True
        value = cls._get_value(item, metadata, names)
        if value is None:
            return False
        allowed = {str(item) for item in allowed_values}
        return str(value) in allowed

    def _allows_confidence(self, item: dict[str, Any], metadata: dict[str, Any]) -> bool:
        """判断记忆项的置信度是否达到策略要求的最低值。

        会按 ``confidence``、``score``、``trust_score`` 的顺序查找置信度。
        未配置 ``min_confidence`` 时直接放行；配置后如果缺少置信度、
        数值无法解析或低于阈值，则拒绝。

        Args:
            item: 单条记忆结果的顶层字典。
            metadata: 单条记忆的元数据字典。

        Returns:
            置信度检查通过时返回 ``True``，否则返回 ``False``。
        """
        if self.min_confidence is None:
            return True
        value = self._get_value(item, metadata, ("confidence", "score", "trust_score"))
        if value is None:
            return False
        try:
            return float(value) >= float(self.min_confidence)
        except (TypeError, ValueError):
            return False

    def _allows_not_expired(self, item: dict[str, Any], metadata: dict[str, Any]) -> bool:
        """判断记忆项是否未过期。

        支持 Unix 时间戳和 ISO 8601 时间字符串，并兼容 ``expires_at`` 与
        ``expiresAt`` 两种字段名。未配置强制过期检查时，缺少过期时间的
        记忆会被允许；启用强制检查后，缺少、格式错误或已经过期都会被拒绝。

        Args:
            item: 单条记忆结果的顶层字典。
            metadata: 单条记忆的元数据字典。

        Returns:
            记忆仍有效或不要求过期时间时返回 ``True``，否则返回 ``False``。
        """
        expires_at = self._get_value(item, metadata, ("expires_at", "expiresAt"))
        if expires_at is None:
            return not self.enforce_expires_at
        try:
            if isinstance(expires_at, (int, float)):
                expires = datetime.fromtimestamp(float(expires_at), tz=timezone.utc)
            else:
                expires = datetime.fromisoformat(str(expires_at).replace("Z", "+00:00"))
                if expires.tzinfo is None:
                    expires = expires.replace(tzinfo=timezone.utc)
        except (TypeError, ValueError):
            return False
        return expires > datetime.now(timezone.utc)

    def _blocks_prompt_injection(self, item: dict[str, Any], metadata: dict[str, Any]) -> bool:
        """判断记忆项是否必须阻止注入模型 Prompt。

        会拦截明确标记为不可注入`injectable=False`的记忆，以及处于候选、待审核、保留、
        拒绝或阻塞状态(`status`字段为`candidate`, `kept`, `rejected`, `blocked`)的记忆。对于来源或作用域属于 Agent 内部的记忆，
        如果启用了 ``require_promotion_for_internal_memory``，还必须明确
        标记为已批准或已晋升，才能被注入。

        Args:
            item: 单条记忆结果的顶层字典。
            metadata: 单条记忆的元数据字典。

        Returns:
            如果记忆存在提示词注入风险或尚未完成晋升审核，返回 ``True``；
            否则返回 ``False``。
        """
        injectable = self._get_value(item, metadata, ("injectable", "prompt_injectable", "is_injectable"))
        if injectable is not None and not self._truthy(injectable):
            return True

        status = self._get_value(item, metadata, ("promotion_status",))
        normalized_status = str(status).lower() if status is not None else None
        if normalized_status in {
            "candidate",
            "pending",
            "requires_review",
            "review_required",
            "kept",
            "non_injectable",
            "rejected",
            "blocked",
        }:
            return True

        if not self.require_promotion_for_internal_memory:
            return False

        source = self._get_value(item, metadata, ("source", "memory_source"))
        scope = self._get_value(item, metadata, ("scope", "memory_scope"))
        internal_source = source is not None and str(source).lower() in {
            "reflection",
            "delegation",
            "self_learning",
            "agent",
            "derived",
            "swarm",
            "trace",
            "tool",
        }
        internal_scope = scope is not None and str(scope).lower() in {
            "agent",
            "delegation",
            "shared",
            "internal",
            "swarm",
            "flow",
        }
        if not internal_source and not internal_scope:
            return False

        if normalized_status in {"promoted", "approved"}:
            return False
        return not self._truthy(injectable)

    @staticmethod
    def _truthy(value: Any) -> bool:
        """将不同格式的值转换为策略内部使用的布尔值。

        布尔值按原值处理，数字中非 0 值视为真；字符串中的
        ``1``、``true``、``yes``、``y``、``on``、``promoted`` 和
        ``approved`` 视为真，其余字符串视为假。

        Args:
            value: 待转换的任意值。

        Returns:
            表示该值是否为真的布尔值。
        """
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)):
            return value != 0
        return str(value).strip().lower() in {"1", "true", "yes", "y", "on", "promoted", "approved"}

    def allows_write(
            self,
            data: str,
            context: dict[str, Any] | None = None,
            *,
            write_count: int = 0,
            recent_fingerprints: set[str] | None = None,
    ) -> MemoryAdmissionDecision:
        """审核一条候选记忆是否可以持久化写入。

        方法会检查本次运行的写入次数、最小文本长度、拒绝正则、重复指纹
        和可选的自定义写入审核回调。审核回调可以返回布尔值、字符串、
        字典或 ``MemoryAdmissionDecision``；这些结果会统一转换为标准决策。
        回调也可以通过决策中的 ``value`` 对待写入文本进行替换或清洗。

        当 ``require_write_admission`` 为 ``True`` 时，没有明确审核回调或
        回调没有明确批准，都会拒绝写入；审核回调抛出异常时也会安全拒绝。

        Args:
            data: 准备写入记忆后端的文本。
            context: 与本次写入有关的上下文，例如用户、来源和作用域。
            write_count: 当前运行已经成功写入的记忆数量。
            recent_fingerprints: 当前运行中已经写入过的记忆指纹集合。

        Returns:
            描述是否允许写入，以及最终写入值或拒绝原因的
            ``MemoryAdmissionDecision``。
        """
        context = context or {}
        candidate = str(data)

        if self.max_writes_per_run is not None and write_count >= self.max_writes_per_run:
            return MemoryAdmissionDecision(
                allowed=False,
                reason=f"Memory write limit exceeded: max_writes_per_run={self.max_writes_per_run}",
            )

        if self.min_write_length is not None and len(candidate.strip()) < self.min_write_length:
            return MemoryAdmissionDecision(
                allowed=False,
                reason=f"Memory write is shorter than min_write_length={self.min_write_length}",
            )

        for pattern in self.reject_write_patterns or ():
            if re.search(pattern, candidate, flags=re.IGNORECASE):
                return MemoryAdmissionDecision(allowed=False, reason=f"Memory write rejected by pattern: {pattern}")

        fingerprint = self.write_fingerprint(candidate, context)
        if self.reject_duplicate_writes and recent_fingerprints is not None and fingerprint in recent_fingerprints:
            return MemoryAdmissionDecision(allowed=False, reason="Duplicate memory write blocked.")

        if self.memory_write_admission is None:
            if self.require_write_admission:
                return MemoryAdmissionDecision(
                    allowed=False,
                    reason="Memory write requires an explicit admission decision.",
                )
            return MemoryAdmissionDecision(allowed=True, value=candidate)

        try:
            raw_decision = self.memory_write_admission(candidate, context)
        except Exception as exc:
            return MemoryAdmissionDecision(
                allowed=False,
                reason=f"Memory write admission failed: {type(exc).__name__}",
            )
        if self.require_write_admission and raw_decision is None:
            return MemoryAdmissionDecision(
                allowed=False,
                reason="Memory write admission did not explicitly approve this write.",
            )
        return self._coerce_write_decision(raw_decision, candidate)

    def allows_promotion(
            self,
            candidate: MemoryCandidate,
            context: dict[str, Any] | None = None,
    ) -> MemoryPromotionDecision:
        """审核一条内部记忆候选是否可以晋升为可注入记忆。

        如果没有配置晋升审核回调，默认返回 ``keep``，即保留候选记录但
        不允许它进入模型上下文。回调可以批准、拒绝、保留或改写候选；
        回调异常时也会返回保守的 ``keep`` 决策。

        Args:
            candidate: 等待审核的非可注入记忆候选。
            context: 与晋升操作有关的上下文，例如候选 ID、用户和运行信息。

        Returns:
            描述晋升动作、最终文本、原因和附加元数据的
            ``MemoryPromotionDecision``。
        """
        if self.memory_promotion_admission is None: # 如果没有配置晋升审核回调, 就采用 `keep` 的决定, 理由是"requires explicit approval"
            return MemoryPromotionDecision.keep("Memory promotion requires explicit approval.")
        try: # 有就调用回调函数获得原始晋升审核结果
            raw_decision = self.memory_promotion_admission(candidate, context or {})
        except Exception as exc: # 回调函数抛出异常时, 也返回 `keep` 的决定, 理由是"admission_error_type"
            return MemoryPromotionDecision.keep(
                f"Memory promotion admission failed: {type(exc).__name__}",
                metadata={"admission_error_type": type(exc).__name__},
            )
        return self._coerce_promotion_decision(raw_decision, candidate.data)

    @staticmethod
    def write_fingerprint(data: str, context: dict[str, Any] | None = None) -> str:
        """为候选记忆写入生成轻量级去重指纹。

        指纹由记忆用户 ID、来源、作用域、Agent 名称和规范化后的文本组成。
        文本会转为小写并压缩连续空白，因此仅大小写或空白不同的内容会被
        视为同一作用域下的重复写入，而不同用户或不同来源仍保持隔离。

        Args:
            data: 候选记忆文本。
            context: 包含作用域信息的写入上下文。

        Returns:
            可放入指纹集合进行重复检测的字符串。
        """
        context = context or {}
        normalized = " ".join(str(data).lower().split())
        scope_key = "|".join(
            str(context.get(key, ""))
            for key in ("memory_user_id", "source", "scope", "agent_name")
        )
        return f"{scope_key}|{normalized}"

    @staticmethod
    def _coerce_write_decision(raw_decision: Any, current_value: str) -> MemoryAdmissionDecision:
        """将写入审核回调的各种返回格式转换为标准决策对象。

        支持直接返回 ``MemoryAdmissionDecision``、``True``、``False``、
        ``None``、字符串、字典或其他值。简单返回值会被解释为允许/拒绝，
        字典可以通过 ``allowed``、``reason`` 和 ``value`` 指定完整结果。

        Args:
            raw_decision: 写入审核回调返回的原始结果。
            current_value: 当前准备写入的文本，用作默认写入值。

        Returns:
            统一格式的 ``MemoryAdmissionDecision``。
        """
        if isinstance(raw_decision, MemoryAdmissionDecision):
            return raw_decision
        if raw_decision is None or raw_decision is True:
            return MemoryAdmissionDecision(allowed=True, value=current_value)
        if raw_decision is False:
            return MemoryAdmissionDecision(allowed=False, reason="Memory write admission blocked this write.")
        if isinstance(raw_decision, str):
            return MemoryAdmissionDecision(allowed=False, reason=raw_decision)
        if isinstance(raw_decision, dict):
            return MemoryAdmissionDecision(
                allowed=bool(raw_decision.get("allowed", True)),
                reason=raw_decision.get("reason"),
                value=raw_decision.get("value", current_value),
            )
        return MemoryAdmissionDecision(allowed=True, value=str(raw_decision))

    @staticmethod
    def _coerce_promotion_decision(raw_decision: Any, current_value: str) -> MemoryPromotionDecision:
        """将晋升审核回调的各种返回格式转换为标准决策对象。

        支持直接返回 ``MemoryPromotionDecision``、布尔值、字符串、字典或
        ``None``。字典可以使用 ``action`` 指定动作，也可以使用
        ``allowed`` 或 ``promote`` 表达批准/拒绝；如果提供了不同于当前
        文本的 ``value``，会转换为改写（``rewrite``）决策。

        Args:
            raw_decision: 晋升审核回调返回的原始结果。
            current_value: 当前候选记忆文本，用作默认晋升值。

        Returns:
            统一格式的 ``MemoryPromotionDecision``。
        """
        if isinstance(raw_decision, MemoryPromotionDecision):
            return raw_decision
        if raw_decision is None:
            return MemoryPromotionDecision.keep("Memory promotion callback did not approve this candidate.")
        if raw_decision is True:
            return MemoryPromotionDecision.approve(current_value)
        if raw_decision is False:
            return MemoryPromotionDecision.reject("Memory promotion callback rejected this candidate.")
        if isinstance(raw_decision, str):
            return MemoryPromotionDecision.reject(raw_decision)
        if isinstance(raw_decision, dict):
            action = raw_decision.get("action")
            if action:
                return MemoryPromotionDecision(
                    action=str(action),
                    reason=raw_decision.get("reason"),
                    value=raw_decision.get("value"),
                    metadata=raw_decision.get("metadata") or {},
                )
            allowed = raw_decision.get("allowed", raw_decision.get("promote"))
            if allowed is True:
                value = raw_decision.get("value", current_value)
                if value != current_value:
                    return MemoryPromotionDecision.rewrite(
                        str(value),
                        reason=raw_decision.get("reason"),
                        metadata=raw_decision.get("metadata"),
                    )
                return MemoryPromotionDecision.approve(
                    str(value),
                    reason=raw_decision.get("reason"),
                    metadata=raw_decision.get("metadata"),
                )
            if allowed is False:
                return MemoryPromotionDecision.reject(
                    raw_decision.get("reason"),
                    metadata=raw_decision.get("metadata"),
                )
            if "value" in raw_decision:
                return MemoryPromotionDecision.rewrite(
                    str(raw_decision["value"]),
                    reason=raw_decision.get("reason"),
                    metadata=raw_decision.get("metadata"),
                )
            return MemoryPromotionDecision.keep(
                raw_decision.get("reason"),
                metadata=raw_decision.get("metadata"),
            )
        return MemoryPromotionDecision.keep("Memory promotion callback returned an unsupported decision.")
