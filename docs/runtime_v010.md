# LightAgent v0.10 Runtime

LightAgent v0.10 adds an opt-in, event-sourced runtime beneath the compatible
`agent.run()` API. Basic agents still require no database or runtime setup.

## Durable Sessions

```python
from LightAgent import LightAgent, SqliteSessionStore

store = SqliteSessionStore(".lightagent/sessions.sqlite3")
agent = LightAgent(
    model="deepseek-v4-flash",
    api_key="your_api_key",
    base_url="your_base_url",
    session_store=store,
)

agent.run("Remember this project decision", session_id="project-42")
agent.run("What did we decide?", session_id="project-42")

print(agent.replay_session("project-42"))
checkpoint = agent.checkpoint_session("before-implementation")
fork = agent.fork_session(through_sequence=checkpoint["sequence"])
```

`InMemorySessionStore`, `JsonlSessionStore`, and `SqliteSessionStore` implement
the same contract. Events are append-only, sequence-validated, versioned, and
credential fields are redacted before persistence. `ContextProjector` rebuilds
conversation context, exact model requests, and compatible trace views from
the event log.

## Async Usage

```python
result = await agent.arun("Analyze the incident")

stream = await agent.arun("Analyze the incident", stream=True)
async for chunk in stream:
    print(chunk)
```

The async entry point keeps synchronous v0.9 model and tool clients compatible
by isolating them in a worker thread. Native async Providers and background
Jobs execute on the caller's event loop.

## Capabilities And Policy

```python
from LightAgent import (
    BaseCapabilityProvider,
    CapabilityRegistry,
    CapabilitySpec,
    PolicyDecision,
    PolicyEngine,
)

def workspace_policy(request):
    if request.capability.write and request.context.metadata.get("read_only"):
        return PolicyDecision.block("workspace is read-only")
    return PolicyDecision.allow(request.arguments)

registry = CapabilityRegistry(policy_engine=PolicyEngine([workspace_policy]))
```

Providers declare lifecycle methods and capability metadata for read, write,
network, execution, persistence, risk, timeout, output limits, cancellation,
and approval. Runtime, Session, and Agent scopes resolve deterministically;
equal-scope conflicts are available through `registry.conflicts()`.

`ToolProviderAdapter`, `MemoryProviderAdapter`, `SkillProviderAdapter`,
`MCPProviderAdapter`, and `WorkflowProviderAdapter` bridge existing LightAgent
APIs into the registry. Sensitive tool calls made by `LightAgent` pass through
the registry's `PolicyEngine` before existing Guardrails and Hooks.

## Long-Task State

Every `LightAgent` exposes `agent.runtime`:

```python
goal = agent.runtime.goals.create(
    "Prepare the release",
    acceptance_criteria=["tests pass", "artifacts build"], # 验收标准
)
agent.runtime.goals.activate(goal.goal_id) # status: PENDING -> ACTIVE  
gent.runtime.inbox.enqueue("steering", "Do not publish yet", message_id="release-hold")#
gent.runtime.pause("waiting for CI") # 当前会话Runtime暂停, 会追加事件 `session.paused`
```

The runtime includes ordered and idempotent Inbox messages, durable Goals,
model/tool/token/time/cost budgets, progress-loop detection, cancellable Jobs,
and bounded subagent registration with narrowing-only permission snapshots.
Restoring a Session rebuilds Inbox, Goal, Budget, and interrupted Job state.

> Runtime 包含有顺序且幂等的 Inbox 消息、持久化目标、模型/工具/token/时间/成本预算、进度循环检测、可取消的后台 Job，以及有数量限制的子 Agent 注册机制；子 Agent 使用只能收紧、不能扩大的权限快照
> 恢复一个 Session 时，Runtime 会重建 Inbox、Goal、Budget，以及被中断的 Job 状态

As of v0.10.2, Jobs accept `idempotency_key` and `cancellation_token`. Reusing a
Job idempotency key returns its existing record instead of scheduling duplicate
work. Operations that accept a `cancellation_token` keyword receive a child
token, so parent cancellation propagates without granting the child authority
over the parent token. Subagent runs use the same cooperative token contract and
forward an optional idempotency key when the child API supports it.

As of v0.11.0, a Job may also use `lease_seconds`. Results produced after lease
expiry are not published; the record becomes `interrupted`. An interrupted Job
can be resumed with a new operation and incremented fencing epoch, while
`renew_lease()` rejects stale epochs. This protects runtime state from a late
worker but cannot roll back an external side effect.

> fencing epoch 可以理解成是版本号码, 处于`interrupted`的job在恢复时, 会有更大的版本号

## Unified Security Context

v0.11.0 adds `SecurityContext` as the identity and authority snapshot shared by
Runtime, Capability Providers, and LightDAG. Child contexts can narrow allowed
capabilities, resources, risk, network access, sandbox requirements, and
deadlines, but cannot widen them. `AgentRuntime.open_session(...,
security_context=context)` binds the context to the opened Session.

`CapabilityGate` applies permissions and Policy before Provider invocation.
For an approval-required capability, pass an `ApprovalToken` bound to the exact
operation, canonical arguments, tenant/project/run/task/attempt identity,
resource, and policy version. Tokens expire and are single-use by default.
`ProviderManifest` records provider and capability digests without serializing
raw secret configuration.

See [LightDAG](lightdag.md) for dynamic verified multi-agent execution.

## Context And Knowledge

`ContextBudget` and `ContextCompactor` provide deterministic trimming,
optional summarization, and SHA-256 references for oversized tool output.
Compaction decisions are Session events. Checkpoints and forks retain source
event lineage.

`SqliteFTSRetrievalProvider` is a dependency-free minimum RAG implementation:

```python
from LightAgent import RetrievalDocument, SqliteFTSRetrievalProvider

rag = SqliteFTSRetrievalProvider(".lightagent/knowledge.sqlite3")
rag.ingest(RetrievalDocument(
    content="The production deployment uses blue-green releases.",
    title="Deployment guide",
    source="docs/deployment.md",
    tenant_id="acme",
))

for result in rag.search("deployment", tenant_id="acme"):
    print(result.citation_id, result.content)
```

`SessionSearchProvider` is intentionally separate from knowledge-base RAG and
returns citations in `session:<session_id>:<sequence>` form.

## Skills And MCP

Skill directories are processed in declared order; later directories shadow
earlier entries and conflicts are reported by `SkillManager.list_conflicts()`.
`discover_project_instructions()` loads nested `AGENTS.md` files from root to
the working directory without modifying them.

MCP retains stdio and SSE configuration compatibility and adds opt-in
Streamable HTTP (`transport: streamable-http`), reconnect attempts, tool-list
refresh, namespace isolation, and external credential-header resolution.

> MCP 保留了 stdio(标准输入输出) 和 SSE 配置的**兼容性**，并新增了可选的 Streamable HTTP（transport: streamable-http）、重连尝试、工具列表刷新、命名空间隔离以及外部凭据 Header 解析功能。

## Compatibility Boundary

- `agent.run("hello")`, `stream=True`, structured results, Hooks, Guardrails,
  Memory, LightSwarm, and LightFlow remain compatible.
- Browser, Terminal, Shell, LSP, vector database, hosted service, and WebUI
  implementations remain optional Providers rather than core dependencies.
- Session and Capability APIs are pre-1.0 contracts and may receive additive
  changes before the v1.0 API freeze.
