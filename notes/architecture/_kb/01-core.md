# core.py 源码知识库

> 源文件：`LightAgent/core.py`，共 3209 行（以工作树 2026-09-28 实际读取为准）。
> 行号均为 def/class 所在行的真实行号。

## 模块概览

core.py 是 LightAgent 框架的核心编排层：定义了单代理 `LightAgent`（负责一次 run 的完整生命周期——session 打开、hook/guardrail 检查、记忆注入、ToT 思维树、LLM 调用、工具循环、trace/session 事件记录、预算控制、agent 间任务转移）和多代理注册表 `LightSwarm`（按名字登记 agent 并作为 handoff 的寻址容器）。它把 tools/protocol/session/tracing/guardrails/hooks/capabilities/runtime 等子模块粘合进 `run()` 主流程，是绘制架构图的中心节点。

## 类与符号清单

- `run_async_safely` (L79-L112)：模块级函数，在同步入口里安全执行协程（已有事件循环时切到独立线程池跑 `asyncio.run`）。
- `LightAgent` (L116-L3170)：单代理类，run 生命周期 + 工具循环 + 记忆/安全/会话/观测的编排者。
- `LightSwarm` (L3173-L3203)：多代理注册表，`agents: Dict[str, LightAgent]`，提供注册与入口 run。
- `if __name__ == "__main__"` (L3206-L3209)：占位打印，无逻辑。

## LightAgent 类

职责：接收用户 query，组装 system prompt 与上下文（记忆/ToT/技能），循环调用 LLM 并执行工具调用直至产出最终回复；全程产生 Trace 事件与 Session 事件，受 hooks/guardrails/policy/budget 治理；支持流式与非流式两种执行路径，以及在 LightSwarm 内把任务移交给其他 agent。

构造参数表（`__init__` L119-L343）：

| 参数 | 默认值 | 作用 |
|---|---|---|
| name | None→`LightAgent{8位随机数}` (L210-212) | 代理名，也是 swarm 注册键与 handoff 目标名 |
| instructions | None→"You are a helpful agent." (L214-215) | 注入 system prompt 的代理指令 |
| role | None | 角色描述，注入 system prompt |
| model | 必填，空则 "gpt-4o-mini" (L203-204) | 主模型名 |
| api_key | None→env `OPENAI_API_KEY` (L205-206) | LLM API key，最终为 None 则抛 ValueError (L306-309) |
| base_url | None→env `OPENAI_BASE_URL`→`https://api.openai.com/v1` (L207-208, L313) | LLM 服务地址 |
| provider | None（仅允许 None/"litellm"，否则 ValueError L201-202） | "litellm" 时改用 LiteLLMClient (L347-352) |
| websocket_base_url | None | 仅保存 (L311)，当前主流程未使用 |
| memory | None | 外部 MemoryProtocol 记忆后端（mem0 等经此注入，core 不直接 import mem0/shared_memory） |
| memory_policy / memory_namespace | None | 记忆安全策略；namespace 快捷生成默认 MemoryPolicy (L220) |
| tree_of_thought | False | 启用 ToT 思维树前置规划 (L315-322) |
| tot_model / tot_api_key / tot_base_url | None→主 api_key/base_url；tot_model 默认 "deepseek-r1" (L316-322) | ToT 专用模型 |
| filter_tools | True | ToT 第三轮按 JSON 结果过滤工具 (L2818-2831) |
| self_learning | False | 额外检索/写入 agent 自身记忆 (L1462-1481) |
| tools | None | 初始工具列表（字符串名或带 tool_info 的函数），经 `load_tools` (L264-266) |
| enable_unsafe_python | False | 注册任意 Python 执行工具，仍需 SandboxProvider 才能真正执行 (L271-277, L1260-1271) |
| skills_directories | None→["skills"] (L261) | 技能目录 |
| auto_discover_skills | True | 自动发现技能并注册 skill 系统工具 (L288-301) |
| input/tool/output_guardrails | None | 三类安全策略，交给 GuardrailManager (L221-225) |
| hooks | None | 运行期 hook，交给 HookManager (L226) |
| session_store | None | v0.10 Session 持久化后端，传给 AgentRuntime (L332-336) |
| capability_registry / policy_engine | None | v0.10 能力注册表与策略引擎 (L329-331) |
| budget_limits | None | 模型调用/工具调用/token/时间/成本预算 (L332-336) |
| context_budget / context_compactor | None / ContextCompactor() | 上下文 token 预算与压缩器 (L240-241) |
| debug / log_level / log_file | False / "INFO" / None | debug 时在 `logs/` 下建 `{name}.log` 并建 LoggerManager (L243-258) |
| tracetools | None | langfuse 配置 dict，走 langfuse 包装的 openai client (L358-371) |

### 方法分组（按主题）

#### 1. 运行生命周期

完整阶段流程（`run` L480-L747 为同步总入口）：

1. 参数校验：result_format/stream 组合、max_tool_iterations≥1（L520-528）。
2. 运行态初始化：traceid=uuid4、`_current_run_id`、user_id、metadata、TraceRecorder(trace)（L531-545），清空计数器/usage/记忆候选（L546-562）。
3. `_begin_session_run` (L852-L882)：`runtime.open_session` → ContextProjector 投影历史 → 记 turn.started / message.received 事件 → 返回 projected_history。
4. `_record_trace("run_start")` (L573 → L910)。
5. `_run_hooks("before_run")` (L580 → L941)；HOOK_BLOCK 则 `_finish_run(success=False)`（L589）并按 stream/event 格式返回错误流。
6. 输入 guardrail：`guardrails.check_input`（L598 → guardrails.py）；拦截 → `_finish_run`（L612）；可替换 query（L619-622）。
7. history 装载：仅当传了 session_id 且未显式传 history 时用投影历史（L625）。
8. `_process_runtime_tools` (L630 → L1350)：注册运行时工具并返回 OpenAI schema。
9. 任务转移判断：`light_swarm` 时 `_handle_task_transfer`（L642 → L2498），命中则直接返回目标 agent 结果。
10. 组装 system_prompt（L647-656：名称/指令/身份/日期时间）＋技能 XML（L658-662，`skill_manager.get_skills_xml`）。
11. `_add_memory_context` (L664 → L1436)：检索记忆拼进 query。
12. ToT 分支：`run_thought` (L669 → L2745) 得到补充说明+过滤后工具；否则用 runtime_tools（L673-675）。
13. `self.chat_params` 构建：system + history + user 消息，stream 标志（L680-685）；metadata 并入（L688-690）。
14. 工具优先级：active_tools(ToT) > runtime_tools > registry 全量（L694-700）；有工具则设 tools/tool_choice="auto"（L702-706）。
15. `_prepare_model_request` (L714 → L1072)：上下文压缩检查 + before_model_request hook + 预算 model_calls + model_request trace。
16. 首次模型调用 `self.client.chat.completions.create(**chat_params)`（L726）；异常 → `_complete_model_request(error=e)`（L728）+ `_finish_run`（L732）。
17. `_complete_model_request(response=response)` (L739 → L1105)：记延迟/usage、预算 tokens。
18. `_core_run_logic` (L742 → L1900)：分流到 `_run_stream_logic` / `_run_non_stream_logic`。
19. 收尾：流式→原样返回或 `_stream_as_events`（L744-745 → L1415）；非流式→`_format_run_result`（L747 → L1378）。

- `run` (L480) — 同步主入口；调用 `_begin_session_run`(L563)、`_record_trace`(L573)、`_run_hooks`(L580)、`guardrails.check_input`(L598)、`_process_runtime_tools`(L630)、`_handle_task_transfer`(L642)、`_add_memory_context`(L664)、`run_thought`(L669)、`_prepare_model_request`(L714)、`client.chat.completions.create`(L726)、`_complete_model_request`(L728,739)、`_core_run_logic`(L742)、`_stream_as_events`(L745)、`_format_run_result`(L747)；被外部调用方、LightSwarm.run(L3203)、`arun`(L758)、handoff 的目标 agent（L2643, L2699）调用。
- `arun` (L749) — 异步入口：非流式 `asyncio.to_thread(self.run)`，流式转 `astream`；被外部 async 调用方调用。
- `astream` (L761) — 把同步流生成器包装成可取消的 async 迭代器；被 `arun`(L759) 调用。
- `_begin_session_run` (L852) — 开 session、投影历史、记 turn 事件；被 `run`(L563) 调用；内部调 `runtime.open_session`(L861)、`ContextProjector().messages`(L868)、`_record_session_event`(L876,881)。
- `_finish_run` (L995) — 收尾：预算 seconds、on_error/after_run hook、run_end trace（含 duration/usage/计数）、turn.completed/failed；被 `run`(L589,612,716,732)、`_run_non_stream_logic`(L2078,2080,2085,2091,2102,2109)、`_run_stream_logic`(L2224,2351,2407,2457,2469,2485)、`_handle_task_transfer`(L2532,2548,2570,2595,2602)、`_handle_task_transfer_stream`(L2655,2662) 调用。
- `_core_run_logic` (L1900) — stream 分流；被 `run`(L742) 调用，内部调 `_run_stream_logic`(L1903) / `_run_non_stream_logic`(L1905)。
- `_format_run_result` (L1378) — 非流式结果格式化（str/RunResult/dict，识别 "[LA-" 前缀为错误）；被 `run`(L595,618,722,738,747) 调用。
- `_stream_as_events` (L1415) — 把流 chunk 包装成 StreamEvent（error/tool_result/tool_call/event/content 五类）；被 `run`(L593,616,720,736,745) 调用。
- `_error_stream` (L2489, staticmethod) — 错误字符串包装成单元素生成器；被 `run`(L591,614,718,734) 与 `_handle_task_transfer`(L2538,2554,2576) 调用。
- `log` (L472) — debug 日志入口；被全类大量调用。
- `run_async_safely` (L79, 模块级) — 同步上下文跑协程；被工具执行点 L2000、L2285 调用。

#### 2. 上下文组装

- system prompt 组装在 `run` 内联（L647-656）＋技能 XML（L658-662，调 `SkillManager.get_skills_xml` L659）。
- `_add_memory_context` (L1436) — 检索用户（及 self_learning 时 agent 自身）记忆拼成 "##用户偏好/##问题相关补充信息" 前缀再接原 query（L1483）；调 `_retrieve_memory_with_hooks`(L1443,1464)、`_store_memory_with_policy`(L1454,1475)；被 `run`(L664) 调用。
- `run_thought` (L2745) — ToT 三连调用 tot_client：规划（L2776）→ 反思（L2788）→ 强制 JSON 工具集（L2813）；filter_tools=True 时 `tool_registry.filter_tools`(L2830) 过滤；返回 (补充说明, active_tools)；被 `run`(L669) 调用。
- `_build_context` (L2710) / `_build_agent_memory` (L2727) — 旧版记忆上下文拼串 helper，当前主流程未调用（遗留）。
- `_compact_model_context` (L1092) — context_budget 超限时 `context_compactor.compact_to_budget` 压缩 messages；被 `_prepare_model_request`(L1073) 调用。
- `compact_session` (L810) — 手动压缩指定 session 并落库；被外部调用；调 `ContextProjector().messages`(L819)、`context_compactor.compact`(L819)。

#### 3. LLM 调用

- `client.chat.completions.create` 调用点共 5 处（另 tot_client 3 处）：
  - L726 `run` 首次调用；L2096 `_run_non_stream_logic` 后续轮；L2463 `_run_stream_logic` 后续轮；L2868 `_detect_intent`；L2993 `create_tool`。
  - ToT：L2776、L2788、L2813（`run_thought`，走 `self.tot_client`）。
- `_initialize_clients` (L345) — 三分支选客户端：litellm → `LiteLLMClient`（L349）；tracetools → langfuse.openai（L358-371）；默认 → `openai.OpenAI`（L373-382）；被 `__init__`(L325) 调用。
- `_prepare_model_request` (L1072) — 每次模型调用前的统一闸门（压缩→hook→预算→trace）；被 `run`(L714)、`_run_non_stream_logic`(L2089)、`_run_stream_logic`(L2455) 调用。
- `_complete_model_request` (L1105) — 挂延迟/usage/结果到 model_request trace 事件，预算扣 tokens（L1137）；被 L728/739、L2098/2104、L2465/2472 调用。
- 重试/错误处理：非流式靠 `for _ in range(max_retry)` 外层循环（L1918），失败重试到 max_retry 用尽返回 "Failed to generate a valid response."（L2107-2110）；流式是 try/except + continue（L2474-2479）+ for-else 兜底（L2481-2487），另有 `max_tool_iterations` 限制（L2400-2417）。
- `_accumulate_usage` (L1144) — 累计 token 用量；被 `_complete_model_request`(L1120)、流式 usage chunk 处（L2214）调用。
- 流式分支要点：`_run_stream_logic` (L2112) 逐 chunk yield（L2141），累积 reasoning_content/content（L2149-2160），按 index 拼接 tool_call 增量（L2165-2186），finish_reason 或 usage-only chunk 判定流结束（L2203-2211）。

#### 4. 工具循环

- 非流式（`_run_non_stream_logic` L1907）：
  - L1920 判 `response.choices[0].message.tool_calls`；L1930 把 assistant 消息（OpenAI 对象）append 进 messages。
  - 每个 tool_call：记 `_current_tool_calls`/`_record_trace("tool_call")`（L1940-1941）→ `json.loads(arguments)`（L1949，失败发 LA-JSON 并以 role:tool 回填错误 L1967-1971）→ `_prepare_tool_call`（L1976 → L1253）→ `run_async_safely(self.tool_dispatcher.dispatch(...))`（L2000 → tools.py `AsyncToolDispatcher.dispatch` L294）→ 生成器响应逐 chunk 累加（L2014-2035）→ `_apply_after_tool_result`（L2053 → L1313）→ `_record_trace("tool_result")`（L2054）→ role:tool 消息回填 messages（L2060-2064）。
  - 无 tool_calls → `_apply_output_guardrails`（L2073）→ `model_response` trace（L2075）→ `_finish_run(success=True)`（L2080）→ return reply。
  - `finish` 工具特判：非流式 L2018-2020（累加 delta）、L2084-2086（直接 `_finish_run(stage="finish_tool")` 并 return）。
  - 下一轮：`_prepare_model_request`(L2089) → `create`(L2096)。
- 流式（`_run_stream_logic` L2112）：
  - 收集完 tool_calls 后逐个执行（L2230-2393）：yield 工具调用信息 dict（L2255）→ `_parse_tool_arguments`（L2264 → L3028）→ `_prepare_tool_call`（L2265）→ `run_async_safely(dispatch)`（L2285）→ 流式工具边执行边 yield（L2299-2316）→ 非流式工具 `_apply_after_tool_result`（L2327）→ yield `tool_output` dict（L2316/2338）。
  - `finish` 工具：L2318-2320 累加 delta、L2348-2356 `_finish_run`、L2396-2397 return。
  - `max_tool_iterations` 用尽：L2400-2417 `_finish_run` + yield 错误 + return。
  - 结果回填：构造 assistant dict（含 reasoning_content 与 tool_calls 数组，L2421-2440）＋逐条 role:tool 消息（L2445-2451）append 进 chat_params["messages"] → `_prepare_model_request`(L2455) → `create`(L2463) → break 进入下一轮 while。
- `_prepare_tool_call` (L1253) — 工具执行前总闸门（详见安全分组）；被 L1976、L2265 调用。
- `_process_runtime_tools` (L1350) — 运行时工具注册进主 registry 并重建 dispatcher（L1374）；被 `run`(L630) 调用。
- `load_tools` (L443) — 初始工具装载（字符串走 `ToolLoader.load_tool` L448）；被 `__init__`(L266)、`create_tool`(L3024) 调用。
- `get_tool` (L433) / `get_tools` (L390) / `validate_tools` (L396) — 对外查询/校验；被外部调用。
- `_parse_tool_arguments` (L3028) — 三级容错解析工具参数 JSON（直解→正则提取→手写状态机）；被 L2264 调用。
- `create_tool` (L2932) — LLM 生成 Python 工具代码写盘并自动加载（L2993 调模型、L3019 写文件、L3024 load_tools）；被外部调用（self_learning 场景）。

#### 5. 安全与治理

- 输入 guardrail：`run` L598 `guardrails.check_input`（GuardrailManager）。
- 工具 guardrail：`_apply_tool_guardrails` (L1208) → `guardrails.check_tool`(L1209)；被 `_prepare_tool_call`(L1297) 调用。
- 输出 guardrail：`_apply_output_guardrails` (L1324) → 先 after_model_response hook（L1325）再 `guardrails.check_output`（L1330）；仅被非流式 L2073 调用（流式不检查——见阅读陷阱）。
- `_prepare_tool_call` (L1253) 顺序：构造 CapabilitySpec（L1254-1261，UNSAFE_PYTHON_TOOL_NAMES 需沙箱）→ `_sandbox_available`（L1262 → L1240）→ `capability_registry.policy_engine.evaluate_sync(PolicyRequest)`（L1272 → capabilities.py）→ 记 policy.decision session 事件（L1278）→ 预算 `runtime.budget.consume(tool_calls=1)`（L1294）→ `_apply_tool_guardrails`(L1297) → `_run_hooks("before_tool_call")`（L1301）。
- `_apply_after_tool_result` (L1313) — after_tool_result hook，可改写/阻断工具输出；被 L2053、L2327 调用。
- `_run_hooks` (L941) — 统一 hook 执行器：构造 HookContext → `hooks.run`（hooks.py HookManager）→ 镜像 hook_decision/review 事件 → HOOK_BLOCK 记 hook_block trace；被 before_run(L580)、on_error(L1028)、after_run(L1029)、before_model_request(L1074)、before_tool_call(L1301)、after_tool_result(L1314)、after_model_response(L1325)、before/after_memory_retrieve(L1495,1515)、before_memory_write(L1559)、after_memory_write(L1631,1799)、before_memory_promote(L1696)、after_memory_promote(L1790)、on_handoff(L2540) 调用。
- `_notify_error` (L1059) — 非终止错误的 on_error 通知；被工具参数/guardrail/执行错误处（L1960,1983,2272,2367,2387）与 stream_retry（L2478）调用。
- 预算（BudgetManager，runtime.py）：`consume(model_calls=1)` L1082；`consume(tokens=...)` L1137；`consume(tool_calls=1)` L1294；`consume(seconds=...)` L1014。BudgetExceeded → "LA-BUDGET"（L1017,1084,1139,1296）。
- `_format_hook_error` (L1065) / `_format_guardrail_error` (L1201) — 统一错误码文案（LA-HOOK / LA-GUARDRAIL，errors.format_error_code）。
- review/approval：`run` 的 `approval_id` 参数（L496-497,536-537）只透传进 hook metadata；review 事件经 `_run_hooks` 的 `review_events` 落 trace（L966-969）。

#### 6. 记忆

- 读取调用点：`_retrieve_memory_with_hooks` (L1485) — before/after_memory_retrieve hook 包夹 `self.memory.retrieve(query, user_id)`（L1514，MemoryProtocol）；`_filter_memory_results`（L1534 → L1880，`memory_policy.allows_result`）过滤；被 `_add_memory_context`(L1443,1464) 调用。
- 写入调用点：`_store_memory_with_policy` (L1536) — before_memory_write hook（L1559）→ `memory_policy.allows_write`（L1576）→ 内部来源走 `_requires_memory_promotion`（L1619 → L1650）→ `_handle_memory_promotion_candidate`（L1620 → L1667）→ 否则 `_store_memory_record`（L1630 → L1864，按签名探测决定是否带 metadata 调 `self.memory.store`）→ after_memory_write hook（L1631）→ 指纹去重计数（L1639-1642）→ `memory_write` trace（L1643）。
- 候选晋升：`_handle_memory_promotion_candidate` (L1667) — 建 MemoryCandidate（L1679）→ upsert（L1692 → L1835）→ before_memory_promote hook（L1696）→ `memory_policy.allows_promotion`（L1724）→ `_apply_memory_promotion_decision`（L1725/手动 L431 → L1743，只有 promotes 才真正落库 L1780）。
- 公开 API：`promote_memory_candidate` (L407) 手动晋升/拒绝；`list_memory_candidates` (L400) 列出待审候选。
- mem0/shared_memory 分支：core.py 不直接 import mem0/shared_memory 模块；外部记忆统一以 MemoryProtocol（protocol.py）传入 `memory` 参数；capabilit 层再以 `MemoryProviderAdapter` 包装注册（L889）。
- 每次运行都会把用户 query 原样写入记忆（L1454-1460），检索结果注入的是 query 前缀而非 system prompt（L1483）。

#### 7. 会话与观测

- session 集成：`_begin_session_run`（L852，open_session/投影/turn 事件）、`_record_session_event` (L891)（session.append + runtime.session_store.save，异常记 `_session_store_error` 不打断主流程）。
- `_record_trace` (L910) — 双写枢纽：trace 事件类型映射 session 事件类型（L913-924：run_start→run.started、model_request→model.requested、tool_call→tool.requested、guardrail_block/hook_block→policy.blocked、handoff→handoff.requested、run_end→run.completed/failed 等），先 `_record_session_event` 再 `TraceRecorder.record`（L938）；被全类约 40 处调用。
- 对外会话 API：`get_session` (L778)、`export_session` (L783)、`replay_session` (L789)、`checkpoint_session` (L795 → runtime.checkpoint)、`fork_session` (L802 → runtime.fork)、`compact_session` (L810)、`pause/resume/cancel_session` (L835/838/841，只记事件)。
- 恢复：无独立 restore 方法——传 `session_id` 给 `run` 时由 `runtime.open_session`(L861) 从 SessionStore 取回已有会话并投影历史（L625）实现"恢复"；`replay_session` 可重放事件流。
- tracing：`TraceRecorder` 每次运行重建（L540-545，支持 parent_trace_id/run_group_id 嵌套归组）；`export_trace` (L1158)、`summarize_trace` (L1165)、`export_trace_to` (L1173)（转发 tracing.py 同名函数）。
- `_build_model_request_trace` (L1189) — 生成不含消息正文的请求摘要（model/stream/message_count/tools）；被 `_prepare_model_request`(L1086) 调用。
- capability 审计挂钩：`__init__` 把 `capability_registry.audit` 指到 `_record_session_event`（L338）。

#### 8. MCP

- `setup_mcp` (L460, async) — 保存 mcp_setting → `MCPClientManager(mcp_setting, self.tool_registry)`（L468）→ `register_mcp_tool()`（L469）把 MCP 工具注册进 ToolRegistry；被外部调用（须 await）。
- 调用路径：MCP 工具注册后与本地工具无异——经 `chat_params["tools"]` 暴露给模型，执行统一走 `self.tool_dispatcher.dispatch(name, args)`（L2000/L2285，tools.py AsyncToolDispatcher L294，其内部再路由到 MCP client）。core.py 中 `self.mcp_client` 仅在 setup_mcp 赋值，无其他直接调用点。

## LightSwarm 类

职责：极简多代理注册表（L3173-L3203）。仅保存 `agents: Dict[str, LightAgent]`（L3175），作为 handoff 的名字寻址容器，不管理调度。

- `__init__` (L3174) — 初始化空 agents 字典。
- `register_agent` (L3177) — 批量注册 agent；重名只打日志不覆盖（L3184-3186）；被外部调用。
- `run` (L3192) — 校验 agent 已注册（L3201）后以 `light_swarm=self` 调 `agent.run(query, light_swarm=self, stream=stream, **run_kwargs)`（L3203）；被外部调用。
- agent 间交接逻辑（实际在 LightAgent 侧）：`run` 传 light_swarm → `_handle_task_transfer` (L2498)：`_detect_intent` (L2514 → L2839，用主模型按 "transfer to {name}" 子串匹配意图 L2884-2886) → 目标校验（L2529）→ `on_handoff` hook 可改写 query/目标（L2540-2580）→ `_handle_task_transfer_stream` (L2611，`yield from target_agent.run(...)` 并透传 parent_trace_id/run_group_id L2643-2646) 或 `_handle_task_transfer_non_stream` (L2668，L2699) → 双侧 `_finish_run` 记 handoff 结果。
- `_transfer_to_agent` (L2889) — 旧版交接实现，当前主流程未调用（遗留，阅读陷阱之一）。

## 跨模块调用关系汇总

| 调用方(core.py:行号) | 被调模块.符号 | 说明 |
|---|---|---|
| `__init__` L196-197 | tools.ToolRegistry / ToolLoader | 工具注册表与加载器 |
| `__init__` L220, L1576, L1724, L1887 | protocol.MemoryPolicy（allows_write/allows_result/allows_promotion/write_fingerprint/scoped_user_id） | 记忆安全策略 |
| `__init__` L221; run L598 | guardrails.GuardrailManager / check_input | 输入闸门 |
| `_apply_tool_guardrails` L1209 | guardrails.GuardrailManager.check_tool | 工具闸门 |
| `_apply_output_guardrails` L1330 | guardrails.GuardrailManager.check_output | 输出闸门（仅非流式） |
| `__init__` L226; `_run_hooks` L963 | hooks.HookManager / HookContext.run | 生命周期钩子 |
| `__init__` L253 | logger.LoggerManager | debug 日志 |
| L448, L1362 | tools.ToolLoader.load_tool | 按名字加载工具 |
| L303, L1374 | tools.AsyncToolDispatcher(...) | 重建派发器 |
| L2000, L2285 | tools.AsyncToolDispatcher.dispatch (tools.py L294) | 工具执行（含 MCP） |
| L394, L700, L2239, L2760, L2830 | tools.ToolRegistry（get_tools/get_tools_str/filter_tools/function_info/validate_tools） | 工具 schema 与过滤 |
| `_initialize_clients` L349, L354 | litellm_client.LiteLLMClient | provider="litellm" 路由 |
| `_initialize_clients` L359-366 | langfuse.openai | tracetools 观测 |
| `_begin_session_run` L861; `run` L625 | runtime.AgentRuntime.open_session + session.SessionStore | 会话打开/恢复 |
| `_record_session_event` L896-903 | session.Session.append / runtime.session_store.save | session 事件落库 |
| `_begin_session_run` L868; `compact_session` L819 | session.ContextProjector().messages | 历史投影 |
| `_compact_model_context` L1096 | session.ContextCompactor.compact_to_budget | 预算压缩 |
| L241, L1096; `compact_session` L819 | session.ContextCompactor | 压缩器 |
| `_finish_run` L1014; L1082, L1137, L1294 | runtime.BudgetManager.consume（经 runtime.budget） | 时间/模型调用/token/工具调用预算 |
| L1015, L1083, L1138, L1295 | runtime.BudgetExceeded | 预算超限异常 |
| `checkpoint_session` L800; `fork_session` L808 | runtime.AgentRuntime.checkpoint / fork | 检查点与分叉 |
| L332-337 | runtime.AgentRuntime + CapabilityRegistry | v0.10 运行时装配 |
| `_register_builtin_providers` L887, L889 | capabilities.ToolProviderAdapter / MemoryProviderAdapter + CapabilityScope | 内置 Provider 注册 |
| `_prepare_tool_call` L1272 | capabilities.PolicyEngine.evaluate_sync(PolicyRequest) | 工具策略评估 |
| `_prepare_tool_call` L1254-1260 | capabilities.CapabilitySpec / CapabilityRisk | 工具能力描述 |
| `invoke_capability` L846 | capabilities.CapabilityRegistry.invoke | 通用能力调用 |
| `__init__` L262; run L659 | skills.SkillManager（discover_skills/get_skills_xml） | 技能发现与注入 |
| `__init__` L295 | skill_tools.create_skill_tools | 注册技能系统工具 |
| L468-469 | mcp_client_manager.MCPClientManager.register_mcp_tool | MCP 工具注册 |
| `_record_trace` L938; `run` L540 | tracing.TraceRecorder.record | 结构化 trace 记录 |
| `_complete_model_request` L1118; L1145; L2217 | tracing.normalize_usage | 用量规范化 |
| `summarize_trace` L1167; `export_trace_to` L1181 | tracing.summarize_trace / export_trace | 聚合与导出 |
| L1017, L1070, L1084, L1206, L1271, L1288, L1296, L1951 等 | errors.format_error_code | LA-* 错误码文案 |
| L729, L2099, L2376, L2466, L2589, L2649 | errors.format_lightagent_error | 异常包装 |
| `_format_run_result` L1394; `_stream_as_events` L1424-1434 | result.RunResult / StreamEvent | 返回对象 |
| `__init__` L271-277; L1260 | builtin_tools（safe_expression/upload_file_to_oss/execute_python_*、UNSAFE_PYTHON_TOOL_NAMES） | 内置工具与沙箱名单 |
| L1483 等经 self.memory | protocol.MemoryProtocol.retrieve / store（L1514, L1877-1878） | 外部记忆后端（mem0 等经此接入） |

## 关键数据结构

- `self.chat_params`（L680-710）：`{model, messages, stream, tools?, tool_choice?: "auto", session_id?(tracetools 时), ...metadata}`；每次 run 整体重建，messages 是可变列表，后续轮次在其上 append。
- messages 列表形态（混合 dict 与 OpenAI 对象）：
  - 初始：`[{"role":"system","content":system_prompt}] + history + [{"role":"user","content":query}]`（L682-683）。
  - 非流式工具轮：直接 append OpenAI 的 assistant 消息对象（L1930）＋ role:tool dict `{"role":"tool","tool_call_id","content"}`（L1967-1971、L2060-2064）。
  - 流式工具轮：手工构造 assistant dict `{"role":"assistant","content":"","reasoning_content":...,"tool_calls":[{"id","type":"function","function":{"name","arguments"}}]}`（L2421-2440，content 必须空串、reasoning_content 为 DeepSeek 兼容）＋ role:tool dict（L2445-2451）。
- tool_calls 形态：
  - 非流式：OpenAI 对象，访问 `tool_call.id / .function.name / .function.arguments`（L1934-1939）。
  - 流式累积器：`[{"name":"","arguments":"","index":i,"title":"","id":""}]`，arguments 按 index 分片拼接（L2174-2186）。
  - 对外记录 `_current_tool_calls`：非流式 `{"id","name","arguments"}`（L1935-1939）；流式 `{"name","title","arguments"}`（L2246-2250）。
- 流式 yield 的增量事件：工具调用开始 `{"name","title","arguments"}`（L2255）；工具输出 `{"name","title","output","latency_ms"}`（L2304-2312、L2328-2336）；错误 `{"name","title","error"}`（L2278、L2373、L2393）；其余为裸 `ChatCompletionChunk`（L2141）。
- StreamEvent（L1424-1434）：`type ∈ {error, tool_result, tool_call, event, content}` + data + trace_id；"[LA-" 开头字符串判为 error。
- RunResult（L1394-1402）：content / reasoning_content / tool_calls / usage / trace_id / trace / error。
- Session 事件类型（映射表 L913-924 及各调用点）：turn.started / message.received / model.requested / model.completed / model.failed / assistant.completed / tool.requested / tool.completed / policy.blocked / policy.decision（L1278）/ handoff.requested / run.started / run.completed / run.failed / error.recorded / trace.recorded / context.compacted（L1098）/ session.paused|resumed|cancelled（L836-842）/ memory 写入相关经 trace 双写。
- 记忆候选（L1679-1691）：MemoryCandidate{candidate_id, data, memory_user_id, original_user_id, source, scope, agent_name, trace_id, run_id, status, injectable, metadata}。
- hook 阶段全集（见第 5/6 分组）：before_run、before_model_request、before_tool_call、after_tool_result、after_model_response、on_handoff、before/after_memory_retrieve、before/after_memory_write、before/after_memory_promote、on_error、after_run。

## 阅读陷阱

1. 输出 guardrail 只在非流式路径生效（L2073 调 `_apply_output_guardrails`）；`_run_stream_logic` 从不检查输出，流式内容不经过 output_guardrails。
2. `max_tool_iterations` 只约束流式工具循环（L2400）；非流式的工具轮数由 `max_retry` 控制（L1918），未传时两者同值（L528）但语义不同。
3. `_run_stream_logic` 标注 `Generator[str,...]` 但实际 yield 的是 `ChatCompletionChunk` 对象和 dict（L2141 注释自认类型不匹配）；消费方必须自行判型，`_stream_as_events` 正是为此存在。
4. 消息列表混合类型：非流式 append 的是 OpenAI 消息对象（L1930），流式 append 的是手工 dict（L2421），且流式 assistant 的 content 必须是空字符串而非 None（L2423 注释）、须带 reasoning_content（DeepSeek 兼容）。
5. 记忆注入改写的是用户 query 而非 system prompt（L1483），且每次 run 都把原 query 写回记忆（L1454）——重复运行同一 query 会造成记忆膨胀（有 fingerprint 去重，L1640-1642）。
6. `_transfer_to_agent`（L2889）是遗留死代码，真实交接路径是 `_handle_task_transfer` → `_handle_task_transfer_stream/non_stream`；同理 `_build_context`/`_build_agent_memory`（L2710/L2727）已不被主流程调用。
7. `run_thought` 中 runtime_tools 的"临时注册表过滤"是空实现（L2753-2758、L2823-2827 直接 pass），运行时工具在 ToT 下不做过滤、原样返回（L2828）。
8. `_detect_intent` 的意图解析只是对模型输出做 `"transfer to {name}"` 子串匹配（L2884-2886），且这次意图判断调用模型（L2868）不经过 budget/hook 闸门。
9. `LightAgent.run` 会重置大量实例状态（traceid、chat_params、计数器，L531-562），同一实例并发/嵌套调用不安全；handoff 时目标 agent 用的是它自己的状态（trace 通过 parent_trace_id 关联，L2640）。
10. `enable_unsafe_python` 只负责注册工具；真正执行还需在 capability registry 挂 sandbox Provider（L1262-1271，否则 LA-SANDBOX 拒绝）。

## 高频符号中文短语表

| 符号 | 中文短语（作图节点副标题） |
|---|---|
| LightAgent | 单代理编排核心 |
| LightSwarm | 多代理注册与寻址 |
| run | 同步主入口：一次完整运行 |
| arun / astream | 异步入口 / 异步流包装 |
| _begin_session_run | 开启会话并投影历史 |
| _finish_run | 收尾：hook+trace+turn 事件 |
| _core_run_logic | 流式/非流式分流 |
| _run_non_stream_logic | 非流式工具循环 |
| _run_stream_logic | 流式 chunk 解析与工具循环 |
| _prepare_model_request | 模型调用前统一闸门 |
| _complete_model_request | 回填延迟用量并扣预算 |
| _prepare_tool_call | 工具执行前安全总闸门 |
| _add_memory_context | 记忆检索注入用户输入 |
| run_thought | ToT 三段式思维树规划 |
| _handle_task_transfer | Swarm 任务移交编排 |
| _detect_intent | LLM 意图识别移交目标 |
| _run_hooks | 生命周期钩子执行器 |
| _record_trace | trace/session 双写事件 |
| _record_session_event | session 事件落库 |
| _apply_output_guardrails | 输出安全检查（仅非流式） |
| _apply_tool_guardrails | 工具参数安全检查 |
| _store_memory_with_policy | 记忆写入策略闸门 |
| _apply_memory_promotion_decision | 记忆候选晋升落库 |
| _parse_tool_arguments | 工具参数三级容错解析 |
| _format_run_result | 非流式结果格式化 |
| _stream_as_events | 流包装为结构化事件 |
| setup_mcp | 注册 MCP 工具到注册表 |
