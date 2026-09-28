# 04 支撑模块源码知识库（supporting modules）

> 覆盖：`__init__.py` 公共 API 面 + errors / result / version / logger / hooks / guardrails / review / tracing / evaluation / capabilities / knowledge / litellm_client。
> 行号均为 2026-09-28 工作树实测 `def/class` 行号，可直接用于架构图节点定位。

---

# __init__.py 公共 API 面（LightAgent/__init__.py）

文件结构：L1-L161 为各子模块 re-import，L163-L309 为 `__all__`（约 147 个导出）。本包是纯"门面"，自身无逻辑。

用户最常用导出（来源模块:行号，行号已在对应源文件核实）：

| 导出符号 | 来源 | 一句话 |
|---|---|---|
| `__version__` | version.py:9 | 版本号，当前 "0.10.1" |
| `LightAgent` | core.py:116 | 核心单 Agent 类 |
| `LightSwarm` | core.py:3173 | 多 Agent 编排（教学级） |
| `ToolRegistry` / `ToolLoader` / `AsyncToolDispatcher` | tools.py:26 / 224 / 281 | 工具注册、加载、异步分发 |
| `LightAgentErrorInfo` / `LightAgentError` / `ERROR_TAXONOMY` | errors.py:14 / 21 / 45 | 错误信息结构 / 可捕获异常 / 错误码表 |
| `classify_exception` / `format_lightagent_error` / `format_error_code` | errors.py:154 / 197 / 206 | 异常归类 / 格式化异常 / 格式化错误码 |
| `RunResult` / `StreamEvent` | result.py:14 / 30 | 非流式结构化结果 / 流式事件 |
| `TraceEvent` / `TraceSummary` / `TraceRecorder` / `JsonlTraceExporter` | tracing.py:17 / 42 / 229 / 97 | 追踪事件 / 汇总指标 / 采集器 / JSONL 导出 |
| `summarize_trace` / `normalize_usage` / `export_trace` | tracing.py:152 / 122 / 211 | 轨迹汇总 / usage 归一 / 轨迹导出 |
| `EvaluationCase` / `EvaluationCaseResult` / `EvaluationReport` / `LightEvaluator` | evaluation.py:18 / 36 / 63 / 103 | 回归评测用例 / 单例结果 / 汇总报告 / 评测器 |
| `HookContext` / `HookDecision` / `HookManager` / `PolicyHook` | hooks.py:26 / 43 / 95 / 73 | 钩子上下文 / 决策 / 管理器 / 策略钩子 |
| `ApprovalRequest` / `ApprovalDecision` / `HumanApprovalHook` / `HumanFeedback` / `InMemoryReviewStore` / `JsonReviewStore` | review.py:37 / 65 / 235 / 110 / 127 / 181 | 人工审批请求 / 决策 / 失败关闭审批钩子 / 人评标注 / 审批存储 |
| `GuardrailDecision` / `GuardrailManager` / `DEFAULT_PRIVACY_PATTERNS` / `privacy_input_guardrail` / `sensitive_tool_confirmation_guardrail` / `high_risk_parameter_guardrail` / `output_redaction_guardrail` | guardrails.py:15 / 24 / 88 / 96 / 113 / 130 / 150 | 护栏决策 / 护栏管理器 / 隐私正则 / 四个内置护栏工厂 |
| `CapabilityScope` / `CapabilityRisk` / `CapabilitySpec` / `CapabilityRegistry` / `PolicyEngine` / `PolicyDecision` / `PermissionSet` / `BaseCapabilityProvider` / `ToolProviderAdapter` / `MemoryProviderAdapter` | capabilities.py:16 / 23 / 30 / 370 / 293 / 269 / 213 / 175 / 578 / 603 | 能力作用域 / 风险级 / 能力规格 / 注册表 / 策略引擎 / 策略决策 / 权限集 / 生命周期基类 / 两个适配器 |
| `RetrievalDocument` / `RetrievalResult` / `RetrievalProvider` / `SqliteFTSRetrievalProvider` / `SessionSearchProvider` / `SkillProviderAdapter` / `MCPProviderAdapter` / `WorkflowProviderAdapter` | knowledge.py:23 / 39 / 58 / 78 / 302 / 341 / 370 / 393 | 检索文档 / 检索结果 / Provider 协议 / SQLite FTS5 RAG / 会话搜索 / 三个适配器 |
| `LiteLLMClient` | litellm_client.py:33 | openai.OpenAI 替身，走 litellm |
| `LoggerManager` | logger.py:14 | 日志集中管理 |
| `Session` / `SessionStore` / `InMemorySessionStore` / `JsonlSessionStore` / `SqliteSessionStore` | session.py:195 / 377 / 394 / 435 / 521 | 会话与三种存储（非本次精读范围） |
| `LightFlow` / `LightFlowStep` / `LightFlowResult` / `JsonLightFlowStore` | flow.py:132 / 41 / 83 / 102 | 轻流程编排（非本次精读范围） |
| `SkillManager` / `Skill` | skills.py:34 / 21 | 技能管理（非本次精读范围） |
| `MCPClientManager` | mcp_client_manager.py:26 | MCP 客户端管理（非本次精读范围） |
| `SharedMemoryPool` / `SharedMemoryRecord` | shared_memory.py:40 / 20 | 共享内存池（非本次精读范围） |

---

# errors.py（LightAgent/errors.py）

## 模块概览
定义 LightAgent 的稳定错误码体系：一张 21 项的错误分类表 `ERROR_TAXONOMY`、可捕获的结构化异常 `LightAgentError`，以及三个纯函数工具——把任意异常归类成稳定错误码（`classify_exception`）、把异常/错误码格式化成面向用户的一行文本（`format_lightagent_error` / `format_error_code`）。模块无第三方依赖，是全框架错误信息的单一事实来源。

## 类与符号清单
- `LightAgentErrorInfo` (L14-L18)：frozen dataclass，三元组 `code/message/guidance`，错误码表的行结构。
- `LightAgentError` (L21-L42)：可捕获异常，构造时按 code 查表填充 message/guidance，未知 code 回退 LA-UNKNOWN（L31）。
- `ERROR_TAXONOMY` (L45-L151)：dict，21 个稳定错误码 → `LightAgentErrorInfo`。
- `classify_exception` (L154-L194)：按 `status_code` 与异常名/文本关键词把任意异常映射到错误码。
- `format_lightagent_error` (L197-L203)：异常 → `[code] message Action:… Guidance:… Details:…` 一行文本。
- `format_error_code` (L206-L212)：已知错误码 + details → 一行文本。

## 关键方法
- `LightAgentError.__init__` (L24-L36) — 用 code 查 `ERROR_TAXONOMY` 填默认 message/guidance，message/guidance 可覆盖；被用户代码捕获使用（框架主循环内部不抛它，见"阅读陷阱"）。
- `classify_exception` (L154) — 先读 `exc.status_code`（无则读 `exc.response.status_code`，L156-L158），HTTP 400/401/403/404/408/413/429/500|502/503|504 直接映射（L160-L177）；再按异常类名/消息文本关键词匹配 authentication、permission、not found、timeout、rate limit、context length（L179-L192）；兜底 default_code。调用方：`format_lightagent_error` (errors.py:199)。
- `format_lightagent_error` (L197) — `classify_exception` + 拼 Action/Guidance/Details；调用方：core.py:729、2099、2376、2466、2589、2649（模型请求/工具执行/流式/移交等 catch 点），tools.py:343。
- `format_error_code` (L206) — 已知码 + details 直接格式化；调用方：core.py:1017/1084/1139（LA-BUDGET）、1070（LA-HOOK）、1206（LA-GUARDRAIL）、1271（LA-SANDBOX）、1287（LA-POLICY 文本）、1951、2359（LA-JSON），tools.py:305/362/370/374（LA-TOOL）。

## 关键机制细节
### 错误码清单（码值 → 含义 → 指导方向）
| 码值 | 含义 | guidance 要点 |
|---|---|---|
| LA-400 | 发给模型提供商的请求无效 | 检查请求参数、工具 schema、消息格式、模型名 |
| LA-401 | 认证失败 | 检查 api_key / OPENAI_API_KEY |
| LA-403 | 提供商因权限或策略拒绝 | 检查账号权限、模型访问、配额 |
| LA-404 | 端点或模型不存在 | 检查 base_url（OpenAI 兼容服务器应以 /v1 结尾）与 model |
| LA-408 | 模型请求超时 | 重试、减小输入、调大超时 |
| LA-413 | 请求/响应超过提供商上限 | 缩减 prompt、历史、工具输出、补全长度 |
| LA-429 | 触发限流或配额 | 等待重试、降并发、查配额与账单 |
| LA-500 | 提供商服务器错误 | 稍后重试或换端点（502 也归此码，L174） |
| LA-503 | 提供商暂时不可用 | 稍后重试或用备用模型（504 也归此码，L176） |
| LA-JSON | 工具调用参数无法解析为 JSON | 检查模型返回的 tool-call JSON 是否匹配 schema |
| LA-TOOL | 工具执行失败 | 检查工具实现、参数、依赖、外部服务凭据 |
| LA-GUARDRAIL | 配置的护栏拦截了操作 | 审查输入/工具/输出护栏策略 |
| LA-HOOK | 配置的运行期钩子拦截了操作 | 审查钩子决策、phase、应用策略 |
| LA-POLICY | 统一能力策略拒绝了操作 | 审查 Provider scope、权限快照、审批要求 |
| LA-SANDBOX | 操作要求显式沙箱 | 先注册隔离的 SandboxProvider |
| LA-BUDGET | 运行期预算耗尽 | 提高预算或收窄目标/工具集/上下文 |
| LA-SESSION | 会话持久化或重放失败 | 检查 SessionStore、事件序列、schema 版本、checkpoint |
| LA-PROVIDER | 能力 Provider 失败或不可用 | 检查 Provider 健康、生命周期、配置摘要、可选依赖 |
| LA-APPROVAL | 操作等待显式审批 | 处理审批请求后恢复同一 Session/工作流 |
| LA-CANCELLED | run/Job/工作流/Session 被取消 | 检查取消事件，可恢复则从 checkpoint 恢复 |
| LA-UNKNOWN | 未预期错误（兜底） | 开 debug 日志看原始异常 |

### 命名与归类规则
- HTTP 状态码类：`LA-<HTTP码>`（500 系特例：502→LA-500、504→LA-503，L174/L176）。
- 语义类：`LA-<域词>`（JSON/TOOL/GUARDRAIL/HOOK/POLICY/SANDBOX/BUDGET/SESSION/PROVIDER/APPROVAL/CANCELLED/UNKNOWN）。
- 文本关键词匹配按小写子串进行（L179-L192），顺序敏感：authentication → permission → notfound → timeout → ratelimit/quota → context length。

## 与其他模块的关系
| 本模块符号:行号 | 对方模块.符号 | 说明 |
|---|---|---|
| `format_lightagent_error`/`format_error_code`:197/206 | core.py:38（import） | 主循环所有 catch 点的统一错误文案出口 |
| 同上 :206 | tools.py:19（import） | 工具执行/参数校验失败文案（LA-TOOL） |
| `ERROR_TAXONOMY`:45 | core.py:1017/1070/1206/1271/2359 | LA-BUDGET/LA-HOOK/LA-GUARDRAIL/LA-SANDBOX/LA-JSON 的具体产出点 |
| `LightAgentError`:21 | `__init__.py:20-27` | 仅作为公共 API 导出给用户捕获 |

## 阅读陷阱
1. 框架主循环几乎不 `raise LightAgentError`：core.py 只 import 了两个格式化函数（core.py:38），错误以**字符串**写进返回值/trace，`LightAgentError` 是给用户侧代码用的异常形态。
2. `classify_exception` 的文本匹配是"包含子串"（如消息里含 "too large" 就判 LA-413），可能误归类。
3. 未知 code 传入 `LightAgentError` 不报错，静默变成 LA-UNKNOWN（L31）；自定义新码必须先进 `ERROR_TAXONOMY`。
4. LA-500 覆盖 502、LA-503 覆盖 504，与直觉的"每个状态码一项"不同。

## 高频符号中文短语表
| 符号 | 中文短语 |
|---|---|
| `LightAgentErrorInfo` | 错误码三元组（码/消息/指导） |
| `LightAgentError` | 可捕获的结构化异常 |
| `ERROR_TAXONOMY` | 21 项稳定错误码总表 |
| `classify_exception` | 异常归类到稳定错误码 |
| `format_lightagent_error` | 异常转用户可读错误文本 |
| `format_error_code` | 错误码转带指导的文本 |

---

# version.py（LightAgent/version.py)

## 模块概览
单行版本声明模块，仅 L9 `__version__ = "0.10.1"`（文件头注释"最后更新 2026-08-09"）。

## 类与符号清单
- `__version__` (L9)：包版本字符串。

## 关键方法
无。`__init__.py:9` re-export；core.py:28-117 将其挂到 LightAgent 实例属性 `__version__`（core.py:117）。

## 关键机制细节
- 版本号 "0.10.1" 与本地 editable 安装元数据 0.10.0 存在偏差（见 AGENTS.md 工作区说明），以源码 L9 为准。

## 与其他模块的关系
| 本模块符号:行号 | 对方模块.符号 | 说明 |
|---|---|---|
| `__version__`:9 | `__init__.py:9` / core.py:28 | 导出与实例属性来源 |

## 阅读陷阱
1. `__version__` 在 core.py:117 被赋成实例属性，同名但作用域不同（实例级 vs 模块级）。

## 高频符号中文短语表
| 符号 | 中文短语 |
|---|---|
| `__version__` | 包版本号 0.10.1 |

---

# result.py（LightAgent/result.py）

## 模块概览
定义两个轻量结构化返回值：非流式 `RunResult` 与流式 `StreamEvent`。让 `run(result_format=...)` 在保持字符串兼容的同时提供机器可读输出（含 trace 与 usage），是评测与观测的返回值契约。

## 类与符号清单
- `RunResult` (L14-L27)：非流式结果——content、reasoning_content、tool_calls、usage、trace_id、trace（事件列表）、error；`__str__` 直接返回 content（L26-L27）。
- `StreamEvent` (L30-L39)：流式事件——type/data/trace_id；`__str__` 返回 str(data)（L38-L39）。

## 关键方法
- `RunResult.__str__` (L26) — 打印即输出 content，让 `print(run(...))` 行为与旧字符串 API 一致。
- `StreamEvent.__str__` (L38) — 打印即输出 data。

## 关键机制细节
- 构造点：core.py:1394 在 `_format_run_result`（core.py:1384）里组装 `RunResult`；core.py:1424-L1434 在 `_stream_as_events`（core.py:1415）里把流 chunk 包装为 `StreamEvent(type="error|tool_result|tool_call|event|content", ...)`。
- `run()` 的返回类型注解 `Union[Generator, str, RunResult]`（core.py:498），`result_format="object"→RunResult`、"event"→StreamEvent、"str"→兼容旧字符串。

## 与其他模块的关系
| 本模块符号:行号 | 对方模块.符号 | 说明 |
|---|---|---|
| `RunResult`:14 | core.py:39（import）、1394 | run() 非流式结构化返回 |
| `StreamEvent`:30 | core.py:39（import）、1424-1434 | run(stream=True, result_format="event") 的产出 |
| `RunResult.trace/usage` | tracing.py:summarize_trace:152 | 被 evaluation.py:127-131 直接消费 |

## 阅读陷阱
1. `RunResult.usage` 是 dict 而非对象；`trace` 是 dict 事件列表（非 TraceEvent 实例），因为它们就是 `TraceRecorder.to_list()` 的产物。
2. `StreamEvent.type` 取值（error/tool_result/tool_call/event/content）与 TraceEvent.type 体系相近但**不是**同一套，别混用。

## 高频符号中文短语表
| 符号 | 中文短语 |
|---|---|
| `RunResult` | 非流式结构化运行结果 |
| `StreamEvent` | 流式结构化事件 |
| `RunResult.trace` | 携带结构化轨迹列表 |
| `RunResult.error` | 错误字符串（非异常） |

---

# logger.py（LightAgent/logger.py）

## 模块概览
对标准库 logging 的薄封装 `LoggerManager`：按实例名创建（复用）named logger，debug 模式加控制台 handler，可选写文件，并在日志前缀里带 TraceID。服务于 LightAgent 实例的过程日志，与结构化追踪（tracing.py）互相独立。

## 类与符号清单
- `LoggerManager` (L14-L65)：集中管理一个 named logger 的构建与带 TraceID 的输出。

## 关键方法
- `__init__` (L17-L21) — 保存 name/debug/traceid，调用 `_setup_logger`。
- `_setup_logger` (L23-L45) — `logging.getLogger(name)`；`propagate=False`（L26）；debug 时加 StreamHandler（L30-L33）；log_file 时建目录并加 FileHandler（L35-L43）。调用方：`__init__`（L20）。
- `log` (L47-L61) — **非 debug 直接 return（L49-L50）**；拼 TraceID 前缀，UTF-8 清洗后按 DEBUG/INFO/ERROR 三级输出。调用方：core.py:478（`self.logger.log(level, action, data)` 封装）。
- `set_traceid` (L63-L65) — 设置当前跟踪 ID；调用方：core.py:571。

## 关键机制细节
- 日志格式固定 `%(asctime)s [%(levelname)s] %(message)s`（L28）。
- TraceID 以 `[TraceID: xxx] ` 前缀进消息体（L52），不是 logging extra 字段。
- `log` 只支持 DEBUG/INFO/ERROR 三个级别字符串（L56-L61），其他值静默丢弃。

## 与其他模块的关系
| 本模块符号:行号 | 对方模块.符号 | 说明 |
|---|---|---|
| `LoggerManager`:14 | core.py:36（import）、253 | LightAgent.__init__ 里构造 |
| `log`:47 | core.py:478 | 过程日志统一出口 |
| `set_traceid`:63 | core.py:571 | run() 开始时绑定 traceid |

## 阅读陷阱
1. **log_file 依赖 debug 开关**：`log()` 开头非 debug 即 return（L49），不开 debug 连文件都不写。
2. 同名 logger 复用 + 每次 `addHandler`（L33/L43）：同进程创建多个 LightAgent 实例会叠加 handler，日志重复输出。
3. `self.traceid` 是实例级可变状态，多线程共享同一实例时会串。

## 高频符号中文短语表
| 符号 | 中文短语 |
|---|---|
| `LoggerManager` | named logger 集中管理 |
| `log` | 带 TraceID 的三级日志 |
| `set_traceid` | 绑定当前跟踪 ID |

---

# hooks.py（LightAgent/hooks.py）

## 模块概览
运行期生命周期钩子原语：`HookContext`（上下文）、`HookDecision`（决策：continue/replace/block/retry/fallback/metadata）、`PolicyHook`（显式失败策略：block 或 continue + 超时）、`HookManager`（按列表序执行、隔离可观测性钩子的失败、支持同步/异步钩子与超时）。是 core 主循环与 LightFlow 的"中间件层"。

## 类与符号清单
- 常量 `HOOK_CONTINUE/REPLACE/BLOCK/RETRY/FALLBACK/METADATA` (L18-L23)：六种决策动作字符串。
- `HookContext` (L26-L40)：phase + payload + trace_id/parent_trace_id/run_id/run_group_id/user_id/agent_name/flow_id/step_name + metadata。
- `HookDecision` (L43-L70)：action/payload/reason/metadata；五个 classmethod 构造器（continue_ L52、replace L56、block L61、retry L64、fallback L68）。
- `PolicyHook` (L73-L92)：frozen；handler + phases 白名单 + failure_mode("block"|"continue") + timeout(>0) + name；`__post_init__` 校验（L83-L92）。
- `HookManager` (L95-L179)：按序运行钩子并归一决策。

## 关键方法
- `HookManager.run` (L101) — 主流程：按列表序执行；PolicyHook 先做 phase 过滤（L109-L110）；异常时无 policy → 记 error 事件后 continue（L120-L140），policy.failure_mode="block" → fail-closed 返回 block（L130-L139）；`replace` 覆盖 payload 后继续（L145-L153）；`metadata` 只记事件（L155-L161）；`block/retry/fallback` 立即返回并附加累积 metadata 与 hook_events（L163-L173）；全部通过则返回 continue + 最终 payload（L175-L179）。调用方：core.py:956（`_run_hooks` 内 `self.hooks.run(context)`），flow.py:805 附近（步骤钩子）。
- `_call_hook` (L181) — 鸭子类型分发：钩子若实现了与 phase 同名方法（如 `before_tool_call`）则调用它，否则把钩子本身当可调用对象调用（L182-L188）。
- `_invoke_hook` (L190) — 带超时版本：隔离 HookContext 副本 + 单线程 ThreadPoolExecutor，超时抛 TimeoutError（L213-L221）。
- `_call_and_resolve` (L223) / `_run_awaitable` (L230) — 同步/异步统一：返回 awaitable 时，无运行中事件循环则 `asyncio.run`；有则另起线程跑新事件循环（L230-L239）。
- `_normalize` (L241) — 把钩子的任意返回值归一为 HookDecision：None→continue；bool False→block；str→block(reason)；dict 支持 allowed/action/payload 四种形态（L241-L265）。

## 关键机制细节
### 事件（phase）类型清单与触发时机（core.py 调用点实测）
| phase 字符串 | 触发时机 | core.py 调用点 |
|---|---|---|
| `before_run` | run() 入口、参数与预算检查前 | L580 |
| `before_model_request` | 每次调用模型前（含重试轮） | L1074 |
| `before_tool_call` | 工具分发前（含沙箱/策略检查后） | L1301 |
| `after_tool_result` | 工具结果回填前 | L1314 |
| `after_model_response` | 模型最终回复产出后、输出护栏前后 | L1325 |
| `on_error` | 任意错误发生时 | L1028、L1063 |
| `after_run` | run 收尾（on_error 之后） | L1029 |
| `on_handoff` | Swarm 子代理移交前 | L2540 |
| `before/after_memory_retrieve` | 记忆检索前后 | L1495 / L1515 |
| `before/after_memory_write` | 记忆写入前后 | L1559 / L1631、L1799 |
| `before/after_memory_promote` | 记忆候选晋升前后 | L1696 / L1790 |

LightFlow 的步骤钩子：flow.py:138 构造 HookManager，flow.py:786-787 构建 HookContext，flow.py:445/805 检查 HOOK_BLOCK。

### 决策流转
- `replace`：替换后续 payload（可改写工具参数、模型请求参数），链式传给下一个钩子。
- `block`：中断当前操作；core.py:971 将其镜像为 trace 事件 `hook_block`。
- `hook_events`：每个钩子的执行结果事件数组附在最终决策 metadata 里，core.py:957-968 逐条转成 `hook_decision` trace 事件；review 的 `review_events` 也在 metadata 里被同段代码转为 `approval_*` trace 事件。

## 与其他模块的关系
| 本模块符号:行号 | 对方模块.符号 | 说明 |
|---|---|---|
| `HookManager`:95 / `HookContext`:26 | core.py:41（import）、226、941-956 | 主循环钩子调度 |
| `HookDecision`:43 | review.py:16（import） | HumanApprovalHook 的返回类型 |
| `HookDecision`:43 | flow.py:20、138、786 | LightFlow 步骤钩子 |
| `PolicyHook`:73 | core.py:41（import）、146 | 构造参数 `hooks: List[Callable | PolicyHook]` |
| `HOOK_BLOCK`:20 | core.py:41、970 | 主循环只消费 block 决策 |

## 阅读陷阱
1. **默认吞异常**：普通钩子抛异常被静默 continue（L120），只有包成 `PolicyHook(failure_mode="block")` 才 fail-closed——想让钩子失败可感知必须用 PolicyHook。
2. `HOOK_RETRY`/`HOOK_FALLBACK` 只在 hooks.py:21-22 定义，core.py/flow.py 均**未实现**对应语义（core.py 只 import HOOK_BLOCK），返回这两种决策实际不会被特殊处理。
3. 从钩子返回裸字符串 = block 并把字符串当原因（L249-L250），不是"日志/备注"。
4. 异步钩子在已有事件循环时会跑到**另一个线程的新事件循环**里（L230-L239），不能依赖 loop 局部状态。

## 高频符号中文短语表
| 符号 | 中文短语 |
|---|---|
| `HookContext` | 钩子上下文（phase+payload+trace 标识） |
| `HookDecision` | 钩子决策（续/替换/拦截） |
| `HookManager` | 有序执行并隔离失败的调度器 |
| `PolicyHook` | 带 fail-closed 与超时的策略钩子 |
| `HOOK_REPLACE` | 改写后续 payload |
| `HOOK_BLOCK` | 拦截当前操作 |
| `_normalize` | 任意返回值归一为决策 |
| `_invoke_hook` | 带超时的钩子调用 |

---

# guardrails.py（LightAgent/guardrails.py）

## 模块概览
轻量护栏原语：`GuardrailManager` 按输入/工具/输出三个检查点顺序执行护栏函数链，任一拒绝即拦截，允许时可改写值；另附四个内置护栏工厂（隐私输入、敏感工具确认、高风险参数、输出脱敏）。与 hooks（生命周期中间件）和 review（人工审批）互补。

## 类与符号清单
- `GuardrailDecision` (L15-L21)：frozen，`allowed/reason/value`；value 非空表示"改写后的值"。
- `GuardrailManager` (L24-L85)：持有 input/tool/output 三条护栏链并执行。
- `DEFAULT_PRIVACY_PATTERNS` (L88-L93)：4 个内置正则——美国 SSN、13-19 位卡号、email、`api_key/secret/password/token = …` 赋值。
- `privacy_input_guardrail` (L96-L110)：输入护栏工厂，命中即 block。
- `sensitive_tool_confirmation_guardrail` (L113-L127)：工具护栏工厂，名单内工具未批准即 block。
- `high_risk_parameter_guardrail` (L130-L147)：工具护栏工厂，按参数校验（callable 断言或允许列表）。
- `output_redaction_guardrail` (L150-L164)：输出护栏工厂，命中替换为 `[redacted]`，**永远 allowed**。

## 关键方法
- `check_input` (L38) — 对 query 跑输入链；调用方：core.py:598（run 入口，命中记 trace `guardrail_block` core.py:611）。
- `check_tool` (L41) — payload 打包为 `{"tool_name", "arguments"}` 后跑工具链；调用方：core.py:1209（工具执行前，trace L1233）。
- `check_output` (L50) — 对最终输出跑输出链；调用方：core.py:1330（`after_model_response` 钩子之后，trace L1342）。
- `_run_guardrails` (L53) — 链式执行：每级收到 `current_value`，allowed 且 value 非 None 则更新 current_value（L65-L66），实现"改写传递"；首个拒绝短路返回。
- `_coerce_decision` (L69) — 返回值归一：GuardrailDecision 原样；None/True→allow；False→block（通用文案）；str→block(reason=str)；dict→显式字段；**其他任意对象→allow 且 value=该对象**（L85）。
- `privacy_input_guardrail` (L96) — 编译正则后返回闭包 guardrail(value, context)。
- `high_risk_parameter_guardrail` (L130) — rules: 参数名 → 断言函数或白名单序列；失败 reason 附参数名（L142/L144）。

## 关键机制细节
### 三个检查点与拦截行为
| 检查点 | 输入形态 | 拦截后行为 |
|---|---|---|
| input（core.py:598） | str query | 直接返回 LA-GUARDRAIL 错误文本（core.py:1206），记 `guardrail_block` trace |
| tool（core.py:1209） | dict `{"tool_name","arguments"}` | 工具不执行，返回 LA-GUARDRAIL |
| output（core.py:1330） | str 输出 | 返回 LA-GUARDRAIL（脱敏类护栏则改写后放行） |

- 护栏签名统一为 `guardrail(value, context) -> GuardrailDecision|None|bool|str|dict|Any`。
- 改写（redaction）与拦截的区别：`output_redaction_guardrail` 返回 allowed=True + value=替换文本，链路继续用改写值；core.py:1346 因此记 `replace` 适配器事件。
- `sensitive_tool_confirmation_guardrail` 的 `approved` 是工厂调用时固定的布尔闭包变量（L119），不能运行期翻转为 True。

## 与其他模块的关系
| 本模块符号:行号 | 对方模块.符号 | 说明 |
|---|---|---|
| `GuardrailManager`:24 | core.py:42（import）、221 | 构造时传入 input/tool/output 护栏列表 |
| `check_input/check_tool/check_output`:38/41/50 | core.py:598/1209/1330 | 三检查点 |
| `GuardrailDecision`:15 | errors.py `LA-GUARDRAIL`（errors.py:101） | 拒绝后由 core 格式化为错误文本 |
| 内置护栏工厂 :96/113/130/150 | `__init__.py:49-57` | 公共 API 导出 |

## 阅读陷阱
1. 工具护栏收到的是**打包 dict** `{"tool_name","arguments"}`（L47），不是裸参数；`high_risk_parameter_guardrail` 内部自己取 `arguments`。
2. `_coerce_decision` 对未知返回对象会**放行并把对象当新值**（L85），护栏返回值类型错可能悄悄改写 query。
3. 输出脱敏护栏永远 allowed，靠 value 改写而非拦截；不要期待它 block。
4. 敏感工具确认护栏是"静态布尔审批"，真正的动态人工审批走 review.py 的 `HumanApprovalHook`。

## 高频符号中文短语表
| 符号 | 中文短语 |
|---|---|
| `GuardrailDecision` | 护栏决策（允许/拒绝/改写值） |
| `GuardrailManager` | 输入/工具/输出三检查点执行器 |
| `DEFAULT_PRIVACY_PATTERNS` | 四类隐私默认正则 |
| `privacy_input_guardrail` | 隐私输入拦截护栏 |
| `sensitive_tool_confirmation_guardrail` | 敏感工具需确认护栏 |
| `high_risk_parameter_guardrail` | 高风险参数校验护栏 |
| `output_redaction_guardrail` | 输出敏感信息脱敏护栏 |
| `_coerce_decision` | 护栏返回值归一 |

---

# review.py（LightAgent/review.py）

## 模块概览
人工审批与反馈原语：可序列化的 `ApprovalRequest`/`ApprovalDecision`（五态：pending/approve/reject/edit/respond）、附着到 trace 的 `HumanFeedback`、两个存储（内存 + 原子写 JSON），以及 fail-closed 的 `HumanApprovalHook`——把"选中的工具调用/移交"先拦截、存为 pending 请求，等人工决策后凭 approval_id 复用放行。

## 类与符号清单
- 常量 `APPROVAL_*` (L19-L30)：五种决策动作 + 合法集合。
- `ApprovalRequest` (L37-L62)：审批请求——action、request_id、run/trace id、tool_name、arguments、source/target_agent、allowed_decisions（默认 approve/reject/edit）等。
- `ApprovalDecision` (L65-L107)：审批决策；`__post_init__` 校验 action 合法（L78-L80）；`approved` 属性 = approve/edit/respond 之一（L82-L84）；五个 classmethod 构造器（approve L86、reject L90、edit L94、respond L98、pending L102）。
- `HumanFeedback` (L110-L124)：人工标注——trace_id、rating、label、comment、reviewer_id。
- `InMemoryReviewStore` (L127-L178)：requests/decisions/feedback 三张内存表。
- `JsonReviewStore` (L181-L232)：继承前者，增删即落盘（tmp + replace 原子写，L227-L232）。
- `HumanApprovalHook` (L235-L442)：fail-closed 审批钩子（可作 HookManager 成员直接使用）。

## 关键方法
- `HumanApprovalHook.__call__` (L263) — 主逻辑：phase 不在白名单或工具不在名单 → None（不表态，L264-L269）；payload 带 `approval_id` → 查历史决策复用（匹配 L275-L276 放行；不匹配或未找到/未决 → block，L277-L303）；否则 `_build_request` 存库：无 reviewer → pending 并 block（L305-L312）；有 reviewer → 调用并归一（reviewer 异常 → reject，L317-L321），resolve 后返回决策。调用方：经 HookManager.run（hooks.py:101）→ core.py:941 `_run_hooks`。
- `_call_reviewer` (L325) — 可选超时的 reviewer 调用（单线程 executor，超时抛 TimeoutError）。
- `_normalize_decision` (L338) — reviewer 返回值归一：ApprovalDecision 原样；True/None→approve；False→reject；str→reject(reason)；dict→action 或 approved/allowed 字段。
- `_build_request` (L364) — 从 HookContext 组装请求；`on_handoff` 阶段把 payload.query 并入 arguments（L367-L368）。
- `_matches` (L386) — 复用 approval_id 时校验当前动作与原请求一致（phase/tool/arguments/agents/user_id，L387-L399）。
- `_hook_decision` (L401) — ApprovalDecision → HookDecision：approve→continue；edit→replace(payload)（before_tool_call 换 arguments，L432-L435）；respond→block(response)；pending/reject→block(reason)；metadata 携带 `approval_request_id` + `review_events`。
- `InMemoryReviewStore.resolve` (L145) — 记录决策，未注册的 request_id 抛 KeyError（L147）。
- `JsonReviewStore._save` (L220) — `*.tmp` 写后 `replace` 原子替换（L227-L232）。

## 关键机制细节
### 审批状态机
- 无 reviewer（异步人工）：`__call__` 存请求 → decision=pending → HookDecision.block → 工具/移交被拦截；trace 出现 `approval_required` 事件（`_hook_decision` L408-L411 决定事件名）。人工决策后 `store.resolve(request_id, decision)`，重跑同一动作时在 hook metadata 传 `approval_id=request_id` 复用放行。
- 决策语义映射（L428-L442）：approve→continue；edit→replace（参数替换）；respond→block 且 reason=人工答复文本；reject/pending→block。
- 复用防伪：approval_id 对应请求与当前动作不匹配 → block"approval does not match"（L277-L290），防止拿 A 决策放行 B 动作。
- fail-closed：reviewer 抛异常也按 reject 处理（L317-L321），绝不让未审批动作通过。

### review_events 与 trace
`_hook_decision` 与 `__call__` 的 block 分支都在 metadata 放 `review_events`（type ∈ approval_required/approve/reject/edit/respond）；core.py:963-L968 把它们逐条转成 `approval_*` trace 事件，并计入 TraceSummary.review_counts（tracing.py:183-L184）。

## 与其他模块的关系
| 本模块符号:行号 | 对方模块.符号 | 说明 |
|---|---|---|
| `HookContext/HookDecision`（review.py:16 import） | hooks.py:26/43 | 钩子协议依赖 |
| `HumanApprovalHook`:235 | core.py `hooks=[...]`、phases 默认 `{"before_tool_call","on_handoff"}`（L256-L260） | 挂到主循环钩子链 |
| `HumanFeedback`:110 | tracing.py:TraceRecorder.record_feedback:261 | 可 `to_dict()` 附着到 trace |
| `InMemoryReviewStore`:127 | `__init__.py:41-48` | 公共 API 导出 |

## 阅读陷阱
1. `pending` 也是 block：钩子返回 block 后 run 结束/工具不执行，需要**重跑同一动作**并携带 `approval_id`，而不是"等待中"。
2. `ApprovalDecision.approved` 为 True 的集合包含 `respond`（L84），但 respond 走到 `_hook_decision` 是 **block**（以人工答复替代动作）——"批准"与"放行原动作"不同。
3. `JsonReviewStore` 的 `list_pending`/`get_decision` 无磁盘写，只有 create/resolve/add_feedback 触发 `_save`。
4. 复用 approval_id 时若 arguments 有任何差异（哪怕空格）都会命中 `_matches` 失败而 block（L387-L399）。

## 高频符号中文短语表
| 符号 | 中文短语 |
|---|---|
| `ApprovalRequest` | 可序列化审批请求 |
| `ApprovalDecision` | 五态审批决策 |
| `HumanFeedback` | 附着 trace 的人工标注 |
| `InMemoryReviewStore` | 内存审批存储 |
| `JsonReviewStore` | 原子落盘审批存储 |
| `HumanApprovalHook` | fail-closed 人工审批钩子 |
| `APPROVAL_PENDING` | 待决（拦截并登记） |
| `APPROVAL_EDIT` | 人工改参后放行 |
| `resolve` | 登记决策（使请求不再 pending） |

---

# tracing.py（LightAgent/tracing.py）

## 模块概览
无后端依赖的观测追踪原语：`TraceEvent`（机器可读事件）、`TraceRecorder`（显式启用时采集）、`TraceSummary`（从事件流聚合的指标）、`normalize_usage`（OpenAI 兼容 usage 归一）、`summarize_trace`（事件列表 → 汇总）、`export_trace` + `JsonlTraceExporter`（导出契约与 JSONL 落盘）。是评测（evaluation）与 run 收尾指标的共同底座。

## 类与符号清单
- `TraceEvent` (L17-L39)：type + data + trace_id/parent_trace_id/run_group_id + UTC 时间戳；`to_dict` 有条件输出 parent/run_group 字段（L35-L38）。
- `TraceSummary` (L42-L82)：事件数、模型请求数/延迟、工具调用/成功/延迟、retry/error 计数与分类、review_counts、usage、estimated_cost_usd；`tool_success_rate` 属性（L60-L64）。
- `TraceExporter` (L85-L94)：Protocol——`export(events, summary, metadata)`。
- `JsonlTraceExporter` (L97-L119)：整段 envelope（exported_at/metadata/summary/events）追加写 JSONL。
- `normalize_usage` (L122-L149)：usage 对象/dict → prompt/completion/total 三键。
- `summarize_trace` (L152-L208)：按事件类型聚合的核心统计函数。
- `export_trace` (L211-L226)：兼容"有 export() 方法的对象"与"裸可调用对象"两种 exporter。
- `TraceRecorder` (L229-L293)：enabled 开关 + trace 标识 + 事件缓冲。

## 关键方法
- `TraceRecorder.record` (L245) — 未启用返回 None（L246-L247），启用则构建 TraceEvent 入列表；调用方：core.py:936-938（`_record_trace`，定义于 core.py:910）。
- `TraceRecorder.to_list` (L258) — 事件转 dict 列表；调用方：core.py:1158（export_trace 方法）、1167（summarize_trace 方法）、evaluation.py:129（result.trace 即它）。
- `TraceRecorder.record_feedback` (L261) — 人工标注转 `human_feedback` 事件。
- `TraceRecorder.summarize/export` (L271/L279) — 便捷聚合与导出。
- `summarize_trace` (L152) — 识别的事件类型：`model_request`（计数+延迟+usage，L165-L170）、`tool_call`（L171-L172）、`tool_result`（无 error 记成功，L173-L176）、`error`（按 category/stage 分类，含 "retry" 则 retry_count+1，L177-L182）、`approval_*`/`human_feedback`（review_counts，L183-L184）、`run_end`（duration_ms、retry_count 上限，L185-L188）；显式 usage 参数优先于事件聚合（L196）；pricing 可估成本（L198-L207）。调用方：core.py:1165-1168、evaluation.py:131。
- `normalize_usage` (L122) — 支持 pydantic `model_dump`（L126-L127）、属性访问兜底（L129-L139）、input_tokens/output_tokens 别名（L140-L141）；调用方：core.py:1047/1118/1145、tracing.py:168/196。
- `export_trace` (L211) — 统一导出入口；调用方：core.py:1173 `export_trace_to` 及 TraceRecorder.export。
- `JsonlTraceExporter.export` (L103) — 追加一行 JSON envelope，返回文件路径。

## 关键机制细节
### 事件类型与落点
- core.py 实际产出的事件 type（`_record_trace` 调用点实测）：`run_start`(573)、`run_end`(1050)、`model_request`(1088)、`model_response`(2075/2223)、`tool_call`(1941/2252)、`tool_result`(2054/2315/2337)、`error`(731/1955/1978/2101/2108 等)、`guardrail_block`(611/1233/1342)、`hook_decision`(965/993)、`hook_block`(971)、`memory_write`(1643/1812)、`memory_retrieve_block`(1503/1524)、`memory_write_block`(1567)、`memory_retrieve_filter`(1889)、`memory_promotion_*`(417/1693/1707/1757/1784)。
- 消费落点：`TraceRecorder.events`（内存）→ `to_list` → 用户侧 `export_trace_to`(core.py:1173) / `JsonlTraceExporter` / `summarize_trace`；`RunResult.trace` 与 Session 事件存储是另一条持久化路径。
- trace 开关：core.py:328 先建 `TraceRecorder(enabled=False)`，run(trace=True) 时在 core.py:540 重建启用。

## 与其他模块的关系
| 本模块符号:行号 | 对方模块.符号 | 说明 |
|---|---|---|
| `TraceRecorder`:229 | core.py:40（import）、328/540、910 | `_record_trace` 的承载者 |
| `summarize_trace`:152 | core.py:1165 / evaluation.py:12,131 | run 汇总与评测指标 |
| `normalize_usage`:122 | core.py:1047/1118/1145 | usage 归一 |
| `TraceSummary.review_counts` | review.py `review_events`（L413-L427） | approval_* 事件计入 |
| `JsonlTraceExporter`:97 | `__init__.py:29-38` | 公共 API 导出 |

## 阅读陷阱
1. `record` 未启用时返回 None，调用方必须判空（core.py:938 正确处理）；直接链式使用会 AttributeError。
2. `TraceSummary.retry_count` 依赖 error 事件 category **字符串含 "retry"**（L181-L182），或 run_end 事件的 retry_count 字段（L188），否则恒 0。
3. `tool_success_count` 被钳制不超过 `tool_call_count`（L192-L195），且依赖 tool_result 事件带 error 字段判失败。
4. usage 优先级：显式传入的 usage 覆盖事件聚合 usage（L196），两者可能不一致。

## 高频符号中文短语表
| 符号 | 中文短语 |
|---|---|
| `TraceEvent` | 追踪事件（type+data+trace 标识） |
| `TraceRecorder` | 显式启用的事件采集器 |
| `TraceSummary` | 聚合运行指标 |
| `summarize_trace` | 事件流聚合统计 |
| `normalize_usage` | usage 三键归一 |
| `export_trace` | 轨迹导出统一入口 |
| `JsonlTraceExporter` | JSONL 审计文件导出 |
| `TraceExporter` | 导出器最小协议 |
| `record_feedback` | 人工标注入轨迹 |

---

# evaluation.py（LightAgent/evaluation.py）

## 模块概览
零依赖的确定性回归评测：`LightEvaluator` 对任何带兼容 `run()` 的对象（LightAgent 实例或 LightFlow）跑固定用例集，逐例做成功性、输出包含、工具调用白/黑名单、trace 事件存在性、时延上限、重试恢复与自定义 check 断言，产出 `EvaluationReport`（通过率、平均时延、估算成本）。

## 类与符号清单
- `EvaluationCheck` (L15)：自定义断言函数类型 `(result, trace) -> Any`。
- `EvaluationCase` (L18-L33)：用例——query、expected_output_contains、expected_tools、forbidden_tools、expected_trace_events、expect_success、max_latency_ms、require_recovery、checks、run_kwargs、metadata。
- `EvaluationCaseResult` (L36-L60)：单例结果——passed、failures 列表、duration_ms、trace、summary。
- `EvaluationReport` (L63-L100)：结果列表 + total/passed/failed/pass_rate 属性（L69-L83）+ 聚合 to_dict（L85-L100）。
- `LightEvaluator` (L103-L190)：评测执行器，可传 pricing 估成本。

## 关键方法
- `LightEvaluator.run` (L109) — 目标必须有 `run()`（否则 TypeError，L110-L111），逐例调 `_run_case`；调用方：用户代码（框架内部无调用点，纯用户侧工具）。
- `_run_case` (L114) — 执行单例：
  - 注入默认 kwargs：`result_format="object"`、`trace=True`（L115-L117），保证拿到 RunResult + trace。
  - 计时并捕获异常（L118-L124）；取 content/error/trace/usage（L127-L130）；`summarize_trace` 算 summary，缺 duration 时用实测值（L131-L133）。
  - 断言序列：success 期望（L136-L138）→ 输出包含（L140-L142）→ 期望工具调用（从 `tool_call` 事件的 data.name 提取，L144-L155）→ 期望 trace 事件（L156-L158）→ 时延上限（L160-L163）→ `require_recovery` 要求成功且 retry_count>0（L164-L165）→ 自定义 checks：False/非空 str/(False, msg) 元组均记失败，check 抛异常也记失败（L167-L178）。

## 关键机制细节
- 通过判定：`failures` 为空即 passed（L182）。
- 自定义 check 返回约定：True/None 通过；False → "custom check returned False"；字符串 → 失败原因；`(bool, message)` 元组按首元素判定（L167-L178）。
- 成本估算依赖 `evaluation.py:12` 从 tracing 导入的 `summarize_trace` 与 pricing 参数（input/output_per_million）。

## 与其他模块的关系
| 本模块符号:行号 | 对方模块.符号 | 说明 |
|---|---|---|
| `LightEvaluator`:103 | core.py:LightAgent.run:498 | 评测目标（要求 result_format/trace 兼容） |
| `summarize_trace`（:12 import） | tracing.py:152 | 单例指标 |
| `EvaluationCaseResult.summary` | tracing.py:TraceSummary:42 | 复用观测指标结构 |
| 全模块 | `__init__.py:39` | 公共 API 导出 |

## 阅读陷阱
1. 评测目标是鸭子类型：任何有 `run()` 的对象都行，但返回 str 时 content 取 `getattr(result, "content", result)`（L127），error/trace/usage 全靠 RunResult 才有。
2. `expected_tools` 匹配的是 trace `tool_call` 事件的 `data.name` 字段，不是工具调用 JSON 里的其他键。
3. `require_recovery` 语义是"成功且至少重试一次"，不是"失败后恢复"。
4. 用例是顺序同步执行的，无并发与随机性——天然可复现，但慢用例会拖长整套评测。

## 高频符号中文短语表
| 符号 | 中文短语 |
|---|---|
| `EvaluationCase` | 确定性回归用例声明 |
| `EvaluationCaseResult` | 单用例结果与失败明细 |
| `EvaluationReport` | 通过率/时延/成本汇总 |
| `LightEvaluator` | 无依赖回归评测器 |
| `_run_case` | 断言链执行单用例 |
| `EvaluationCheck` | 自定义断言函数类型 |

---

# capabilities.py（LightAgent/capabilities.py）

## 模块概览
v0.10 能力系统的核心：统一的能力声明（`CapabilitySpec`，带风险级与标志位）、Provider 生命周期协议与基类、只能收窄的权限集（`PermissionSet`）、fail-closed 策略引擎（`PolicyEngine`）、按作用域解析 Provider 并在策略通过后执行能力的注册表（`CapabilityRegistry`），以及把旧 ToolRegistry/记忆后端适配进能力体系的两个 Adapter。

## 类与符号清单
- `CapabilityScope` (L16-L20)：DEFAULT/RUNTIME/SESSION/AGENT 四级作用域。
- `CapabilityRisk` (L23-L27)：L0 READ_ONLY / L1 ISOLATED_WRITE / L2 SENSITIVE / L3 DESTRUCTIVE。
- `CapabilitySpec` (L30-L60)：frozen 能力规格——name、read/write/network/execute/persistent/cancellable/resumable、timeout、output_limit、requires_sandbox、requires_approval；`__post_init__` 校验（L49-L55）。
- `ProviderHealth` (L63-L72)：健康状态（healthy/status/message/degraded_capabilities）。
- `RuntimeContext` (L75-L84)：runtime/session/agent/user/turn/run id + `permissions: PermissionSet`。
- `CapabilityProvider` (L87-L108)：Protocol——mount/start/health/reload/stop/unmount。
- 16 个标记 Protocol（L111-L172）：Model/Tool/FileSystem/Shell/Terminal/Browser/Web/LSP/Memory/RAG/Subagent/Workflow/Interaction/Sandbox/Credential/TelemetryProvider，全部为空子类，仅作类型标注。
- `BaseCapabilityProvider` (L175-L210)：Python 原生 Provider 的参考生命周期实现（start 前必须 mount，L192-L194）。
- `PermissionSet` (L213-L258)：allowed/denied/max_risk；`allows` (L221) 与 `narrow` (L234)。
- `PolicyRequest` (L261-L266) / `PolicyDecision` (L269-L287)：策略输入与输出（allow/block/approval 三构造器）。
- `PolicyCallable` (L290)：策略函数类型。
- `PolicyEngine` (L293-L359)：有序 fail-closed 策略评估。
- `ProviderRegistration` (L362-L367)：注册记录（provider/scope/owner_id/order）。
- `CapabilityRegistry` (L370-L575)：注册、解析、生命周期、审计、策略执行。
- `ToolProviderAdapter` (L578-L600) / `MemoryProviderAdapter` (L603-L627)：旧组件适配。
- `_run_sync` (L630-L650)：同步环境运行协程的工具函数。

## 关键方法
- `PermissionSet.allows` (L221) — denied 优先 → allowed 白名单（非空时必须包含）→ 风险级不超过 max_risk（L221-L232）。调用方：PolicyEngine.evaluate（capabilities.py:305）。
- `PermissionSet.narrow` (L234) — 派生更窄权限；试图新增能力或提高 max_risk 抛 ValueError（L242-L253）。
- `PolicyEngine.evaluate` (L303) — 三段：① context.permissions 快照检查（L304-L306）；② spec.requires_approval 直接返回 approval 决策（L307-L308）；③ 按序跑策略函数（参数深拷贝隔离，L310-L319），策略异常时 fail_closed 则 block（L323-L327），allowed=False 短路，arguments 可被策略改写传递（L334-L335）。调用方：CapabilityRegistry.invoke:510。
- `PolicyEngine.evaluate_sync` (L338) — `_run_sync` 包装；调用方：core.py:1272（工具的策略检查）。
- `PolicyEngine._coerce` (L341) — 策略返回值归一：None/True→allow，False→block，dict 支持 requires_approval/allowed/reason/arguments（L341-L359）。
- `CapabilityRegistry.register` (L392) — SESSION/AGENT 作用域必须给 owner_id（L400-L401）；同 name+scope+owner 重复注册抛 ValueError（L402-L408）；能力重叠时记录冲突（后注册者胜，L410-L420）。调用方：core.py:887/889。
- `CapabilityRegistry.resolve` (L454) — 按 capability 名在 `_matching`（L535：DEFAULT/RUNTIME 恒可见，SESSION 按 session_id、AGENT 按 agent_id 匹配）中找，按 `(scope优先级, 注册顺序)` 降序取第一个（L462-L463）；无匹配抛 LookupError。调用方：CapabilityRegistry.invoke:508。
- `CapabilityRegistry.invoke` (L500) — 完整执行管线：resolve → `policy_engine.evaluate`（L510-L515）→ 审计 `policy.decision`（L516-L521）→ 拒绝抛 PermissionError（L522-L524）→ 调 `provider.invoke(capability, **arguments)`，协程按 spec.timeout 用 `asyncio.wait_for`（L530），输出按 output_limit 截断（L531-L532）。调用方：core.py:846（arun 的异步 Provider 路径）。
- `CapabilityRegistry.mount/stop` (L427/L494) — 按匹配序 mount+start / stop+unmount 并审计。
- `CapabilityRegistry._configuration_digest` (L567) — 配置中 key/token/secret/password 字段替换为 `[redacted]` 后 sha256（L568-L575）。
- `ToolProviderAdapter.invoke` (L595) — `tool.<name>` → 每次调用新建 `AsyncToolDispatcher` 分发（L597-L600）。
- `_run_sync` (L630) — 无事件循环直接 `asyncio.run`；有则起 daemon 线程跑（L636-L650）。

## 关键机制细节
### 注册与生效机制
1. **声明**：Provider 构造时给 `CapabilitySpec` 列表（如 SqliteFTSRetrievalProvider 的 6 个 rag.* 规格，knowledge.py:94-L101）。
2. **注册**：`registry.register(provider, scope=..., owner_id=...)`；core.py:329 建默认注册表（可注入 policy_engine），core.py:887/889 自动把 ToolRegistry 和 memory 后端以 RUNTIME 作用域注册为 Adapter。
3. **挂载**：`mount(context)` 逐个 provider.mount + start，审计 `provider.started`。
4. **解析**：`resolve(capability, context)` 按 AGENT > SESSION > RUNTIME > DEFAULT 优先级（`_precedence` L373-L378，降序排序 L462）。
5. **执行**：`invoke` 前置策略评估（权限快照 → requires_approval → 策略链），拒绝抛 PermissionError；通过后按 spec.timeout/output_limit 执行。
6. **审计**：`_audit`（L546）输出 provider/scope/owner/配置摘要等结构化事件，core.py 将其写入 session 事件（`policy.decision`，core.py:1265-1284 一带）。

### 风险级与审批
- L0-L3 四级风险（L23-L27）参与 PermissionSet 检查；`requires_sandbox` 在 core.py:1262 单独检查（无沙箱 Provider → LA-SANDBOX，core.py:1271）；`requires_approval` 在 PolicyEngine 短路返回 approval 决策（L307-L308）。

## 与其他模块的关系
| 本模块符号:行号 | 对方模块.符号 | 说明 |
|---|---|---|
| `CapabilityRegistry/PolicyEngine/CapabilitySpec/PolicyRequest` | core.py:47-54（import）、329、1254、1272 | 主循环能力化路径 |
| `CapabilityRegistry`:370 | runtime.py:13、721-729 | AgentRuntime 持有注册表与 RuntimeContext |
| `ToolProviderAdapter`:578 | tools.py:AsyncToolDispatcher:281 | 适配旧工具分发 |
| `MemoryProviderAdapter`:603 | 记忆后端 retrieve/store | 记忆能力化 |
| `BaseCapabilityProvider`:175 | knowledge.py:14-19（import） | 检索 Provider 的基类 |
| `PermissionSet`:213 | RuntimeContext.permissions:83 | 运行期权限快照 |
| 拒绝 PermissionError:524 | core.py:1286-1289 → errors.py `LA-POLICY`（errors.py:111） | 拒绝信息格式化 |

## 阅读陷阱
1. 能力冲突解析是"同作用域内后注册者胜"（L419），且冲突只记录到 `conflicts()` 不报错。
2. `invoke` 拒绝抛的是**裸 PermissionError**，不带 LA- 码；LA-POLICY 文本由 core.py 后续格式化——捕获异常时要按 PermissionError 处理。
3. `evaluate_sync` 在已有事件循环里会**起线程跑新 loop**（L636-L650），不是"当前 loop 内同步执行"。
4. 16 个 `XxxProvider` Protocol 都是空标记（L111-L172），真正可复用的实现只有 `BaseCapabilityProvider` 和两个 Adapter。

## 高频符号中文短语表
| 符号 | 中文短语 |
|---|---|
| `CapabilityScope` | 四级能力作用域 |
| `CapabilityRisk` | L0-L3 风险等级 |
| `CapabilitySpec` | 能力规格声明 |
| `CapabilityRegistry` | Provider 注册与能力执行 |
| `PolicyEngine` | fail-closed 策略引擎 |
| `PolicyDecision` | 允许/拒绝/需审批决策 |
| `PermissionSet` | 只能收窄的权限快照 |
| `BaseCapabilityProvider` | Provider 生命周期基类 |
| `ToolProviderAdapter` | 旧工具注册表适配器 |
| `MemoryProviderAdapter` | 记忆后端适配器 |
| `RuntimeContext` | 运行期上下文与权限 |
| `ProviderHealth` | Provider 健康状态 |
| `resolve` | 按能力名解析 Provider |
| `invoke` | 策略检查后的能力执行 |

---

# knowledge.py（LightAgent/knowledge.py）

## 模块概览
"知识/检索" Provider 集合：零依赖的 SQLite FTS5 RAG（`SqliteFTSRetrievalProvider`，分块 + bm25 排序 + LIKE 降级）、跨 Session 字面搜索（`SessionSearchProvider`），以及把 SkillManager、MCPClientManager、LightFlow 适配成能力 Provider 的三个 Adapter。所有 Provider 均继承 capabilities 的 `BaseCapabilityProvider`，以 CapabilitySpec 声明能力。

## 类与符号清单
- `RetrievalDocument` (L23-L36)：入库文档——content/title/source/document_id/scope/owner_id/tenant_id/created_at/metadata。
- `RetrievalResult` (L39-L55)：检索结果——chunk 级内容 + citation_id + score + 元数据。
- `RetrievalProvider` (L58-L75)：Protocol——ingest/remove/list_documents/search/read_chunk/reindex。
- `SqliteFTSRetrievalProvider` (L78-L299)：SQLite FTS5 检索实现（name="sqlite-fts5-rag"）。
- `SessionSearchProvider` (L302-L338)：Session 事件字面搜索（name="session-search"）。
- `SkillProviderAdapter` (L341-L367)：skill.list/activate/read_reference/execute_script 四能力。
- `MCPProviderAdapter` (L370-L390)：每个 MCP 工具一个 `mcp.<tool>` 能力。
- `WorkflowProviderAdapter` (L393-L424)：workflow.start/status/resume/rerun_step 四能力。
- `_call_in_thread` (L427-L431)：线程里跑同步方法并兼容其返回协程。

## 关键方法
- `SqliteFTSRetrievalProvider.__init__` (L84) — 校验 chunk_size≥100、0≤overlap<chunk_size（L85-L88）；建父目录；注册 6 个 CapabilitySpec（rag.ingest=L1、rag.remove=L3 DESTRUCTIVE、rag.search 读、rag.reindex=L2 SENSITIVE 等，L94-L101）；`_initialize`。
- `_initialize` (L109) — 建三张表：`rag_documents(document_id, payload)`、`rag_chunks(chunk_id, document_id FK 级联, position, content)`、虚拟表 `rag_chunks_fts USING fts5(chunk_id UNINDEXED, content)`（L111-L133）；FTS5 不可用时 `_fts5=False` 降级。
- `health` (L137) — FTS5 缺失时报 degraded，`degraded_capabilities=["rag.search"]`（L137-L143）。
- `ingest` (L145) — 分块后整体重写：INSERT OR REPLACE 文档 → 删旧 chunk（含 FTS 表）→ 重插（chunk_id=`"<doc_id>:<position>"`，L164）。
- `search` (L194) — 检索主流程：空 query 返回 []；FTS5 路径 `MATCH` + `bm25(rag_chunks_fts)` 升序（L209-L220）；降级路径 `lower(content) LIKE %q%`（L222-L232）；均超取 `limit*10` 后在 Python 侧按 scope/owner_id/tenant_id 过滤，凑满 limit 截断（L234-L244）。
- `read_chunk` (L247) — 按 chunk_id 读单块（引用依据）。
- `reindex` (L261) — 清空 FTS 表并从 rag_chunks 全量重建（L261-L270）。
- `invoke` (L272) — `rag.<方法名>` → 反射调用同名方法（L272-L275）。
- `_chunks` (L277) — 滑窗分块，步长 `chunk_size - chunk_overlap`（L280-L281）；空内容返回 `[""]`。
- `_result` (L283) — 组装 RetrievalResult：`citation_id=f"rag:{chunk_id}"`（L290），`score = -bm25 rank`（bm25 越小越相关，L294）。
- `SessionSearchProvider.search` (L312) — casefold 子串匹配 SessionStore 事件的 JSON 序列化文本（L317-L330），citation=`"session:<sid>:<seq>"`（L327）。
- `WorkflowProviderAdapter.invoke` (L406) — start 优先走 `arun`，同步 `run/resume/rerun_step` 经 `_call_in_thread`（L407-L424）。

## 关键机制细节
### FTS5 建表与检索流程
1. 建表：`rag_documents`（整文档 JSON payload）+ `rag_chunks`（分块正文，FK 级联）+ FTS5 虚拟表（chunk_id UNINDEXED + content）（L111-L133）。
2. 写入：`ingest` 分块（滑窗 overlap）→ 双写 rag_chunks 与 rag_chunks_fts（L163-L173）；重入库先删旧 FTS 行与 chunk 行（L157-L162）。
3. 检索：`MATCH` 命中 → JOIN rag_chunks/rag_documents → `ORDER BY bm25` → LIMIT（超取 10 倍）→ scope/owner/tenant 后过滤 → `score=-rank`。
4. 降级：编译环境无 FTS5 → `_fts5=False`，search 走 LIKE，health 报 degraded。
5. 引用：检索结果自带 `citation_id`（`rag:` 或 `session:` 前缀），供上层引用追溯。

### 适配器与能力声明
- SkillProviderAdapter 的 `skill.execute_script` 是全库唯一同时带 `requires_sandbox=True, requires_approval=True` 的能力（L351-L357）。
- MCPProviderAdapter 按工具名单逐个生成 SENSITIVE+network+execute 规格（L377-L386），能力名即 `mcp.<tool_name>`。

## 与其他模块的关系
| 本模块符号:行号 | 对方模块.符号 | 说明 |
|---|---|---|
| `BaseCapabilityProvider/CapabilitySpec/CapabilityRisk/ProviderHealth`（:14-19 import） | capabilities.py:175/30/23/63 | 能力体系基座 |
| `SessionStore/_utc_now`（:20 import） | session.py:377 | SessionSearchProvider 的存储来源 |
| `SkillProviderAdapter`:341 | skills.py:SkillManager:34 | 技能能力化 |
| `MCPProviderAdapter`:370 | mcp_client_manager.py:MCPClientManager:26 的 call_tool | MCP 工具能力化 |
| `WorkflowProviderAdapter`:393 | flow.py:LightFlow:132 | 工作流能力化 |
| 全模块 | `__init__.py:141-150` | 公共 API 导出 |

## 阅读陷阱
1. `search` 的 scope/owner/tenant 过滤发生在**超取 10 倍之后**（L234-L244）：若前 10×limit 条全被过滤，即使库里有更多匹配也返回不足 limit——不是 SQL 层精确分页。
2. 用户 query **原样**传给 FTS5 `MATCH`（L219），含引号等 FTS5 语法字符可能抛 sqlite3.OperationalError，无转义保护。
3. `score` 是 bm25 的相反数（L294），越大越相关，但只有 FTS5 路径有值，LIKE 路径为 None。
4. 模块名叫 knowledge，实际是"词法检索 Provider 集合"——无 embedding/向量检索；FTS5 对中文按 Unicode 分词效果有限，中文检索建议实测。

## 高频符号中文短语表
| 符号 | 中文短语 |
|---|---|
| `RetrievalDocument` | 入库检索文档 |
| `RetrievalResult` | 带引用的检索结果 |
| `RetrievalProvider` | 检索 Provider 协议 |
| `SqliteFTSRetrievalProvider` | SQLite FTS5 词法 RAG |
| `SessionSearchProvider` | 跨 Session 字面搜索 |
| `SkillProviderAdapter` | 技能系统能力适配 |
| `MCPProviderAdapter` | MCP 工具能力适配 |
| `WorkflowProviderAdapter` | LightFlow 能力适配 |
| `ingest` | 分块双写入库 |
| `search` | bm25/LIKE 检索 |
| `reindex` | FTS 表全量重建 |
| `_chunks` | 滑窗分块 |

---

# litellm_client.py（LightAgent/litellm_client.py）

## 模块概览
43 行的 openai 客户端替身：`LiteLLMClient` 用 `SimpleNamespace` 拼出 `client.chat.completions.create(**params)` 的调用形状，把请求转发给 `litellm.completion`，使 core.py 中所有 openai 风格调用车不经修改即可路由到 LiteLLM 支持的任意厂商。

## 类与符号清单
- `_LiteLLMCompletions` (L10-L30)：模拟 `client.chat.completions` 对象。
- `LiteLLMClient` (L33-L43)：模拟 `openai.OpenAI` 客户端外壳。

## 关键方法
- `_LiteLLMCompletions.create` (L24) — 封装点三部曲：`api_key` 原样注入（L25-L26）；`base_url` 映射为 LiteLLM 的 `api_base`（L27-L28）；`drop_params=True` 默认开启（L29，静默丢弃 LiteLLM 不支持的参数）；最终 `self._litellm.completion(**params)`（L30）。调用方：core.py:726、2096、2463（主循环/工具轮/流式模型调用）、2776/2788/2813（ToT 客户端）、2868/2993（辅助生成）。
- `__init__` 们（L11-L22、L36-L43）— 懒加载 litellm，缺失时提示 `pip install LightAgent[litellm]`（L18-L21）；litellm_module 参数便于测试注入。

## 关键机制细节
- core.py 的接入点：`_initialize_clients`（core.py:344）在 `provider == "litellm"` 时构造 `LiteLLMClient`（core.py:348-L356）；base_url 等于 OpenAI 默认值时不传（core.py:350-L351），tree_of_thought 另建 tot_client（core.py:353-L356）。
- 调用形状：`client.chat.completions.create(**self.chat_params)`（core.py:726 等 8 处），与 openai SDK 完全同形。
- 返回值为 litellm 的 ModelResponse，属性访问与 openai ChatCompletion 兼容，但类型不同。

## 与其他模块的关系
| 本模块符号:行号 | 对方模块.符号 | 说明 |
|---|---|---|
| `LiteLLMClient`:33 | core.py:348-356 | provider=="litellm" 时替换 self.client |
| `_LiteLLMCompletions.create`:24 | core.py:726/2096/2463/2776/2813/2868/2993 | 所有 chat.completions.create 调用点 |
| `__init__.py:33`（import 处） | `__init__.py` | 注意：LiteLLMClient **不在** `__all__`（用户直接 from LightAgent.litellm_client import） |

## 阅读陷阱
1. 只封装 `chat.completions.create` 一个入口——无 embeddings、无 Responses API、无流式专门处理（流式仍走同一 create，靠 params.stream）。
2. `drop_params=True` 会**静默丢弃**目标厂商不支持的参数（L29），排查参数不生效时先想到它。
3. `LiteLLMClient` 未列入包 `__all__`（`__init__.py:163-309` 无此名），但它仍从 `__init__.py:33` 之外的位置（core.py:348 懒导入）可用。
4. `api_key/base_url` 为 None 时不注入参数，交由 litellm 读环境变量等默认行为。

## 高频符号中文短语表
| 符号 | 中文短语 |
|---|---|
| `LiteLLMClient` | openai.OpenAI 形状的替身 |
| `_LiteLLMCompletions` | 模拟 chat.completions 对象 |
| `create` | 转发 litellm.completion 的封装点 |
