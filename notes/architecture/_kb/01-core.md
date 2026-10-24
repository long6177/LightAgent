# core.py 源码知识库

> 源文件：`LightAgent/core.py`，共 3300 行（以工作树 2026-10-24、提交 ac177ca 实读为准）。
> 行号均为 def/class 所在行的真实行号。

## 模块概览

core.py 是 LightAgent 框架的核心编排层：定义了单代理 `LightAgent`（负责一次 run 的完整生命周期——session 打开、hook/guardrail 检查、记忆注入、ToT 思维树、LLM 调用、工具循环、trace/session 事件记录、预算控制、agent 间任务转移）和多代理注册表 `LightSwarm`（按名字登记 agent 并作为 handoff 的寻址容器）。它把 tools/protocol/session/tracing/guardrails/hooks/capabilities/runtime 等子模块粘合进 `run()` 主流程，是绘制架构图的中心节点。

## 类与符号清单

- `run_async_safely` (L81-L114)：模块级函数，在同步入口里安全执行协程（已有事件循环时切到独立线程池跑 `asyncio.run`）。
- `LightAgent` (L118-L3261)：单代理类，run 生命周期 + 工具循环 + 记忆/安全/会话/观测的编排者。
- `LightSwarm` (L3264-L3294)：多代理注册表，`agents: Dict[str, LightAgent]`，提供注册与入口 run。
- `if __name__ == "__main__"` (L3297-L3300)：占位打印，无逻辑。

## LightAgent 类

职责：接收用户 query，组装 system prompt 与上下文（记忆/ToT/技能），循环调用 LLM 并执行工具调用直至产出最终回复；全程产生 Trace 事件与 Session 事件，受 hooks/guardrails/policy/budget 治理；支持流式与非流式两种执行路径，以及在 LightSwarm 内把任务移交给其他 agent。

构造参数表（`__init__` L121-L345）：

| 参数 | 默认值 | 作用 |
|---|---|---|
| name | None→`LightAgent{8位随机数}` (L212-214) | 代理名，也是 swarm 注册键与 handoff 目标名 |
| instructions | None→"You are a helpful agent." (L216-217) | 注入 system prompt 的代理指令 |
| role | None | 角色描述，注入 system prompt |
| model | 必填，空则 "gpt-4o-mini" (L205-206) | 主模型名 |
| api_key | None→env `OPENAI_API_KEY` (L207-208) | LLM API key，最终为 None 则抛 ValueError (L308-311) |
| base_url | None→env `OPENAI_BASE_URL`→`https://api.openai.com/v1` (L209-210, L315) | LLM 服务地址 |
| provider | None（仅允许 None/"litellm"，否则 ValueError L203-204） | "litellm" 时改用 LiteLLMClient (L349-354) |
| websocket_base_url | None | 仅保存 (L313)，当前主流程未使用 |
| memory | None | 外部 MemoryProtocol 记忆后端（mem0 等经此注入，core 不直接 import mem0/shared_memory） |
| memory_policy / memory_namespace | None | 记忆安全策略；namespace 快捷生成默认 MemoryPolicy (L222) |
| tree_of_thought | False | 启用 ToT 思维树前置规划 (L317-324) |
| tot_model / tot_api_key / tot_base_url | None→主 api_key/base_url；tot_model 默认 "deepseek-r1" (L318-324) | ToT 专用模型 |
| filter_tools | True | ToT 第三轮按 JSON 结果过滤工具 (L2910-2921) |
| self_learning | False | 额外检索/写入 agent 自身记忆 (L1499-1519) |
| tools | None | 初始工具列表（字符串名或带 tool_info 的函数），经 `load_tools` (L266-268) |
| enable_unsafe_python | False | 注册任意 Python 执行工具，仍需 SandboxProvider 才能真正执行 (L274-279, L1286-1299) |
| skills_directories | None→["skills"] (L263) | 技能目录 |
| auto_discover_skills | True | 自动发现技能并注册 skill 系统工具 (L290-303) |
| input/tool/output_guardrails | None | 三类安全策略，交给 GuardrailManager (L223-227) |
| hooks | None | 运行期 hook，交给 HookManager (L228) |
| session_store | None | v0.10 Session 持久化后端，传给 AgentRuntime (L334-338) |
| capability_registry / policy_engine | None | v0.10 能力注册表与策略引擎 (L331-333) |
| budget_limits | None | 模型调用/工具调用/token/时间/成本预算 (L334-338) |
| context_budget / context_compactor | None / ContextCompactor() | 上下文 token 预算与压缩器 (L242-243) |
| debug / log_level / log_file | False / "INFO" / None | debug 时在 `logs/` 下建 `{name}.log` 并建 LoggerManager (L245-260) |
| tracetools | None | langfuse 配置 dict，走 langfuse 包装的 openai client (L360-373) |

### 方法分组（按主题）

#### 1. 运行生命周期

完整阶段流程（`run` L482-L757 为同步总入口）：

1. 参数校验：result_format/stream 组合、max_tool_iterations≥1（L526-534）。
2. 运行态初始化：traceid=uuid4、`_current_run_id`、user_id、metadata、TraceRecorder(trace)（L537-553），清空计数器/usage/记忆候选（L554-570）。
3. `_begin_session_run` (L863-L893)：`runtime.open_session` → ContextProjector 投影历史 → 记 turn.started / message.received 事件 → 返回 projected_history。
4. `_record_trace("run_start")` (L581 → L932)。
5. `_run_hooks("before_run")` (L589 → L964)；HOOK_BLOCK 则 `_finish_run(success=False)`（L598）并按 stream/event 格式返回错误流。
6. 输入 guardrail：`guardrails.check_input`（L607 → guardrails.py）；拦截 → `_finish_run`（L621）；可替换 query（L628-631）。
7. history 装载：仅当传了 session_id 且未显式传 history 时用投影历史（L634）。
8. `_process_runtime_tools` (L639 → L1378)：注册运行时工具并返回 OpenAI schema。
9. 任务转移判断：`light_swarm` 时 `_handle_task_transfer`（L651 → L2589），命中则直接返回目标 agent 结果。
10. 组装 system_prompt（L659-665：名称/指令/身份/日期时间）＋技能 XML（L667-671，`skill_manager.get_skills_xml`）。
11. `_add_memory_context` (L674 → L1464)：检索记忆拼进 query。
12. ToT 分支：`run_thought` (L679 → L2836) 得到补充说明+过滤后工具；否则用 runtime_tools（L683-685）。
13. `self.chat_params` 构建：system + history + user 消息，stream 标志（L690-695）；metadata 并入（L698-700）。
14. 工具优先级：active_tools(ToT) > runtime_tools > registry 全量（L704-710）；有工具则设 tools/tool_choice="auto"（L712-716）。
15. `_prepare_model_request` (L724 → L1105)：上下文压缩检查 + before_model_request hook + 预算 model_calls + model_request trace。
16. 首次模型调用 `self.client.chat.completions.create(**chat_params)`（L736）；异常 → `_complete_model_request(error=e)`（L738）+ `_finish_run`（L742）。
17. `_complete_model_request(response=response)` (L749 → L1141)：记延迟/usage、预算 tokens。
18. `_core_run_logic` (L752 → L1991)：分流到 `_run_stream_logic` / `_run_non_stream_logic`。
19. 收尾：流式→原样返回或 `_stream_as_events`（L753-756 → L1443）；非流式→`_format_run_result`（L757 → L1406）。

- `run` (L482) — 同步主入口；调用 `_begin_session_run`(L571)、`_record_trace`(L581)、`_run_hooks`(L589)、`guardrails.check_input`(L607)、`_process_runtime_tools`(L639)、`_handle_task_transfer`(L651)、`_add_memory_context`(L674)、`run_thought`(L679)、`_prepare_model_request`(L724)、`client.chat.completions.create`(L736)、`_complete_model_request`(L738,749)、`_core_run_logic`(L752)、`_stream_as_events`(L755)、`_format_run_result`(L757)；被外部调用方、LightSwarm.run(L3294)、`arun`(L768)、handoff 的目标 agent（L2734, L2790）调用。
- `arun` (L759) — 异步入口：非流式 `asyncio.to_thread(self.run)`，流式转 `astream`；被外部 async 调用方调用。
- `astream` (L771) — 把同步流生成器包装成可取消的 async 迭代器；被 `arun`(L769) 调用。
- `_begin_session_run` (L863) — 开 session、投影历史、记 turn 事件；被 `run`(L571) 调用；内部调 `runtime.open_session`(L872)、`ContextProjector().messages`(L879)、`_record_session_event`(L887,892)。
- `_finish_run` (L1018) — 收尾：预算 seconds、on_error/after_run hook、run_end trace（含 duration/usage/计数）、turn.completed/failed；被 `run`(L598,621,726,742)、`_run_non_stream_logic`(L2169,2171,2176,2182,2193,2200)、`_run_stream_logic`(L2315,2442,2498,2548,2560,2576)、`_handle_task_transfer`(L2623,2639,2661,2686,2693)、`_handle_task_transfer_stream`(L2746,2753) 调用。
- `_core_run_logic` (L1991) — stream 分流；被 `run`(L752) 调用，内部调 `_run_stream_logic`(L1994) / `_run_non_stream_logic`(L1996)。
- `_format_run_result` (L1406) — 非流式结果格式化（str/RunResult/dict，识别 "[LA-" 前缀为错误）；被 `run`(L604,627,732,748,757) 调用。
- `_stream_as_events` (L1443) — 把流 chunk 包装成 StreamEvent（error/tool_result/tool_call/event/content 五类）；被 `run`(L602,625,730,746,755) 调用。
- `_error_stream` (L2581, staticmethod) — 错误字符串包装成单元素生成器；被 `run`(L600,623,728,744) 与 `_handle_task_transfer`(L2629,2645,2667) 调用。
- `log` (L474) — debug 日志入口；被全类大量调用。
- `run_async_safely` (L81, 模块级) — 同步上下文跑协程；被工具执行点 L2091、L2376 调用。

#### 2. 上下文组装

- system prompt 组装在 `run` 内联（L659-665）＋技能 XML（L667-671，调 `SkillManager.get_skills_xml` L668）。
- `_add_memory_context` (L1464) — 检索用户（及 self_learning 时 agent 自身）记忆拼成 "##用户偏好/##问题相关补充信息" 前缀再接原 query（L1521）；调 `_retrieve_memory_with_hooks`(L1477,1501)、`_store_memory_with_policy`(L1490,1513)；被 `run`(L674) 调用。
- `run_thought` (L2836) — ToT 三连调用 tot_client：规划（L2867）→ 反思（L2879）→ 强制 JSON 工具集（L2904）；filter_tools=True 时 `tool_registry.filter_tools`(L2921) 过滤；返回 (补充说明, active_tools)；被 `run`(L679) 调用。
- `_build_context` (L2801) / `_build_agent_memory` (L2818) — 旧版记忆上下文拼串 helper，当前主流程未调用（遗留）。
- `_compact_model_context` (L1128) — context_budget 超限时 `context_compactor.compact_to_budget` 压缩 messages；被 `_prepare_model_request`(L1109) 调用。
- `compact_session` (L821) — 手动压缩指定 session 并落库；被外部调用；调 `ContextProjector().messages`(L830)、`context_compactor.compact`(L830)。

#### 3. LLM 调用

- `client.chat.completions.create` 调用点共 5 处（另 tot_client 3 处）：
  - L736 `run` 首次调用；L2187 `_run_non_stream_logic` 后续轮；L2554 `_run_stream_logic` 后续轮；L2959 `_detect_intent`；L3084 `create_tool`。
  - ToT：L2867、L2879、L2904（`run_thought`，走 `self.tot_client`）。
- `_initialize_clients` (L347) — 三分支选客户端：litellm → `LiteLLMClient`（L350）；tracetools → langfuse.openai（L360-373）；默认 → `openai.OpenAI`（L375-384）；被 `__init__`(L327) 调用。
- `_prepare_model_request` (L1105) — 每次模型调用前的统一闸门（压缩→hook→预算→trace）；被 `run`(L724)、`_run_non_stream_logic`(L2180)、`_run_stream_logic`(L2546) 调用。
- `_complete_model_request` (L1141) — 挂延迟/usage/结果到 model_request trace 事件，预算扣 tokens（L1173）；被 L738/749、L2189/2195、L2556/2563 调用。
- 重试/错误处理：非流式靠 `for _ in range(max_retry)` 外层循环（L2009），失败重试到 max_retry 用尽返回 "Failed to generate a valid response."（L2198-2201）；流式是 try/except + continue（L2565-2570）+ for-else 兜底（L2572-2578），另有 `max_tool_iterations` 限制（L2490-2508）。
- `_accumulate_usage` (L1180) — 累计 token 用量；被 `_complete_model_request`(L1156)、流式 usage chunk 处（L2305）调用。
- 流式分支要点：`_run_stream_logic` (L2203) 逐 chunk yield（L2232），累积 reasoning_content/content（L2240-2251），按 index 拼接 tool_call 增量（L2256-2277），finish_reason 或 usage-only chunk 判定流结束（L2294-2302）。

#### 4. 工具循环

- 非流式（`_run_non_stream_logic` L1998）：
  - L2011 判 `response.choices[0].message.tool_calls`；L2021 把 assistant 消息（OpenAI 对象）append 进 messages。
  - 每个 tool_call：记 `_current_tool_calls`/`_record_trace("tool_call")`（L2031-2032）→ `json.loads(arguments)`（L2040，失败发 LA-JSON 并以 role:tool 回填错误 L2058-2062）→ `_prepare_tool_call`（L2067 → L1276）→ `run_async_safely(self.tool_dispatcher.dispatch(...))`（L2091 → tools.py `AsyncToolDispatcher.dispatch` L295）→ 生成器响应逐 chunk 累加（L2105-2126）→ `_apply_after_tool_result`（L2144 → L1341）→ `_record_trace("tool_result")`（L2145）→ role:tool 消息回填 messages（L2151-2155）。
  - 无 tool_calls → `_apply_output_guardrails`（L2164）→ `model_response` trace（L2166）→ `_finish_run(success=True)`（L2171）→ return reply。
  - `finish` 工具特判：非流式 L2410-2413（累加 delta）、L2175-2177（直接 `_finish_run(stage="finish_tool")` 并 return）。
  - 下一轮：`_prepare_model_request`(L2180) → `create`(L2187)。
- 流式（`_run_stream_logic` L2203）：
  - 收集完 tool_calls 后逐个执行（L2321-2488）：yield 工具调用信息 dict（L2346）→ `_parse_tool_arguments`（L2355 → L3119）→ `_prepare_tool_call`（L2356）→ `run_async_safely(dispatch)`（L2376）→ 流式工具边执行边 yield（L2390-2407）→ 非流式工具 `_apply_after_tool_result`（L2418）→ yield `tool_output` dict（L2407/2429）。
  - `finish` 工具：L2410-2413 累加 delta、L2442-2447 `_finish_run`、L2487-2488 return。
  - `max_tool_iterations` 用尽：L2490-2508 `_finish_run` + yield 错误 + return。
  - 结果回填：构造 assistant dict（含 reasoning_content 与 tool_calls 数组，L2512-2533）＋逐条 role:tool 消息（L2536-2542）append 进 chat_params["messages"] → `_prepare_model_request`(L2546) → `create`(L2554) → break 进入下一轮 while。
- `_prepare_tool_call` (L1276) — 工具执行前总闸门（详见安全分组）；被 L2067、L2356 调用。
- `_process_runtime_tools` (L1378) — 运行时工具注册进主 registry 并重建 dispatcher（L1402）；被 `run`(L639) 调用。
- `load_tools` (L445) — 初始工具装载（字符串走 `ToolLoader.load_tool` L450）；被 `__init__`(L268)、`create_tool`(L3115) 调用。
- `get_tool` (L435) / `get_tools` (L392) / `validate_tools` (L398) — 对外查询/校验；被外部调用。
- `_parse_tool_arguments` (L3119) — 三级容错解析工具参数 JSON（直解→正则提取→手写状态机）；被 L2355 调用。
- `create_tool` (L3023) — LLM 生成 Python 工具代码写盘并自动加载（L3084 调模型、L3110 写文件、L3115 load_tools）；被外部调用（self_learning 场景）。

#### 5. 安全与治理

- 输入 guardrail：`run` L607 `guardrails.check_input`（GuardrailManager）。
- 工具 guardrail：`_apply_tool_guardrails` (L1244) → `guardrails.check_tool`(L1245)；被 `_prepare_tool_call`(L1325) 调用。
- 输出 guardrail：`_apply_output_guardrails` (L1352) → 先 after_model_response hook（L1353）再 `guardrails.check_output`（L1358）；仅被非流式 L2164 调用（流式不检查——见阅读陷阱）。
- `_prepare_tool_call` (L1276) 顺序：构造 CapabilitySpec（L1280-1289，UNSAFE_PYTHON_TOOL_NAMES 需沙箱）→ `_sandbox_available`（L1290 → L1286）→ `capability_registry.policy_engine.evaluate_sync(PolicyRequest)`（L1300 → capabilities.py）→ 记 policy.decision session 事件（L1306）→ 预算 `runtime.budget.consume(tool_calls=1)`（L1322）→ `_apply_tool_guardrails`(L1325) → `_run_hooks("before_tool_call")`（L1329）。
- `_apply_after_tool_result` (L1341) — after_tool_result hook，可改写/阻断工具输出；被 L2144、L2418 调用。
- `_run_hooks` (L964) — 统一 hook 执行器：构造 HookContext → `hooks.run`（hooks.py HookManager）→ 镜像 hook_decision/review 事件 → HOOK_BLOCK 记 hook_block trace；被 before_run(L589)、on_error(L1051)、after_run(L1052)、before_model_request(L1110)、before_tool_call(L1329)、after_tool_result(L1342)、after_model_response(L1353)、before/after_memory_retrieve(L1534,1557)、before_memory_write(L1615)、after_memory_write(L1692,1870)、before_memory_promote(L1762)、after_memory_promote(L1861)、on_handoff(L2631) 调用。
- `_notify_error` (L1082) — 非终止错误的 on_error 通知；被工具参数/guardrail/执行错误处（L2051,2074,2363,2458,2478）与 stream_retry（L2569）调用。
- 预算（BudgetManager，runtime.py）：`consume(model_calls=1)` L1118；`consume(tokens=...)` L1173；`consume(tool_calls=1)` L1322；`consume(seconds=...)` L1037。BudgetExceeded → "LA-BUDGET"（L1040,1120,1175,1324）。
- `_format_hook_error` (L1089) / `_format_guardrail_error` (L1238) — 统一错误码文案（LA-HOOK / LA-GUARDRAIL，errors.format_error_code）。
- review/approval：`run` 的 `approval_id` 参数（L498-499,544-545）只透传进 hook metadata；review 事件经 `_run_hooks` 的 `review_events` 落 trace（L989-992）。

#### 6. 记忆

- 读取调用点：`_retrieve_memory_with_hooks` (L1523) — before/after_memory_retrieve hook 包夹 `self.memory.retrieve(query, user_id)`（L1554，MemoryProtocol）；`_filter_memory_results`（L1576 → L1959，`memory_policy.allows_result`）过滤；被 `_add_memory_context`(L1477,1501) 调用。
- 写入调用点：`_store_memory_with_policy` (L1578) — before_memory_write hook（L1615）→ `memory_policy.allows_write`（L1633）→ 内部来源走 `_requires_memory_promotion`（L1677 → L1711）→ `_handle_memory_promotion_candidate`（L1678 → L1732）→ 否则 `_store_memory_record`（L1689 → L1943，按签名探测决定是否带 metadata 调 `self.memory.store`）→ after_memory_write hook（L1692）→ 指纹去重计数（L1700-1703）→ `memory_write` trace（L1704）。
- 候选晋升：`_handle_memory_promotion_candidate` (L1732) — 建 MemoryCandidate（L1744）→ upsert（L1757 → L1906）→ before_memory_promote hook（L1762）→ `memory_policy.allows_promotion`（L1791）→ `_apply_memory_promotion_decision`（L1792/手动 L433 → L1810，只有 promotes 才真正落库 L1849）。
- 公开 API：`promote_memory_candidate` (L409) 手动晋升/拒绝；`list_memory_candidates` (L402) 列出待审候选。
- mem0/shared_memory 分支：core.py 不直接 import mem0/shared_memory 模块；外部记忆统一以 MemoryProtocol（protocol.py）传入 `memory` 参数；capabilit 层再以 `MemoryProviderAdapter` 包装注册（L900）。
- 每次运行都会把用户 query 原样写入记忆（L1490-1496），检索结果注入的是 query 前缀而非 system prompt（L1521）。

#### 7. 会话与观测

- session 集成：`_begin_session_run`（L863，open_session/投影/turn 事件）、`_record_session_event` (L902)（session.append + runtime.session_store.save，异常记 `_session_store_error` 不打断主流程）。
- `_record_trace` (L932) — 双写枢纽：trace 事件类型映射 session 事件类型（L936-947：run_start→run.started、model_request→model.requested、tool_call→tool.requested、guardrail_block/hook_block→policy.blocked、handoff→handoff.requested、run_end→run.completed/failed 等），先 `_record_session_event` 再 `TraceRecorder.record`（L961）；被全类约 40 处调用。
- 对外会话 API：`get_session` (L789)、`export_session` (L794)、`replay_session` (L800)、`checkpoint_session` (L806 → runtime.checkpoint)、`fork_session` (L813 → runtime.fork)、`compact_session` (L821)、`pause/resume/cancel_session` (L846/849/852，只记事件)。
- 恢复：无独立 restore 方法——传 `session_id` 给 `run` 时由 `runtime.open_session`(L872) 从 SessionStore 取回已有会话并投影历史（L634）实现"恢复"；`replay_session` 可重放事件流。
- tracing：`TraceRecorder` 每次运行重建（L548-553，支持 parent_trace_id/run_group_id 嵌套归组）；`export_trace` (L1194)、`summarize_trace` (L1201)、`export_trace_to` (L1209)（转发 tracing.py 同名函数）。
- `_build_model_request_trace` (L1225) — 生成不含消息正文的请求摘要（model/stream/message_count/tools）；被 `_prepare_model_request`(L1122) 调用。
- capability 审计挂钩：`__init__` 把 `capability_registry.audit` 指到 `_record_session_event`（L340）。

#### 8. MCP

- `setup_mcp` (L462, async) — 保存 mcp_setting → `MCPClientManager(mcp_setting, self.tool_registry)`（L470）→ `register_mcp_tool()`（L471）把 MCP 工具注册进 ToolRegistry；被外部调用（须 await）。
- 调用路径：MCP 工具注册后与本地工具无异——经 `chat_params["tools"]` 暴露给模型，执行统一走 `self.tool_dispatcher.dispatch(name, args)`（L2091/L2376，tools.py AsyncToolDispatcher L295，其内部再路由到 MCP client）。core.py 中 `self.mcp_client` 仅在 setup_mcp 赋值，无其他直接调用点。

## LightSwarm 类

职责：极简多代理注册表（L3264-L3294）。仅保存 `agents: Dict[str, LightAgent]`（L3266），作为 handoff 的名字寻址容器，不管理调度。

- `__init__` (L3265) — 初始化空 agents 字典。
- `register_agent` (L3268) — 批量注册 agent；重名只打日志不覆盖（L3275-3277）；被外部调用。
- `run` (L3283) — 校验 agent 已注册（L3292）后以 `light_swarm=self` 调 `agent.run(query, light_swarm=self, stream=stream, **run_kwargs)`（L3294）；被外部调用。
- agent 间交接逻辑（实际在 LightAgent 侧）：`run` 传 light_swarm → `_handle_task_transfer` (L2589)：`_detect_intent` (L2605 → L2930，用主模型按 "transfer to {name}" 子串匹配意图 L2975-2977) → 目标校验（L2620）→ `on_handoff` hook 可改写 query/目标（L2631-2671）→ `_handle_task_transfer_stream` (L2702，`yield from target_agent.run(...)` 并透传 parent_trace_id/run_group_id L2731-2734) 或 `_handle_task_transfer_non_stream` (L2759，L2790) → 双侧 `_finish_run` 记 handoff 结果。
- `_transfer_to_agent` (L2980) — 旧版交接实现，当前主流程未调用（遗留，阅读陷阱之一）。

## 跨模块调用关系汇总

| 调用方(core.py:行号) | 被调模块.符号 | 说明 |
|---|---|---|
| `__init__` L198-199 | tools.ToolRegistry / ToolLoader | 工具注册表与加载器 |
| `__init__` L222, L1633, L1791, L1881 | protocol.MemoryPolicy（allows_write/allows_result/allows_promotion/write_fingerprint/scoped_user_id） | 记忆安全策略 |
| `__init__` L223; run L607 | guardrails.GuardrailManager / check_input | 输入闸门 |
| `_apply_tool_guardrails` L1245 | guardrails.GuardrailManager.check_tool | 工具闸门 |
| `_apply_output_guardrails` L1358 | guardrails.GuardrailManager.check_output | 输出闸门（仅非流式） |
| `__init__` L228; `_run_hooks` L986 | hooks.HookManager / HookContext.run | 生命周期钩子 |
| `__init__` L255 | logger.LoggerManager | debug 日志 |
| L450, L1390 | tools.ToolLoader.load_tool | 按名字加载工具 |
| L305, L1402 | tools.AsyncToolDispatcher(...) | 重建派发器 |
| L2091, L2376 | tools.AsyncToolDispatcher.dispatch (tools.py L295) | 工具执行（含 MCP） |
| L396, L710, L2330, L2851, L2921 | tools.ToolRegistry（get_tools/get_tools_str/filter_tools/function_info/validate_tools） | 工具 schema 与过滤 |
| `_initialize_clients` L350, L356 | litellm_client.LiteLLMClient | provider="litellm" 路由 |
| `_initialize_clients` L360-373 | langfuse.openai | tracetools 观测 |
| `_begin_session_run` L872; `run` L634 | runtime.AgentRuntime.open_session + session.SessionStore | 会话打开/恢复 |
| `_record_session_event` L918-925 | session.Session.append / runtime.session_store.save | session 事件落库 |
| `_begin_session_run` L879; `compact_session` L830 | session.ContextProjector().messages | 历史投影 |
| `_compact_model_context` L1132 | session.ContextCompactor.compact_to_budget | 预算压缩 |
| L243, L1132; `compact_session` L830 | session.ContextCompactor | 压缩器 |
| `_finish_run` L1037; L1118, L1173, L1322 | runtime.BudgetManager.consume（经 runtime.budget） | 时间/模型调用/token/工具调用预算 |
| L1038, L1119, L1174, L1323 | runtime.BudgetExceeded | 预算超限异常 |
| `checkpoint_session` L811; `fork_session` L819 | runtime.AgentRuntime.checkpoint / fork | 检查点与分叉 |
| L334-338 | runtime.AgentRuntime + CapabilityRegistry | v0.10 运行时装配 |
| `_register_builtin_providers` L895, L900 | capabilities.ToolProviderAdapter / MemoryProviderAdapter + CapabilityScope | 内置 Provider 注册 |
| `_prepare_tool_call` L1300 | capabilities.PolicyEngine.evaluate_sync(PolicyRequest) | 工具策略评估 |
| `_prepare_tool_call` L1280-1289 | capabilities.CapabilitySpec / CapabilityRisk | 工具能力描述 |
| `invoke_capability` L857 | capabilities.CapabilityRegistry.invoke | 通用能力调用 |
| `__init__` L264; run L668 | skills.SkillManager（discover_skills/get_skills_xml） | 技能发现与注入 |
| `__init__` L297 | skill_tools.create_skill_tools | 注册技能系统工具 |
| L470-471 | mcp_client_manager.MCPClientManager.register_mcp_tool | MCP 工具注册 |
| `_record_trace` L961; `run` L548 | tracing.TraceRecorder.record | 结构化 trace 记录 |
| `_complete_model_request` L1154; L1181; L2308 | tracing.normalize_usage | 用量规范化 |
| `summarize_trace` L1203; `export_trace_to` L1217 | tracing.summarize_trace / export_trace | 聚合与导出 |
| L1040, L1093, L1120, L1242, L1299, L1315, L1324, L2042 等 | errors.format_error_code | LA-* 错误码文案 |
| L739, L2190, L2467, L2557, L2680, L2740 | errors.format_lightagent_error | 异常包装 |
| `_format_run_result` L1422; `_stream_as_events` L1450-1462 | result.RunResult / StreamEvent | 返回对象 |
| `__init__` L273-279; L1286 | builtin_tools（safe_expression/upload_file_to_oss/execute_python_*、UNSAFE_PYTHON_TOOL_NAMES） | 内置工具与沙箱名单 |
| L1477 等经 self.memory | protocol.MemoryProtocol.retrieve / store（L1554, L1956-1957） | 外部记忆后端（mem0 等经此接入） |

## 关键数据结构

- `self.chat_params`（L690-716）：`{model, messages, stream, tools?, tool_choice?: "auto", session_id?(tracetools 时), ...metadata}`；每次 run 整体重建，messages 是可变列表，后续轮次在其上 append。
- messages 列表形态（混合 dict 与 OpenAI 对象）：
  - 初始：`[{"role":"system","content":system_prompt}] + history + [{"role":"user","content":query}]`（L692-693）。
  - 非流式工具轮：直接 append OpenAI 的 assistant 消息对象（L2021）＋ role:tool dict `{"role":"tool","tool_call_id","content"}`（L2058-2062、L2151-2155）。
  - 流式工具轮：手工构造 assistant dict `{"role":"assistant","content":"","reasoning_content":...,"tool_calls":[{"id","type":"function","function":{"name","arguments"}}]}`（L2512-2533，content 必须空串、reasoning_content 为 DeepSeek 兼容）＋ role:tool dict（L2536-2542）。
- tool_calls 形态：
  - 非流式：OpenAI 对象，访问 `tool_call.id / .function.name / .function.arguments`（L2025-2030）。
  - 流式累积器：`[{"name":"","arguments":"","index":i,"title":"","id":""}]`，arguments 按 index 分片拼接（L2264-2277）。
  - 对外记录 `_current_tool_calls`：非流式 `{"id","name","arguments"}`（L2026-2030）；流式 `{"name","title","arguments"}`（L2337-2341）。
- 流式 yield 的增量事件：工具调用开始 `{"name","title","arguments"}`（L2346）；工具输出 `{"name","title","output","latency_ms"}`（L2395-2403、L2419-2427）；错误 `{"name","title","error"}`（L2369、L2464、L2484）；其余为裸 `ChatCompletionChunk`（L2232）。
- StreamEvent（L1450-1462）：`type ∈ {error, tool_result, tool_call, event, content}` + data + trace_id；"[LA-" 开头字符串判为 error。
- RunResult（L1422-1430）：content / reasoning_content / tool_calls / usage / trace_id / trace / error。
- Session 事件类型（映射表 L936-947 及各调用点）：turn.started / message.received / model.requested / model.completed / model.failed / assistant.completed / tool.requested / tool.completed / policy.blocked / policy.decision（L1306）/ handoff.requested / run.started / run.completed / run.failed / error.recorded / trace.recorded / context.compacted（L1134）/ session.paused|resumed|cancelled（L846-853）/ memory 写入相关经 trace 双写。
- 记忆候选（L1744-1756）：MemoryCandidate{candidate_id, data, memory_user_id, original_user_id, source, scope, agent_name, trace_id, run_id, status, injectable, metadata}。
- hook 阶段全集（见第 5/6 分组）：before_run、before_model_request、before_tool_call、after_tool_result、after_model_response、on_handoff、before/after_memory_retrieve、before/after_memory_write、before/after_memory_promote、on_error、after_run。

## 阅读陷阱

1. 输出 guardrail 只在非流式路径生效（L2164 调 `_apply_output_guardrails`）；`_run_stream_logic` 从不检查输出，流式内容不经过 output_guardrails。
2. `max_tool_iterations` 只约束流式工具循环（L2491）；非流式的工具轮数由 `max_retry` 控制（L2009），未传时两者同值（L534）但语义不同。
3. `_run_stream_logic` 标注 `Generator[str,...]` 但实际 yield 的是 `ChatCompletionChunk` 对象和 dict（L2232 注释自认类型不匹配）；消费方必须自行判型，`_stream_as_events` 正是为此存在。
4. 消息列表混合类型：非流式 append 的是 OpenAI 消息对象（L2021），流式 append 的是手工 dict（L2512），且流式 assistant 的 content 必须是空字符串而非 None（L2514 注释）、须带 reasoning_content（DeepSeek 兼容）。
5. 记忆注入改写的是用户 query 而非 system prompt（L1521），且每次 run 都把原 query 写回记忆（L1490）——重复运行同一 query 会造成记忆膨胀（有 fingerprint 去重，L1700-1702）。
6. `_transfer_to_agent`（L2980）是遗留死代码，真实交接路径是 `_handle_task_transfer` → `_handle_task_transfer_stream/non_stream`；同理 `_build_context`/`_build_agent_memory`（L2801/L2818）已不被主流程调用。
7. `run_thought` 中 runtime_tools 的"临时注册表过滤"是空实现（L2844-2849、L2914-2918 直接 pass），运行时工具在 ToT 下不做过滤、原样返回（L2919）。
8. `_detect_intent` 的意图解析只是对模型输出做 `"transfer to {name}"` 子串匹配（L2975-2977），且这次意图判断调用模型（L2959）不经过 budget/hook 闸门。
9. `LightAgent.run` 会重置大量实例状态（traceid、chat_params、计数器，L537-570），同一实例并发/嵌套调用不安全；handoff 时目标 agent 用的是它自己的状态（trace 通过 parent_trace_id 关联，L2731）。
10. `enable_unsafe_python` 只负责注册工具；真正执行还需在 capability registry 挂 sandbox Provider（L1286-1299，否则 LA-SANDBOX 拒绝）。

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
