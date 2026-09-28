# 源码知识库 03：工作流 / 运行时 / 会话 / 协议 / 共享记忆

> 基于 fork 工作树（v0.10 系）实读行号；行号均来自真实文件，非估算。
> 覆盖：LightAgent/flow.py、runtime.py、session.py、protocol.py、shared_memory.py。

---

# LightFlow 工作流编排（LightAgent/flow.py，共 1039 行）

## 模块概览
flow.py 提供**确定性（deterministic）多 Agent 工作流执行器**：用户把若干持有 `run()` 方法的 Agent（通常是 LightAgent 实例）以 DAG 方式注册为 step，`run()` 按拓扑序逐个执行，带重试、超时、降级（fallback Agent）、人工审批门、hook 拦截、trace 记录与 JSON 检查点持久化；支持 `resume`（从检查点续跑）与 `rerun_step`（重跑某步及其全部下游）。它不自己做调度线程/事件循环，是同步顺序执行 + `asyncio.to_thread` 包装的异步入口。

## 类与符号清单
- FLOW_PENDING/RUNNING/SUCCESS/FAILED/SKIPPED/WAITING_APPROVAL (L32-37)：step/流程状态常量字符串。
- LightFlowStep (L40-55)：单个 step 的定义 dataclass——name、agent、depends_on、query（str 或 Callable）、tools、max_retry(默认1)、timeout、fallback_agent、cancel_if、requires_approval、approval_handler、metadata。
- LightFlowStepResult (L58-79)：一个 step 的执行结果快照——content、error、attempts、trace、status、started/ended/duration_ms、input/output_summary、retry_count、used_fallback、approval_request_id/decision；`__str__` 返回 content (L78)。
- LightFlowResult (L82-99)：整次 run 的结果——content（最后一个成功 step 的输出）、steps 列表、trace_id、trace、error、run_id、status；`success` property (L94) = error 为 None 且 status==success。
- JsonLightFlowStore (L102-129)：JSON 文件检查点存储，每个 run_id 一个 `<safe_run_id>.json`；`_path` (L125) 过滤非法字符。
- LightFlow (L132-1039)：工作流主体类。

## 关键方法
- `step` (L144) — 注册一个 step 并返回 self 以支持链式调用；校验：名字非空/唯一 (L161-164)、agent 必须有 run() (L165)、fallback_agent 必须有 run() (L167)、max_retry>=1 (L169)、timeout>0 (L171)。调用方：用户代码/示例 example/10.lightflow.py:36。它调用：LightFlowStep 构造 (L175)。
- `validate` (L192) — DAG 校验：未知依赖→error (L204)、孤立 step→warning (L206)、DFS 找环 (L209-226)；strict=True 时 warning 升级为 error (L228)。调用方：`_ordered_steps` (L810)、用户自查。
- `run` (L236) — 一次完整执行入口；校验 result_format∈{object,str,dict} (L248)，生成 run_id（uuid4.hex，L257），取拓扑序后交给 `_execute` (L251)。调用方：用户代码、`arun`（经线程）。
- `arun` (L262) — `asyncio.to_thread(self.run, ...)`，把同步 run 丢进线程避免阻塞事件循环。
- `resume` (L266) — 从检查点续跑：读 run 记录 (L277)、恢复审批决定 (L280)、发 on_resume hook (L281)、把 status==success 的 step 装入 initial_completed (L282-286)、只执行未成功的 step (L287)。
- `rerun_step` (L300) — 重跑指定 step 及其全部下游：`_downstream_steps` (L321) 计算闭包，清除下游的审批决定 (L322-324)，下游之外的 success step 作为 initial_completed (L325-329)，仅执行下游集合 (L330)。
- `get_run` (L343) — 先查内存 `_records`，未命中再查 store (L345-348)。
- `approve` (L357) — 落一笔人工审批决定：要求该 step 状态为 waiting_approval 且有 approval_request_id (L373-377)，归一化决定后写进内存 `_approval_decisions` 与记录的 `approvals` 字段并持久化 (L378-388)。调用方：外部审批 UI/用户。
- `_execute` (L391) — 核心主循环（详见"关键机制细节"）。调用方：run (L251)、resume (L288)、rerun_step (L331)。
- `_run_step` (L667) — 单 step 的重试+降级执行：attempts 从 1 到 max_retry 循环调 `_call_agent` (L679-688)，失败后若配了 fallback_agent 再调一次 (L711-724)；结果归一为 LightFlowStepResult。
- `_call_agent` (L743) — 组装 `agent.run(query, tools=..., stream=False, user_id=..., metadata=..., result_format="object", trace=..., parent_trace_id=..., run_group_id=...)` 并调用 (L765)；有 timeout 时用 `ThreadPoolExecutor(max_workers=1)` + `future.result(timeout)` 实现超时 (L766-772)。调用方：`_run_step` (L680、L712)。它调用：agent.run → 即 LightAgent.run（core.py:480）。
- `_run_flow_hook` (L774) — 构造 HookContext 并跑 `self.hooks.run(context)` (L797)，把 decision.metadata 里的 hook_events/review_events 写进 recorder，HOOK_BLOCK 记 hook_block 事件 (L799-806)。调用方：`_execute`（before_flow_step L434、on_approval_required L484、after_flow_step L598）、resume (L281)、rerun_step (L320)。它调用：hooks.HookManager.run（hooks.py:101）。
- `_ordered_steps` (L809) — 先 validate（有 error 直接 raise，L810-812），再对依赖做 DFS 后序遍历得到"依赖在前"的执行序 (L817-826)。调用方：run (L250)、resume (L287)、rerun_step (L316、L330)、_execute (L407)。
- `_build_step_query` (L829) — step 输入构造：callable query → `step.query(context)`（TypeError 时退回 `(original_query, context)` 两参签名，L831-835）；字符串 query 原样用；无 query 无依赖→透传原始 query；有依赖→original_query + "\nPrevious step outputs:\n" + 各依赖输出 (L838-844)。
- `_normalize_agent_result` (L846) — RunResult → (content, error, trace)；普通对象 str() 后若以 `[LA-` 前缀开头则视为错误文本 (L850-852)。
- `_format_result` (L854) — 按 result_format 返回对象/str/dict (L855-869)。
- `_checkpoint` (L871) — 构造运行记录：run_id、query、status、error、steps（未跑的 step 补 pending 占位，L882-888）、approvals、updated_at；写内存 `_records` 并落 store (L902-904)。
- `_remaining_skipped_results` (L906) — 某 step 失败后，把所有直接依赖失败者、或依赖已被执行 step 的未跑 step 生成 skipped 结果 (L917-918)。
- `_check_approval` (L932) — 审批门：未要求审批→直接 approve (L940)；已有持久化决定→复用 (L942-944)；无 handler→pending (L946)；有 handler→调用 `step.approval_handler(step, context)`，异常→reject，False/str/dict 语义各异 (L949-970)。调用方：_execute (L468)。
- `_coerce_approval_decision` (L972) — 把 bool/str/dict/None/ApprovalDecision 统一归一为 ApprovalDecision（True/None→approve；False/str→reject；dict 按 action/approved/allowed 解释）。
- `_restore_approval_decisions` (L1004) — 从 run 记录的 `approvals` 字典与各 step 的 approval_request_id 重建内存审批状态（resume/rerun 用）。
- `_downstream_steps` (L1016) — 不动点迭代求"该 step 的全部传递下游"集合。
- `_summarize` (L1036) — 超 240 字符截断加 "..."（作为 input/output_summary）。

## 关键机制细节
### step 定义 → 注册 → 校验
1. 定义：`flow.step("name", agent=..., depends_on=[...], query=..., ...)`（L144-190），参数全部存进 LightFlowStep（L40）；注册时只做本地参数校验，**不做 DAG 校验**。
2. 依赖即字符串名字列表（L46），校验时才解析（validate L201-205 查未知依赖，L209-226 DFS 查环）。
3. 执行序：`_ordered_steps`（L809）每次 run/resume/rerun 都重新 validate + 重新拓扑排序，因此注册后 DAG 固定但执行序是运行时算的；第一个校验 error 直接 raise。

### 单个 step 的完整执行生命周期（在 `_execute` L391 主循环内）
1. **取消/条件跳过**：`self._cancelled or step.cancel_if(context)` → 生成 skipped 结果并 checkpoint (L427-431)。
2. **构造输入**：`_build_step_query` (L433)。
3. **before_flow_step hook** (L434-444)：可返回 HOOK_BLOCK（→skipped，L445-448）或 payload 里带 `query` 改写输入 (L450-451)。
4. **审批门** (L453-576)：构造 ApprovalRequest（request_id 复用持久化的，否则新生成，L455-458）→ `_check_approval` (L468)：
   - pending → 记 request_id、发 on_approval_required hook、生成 waiting_approval 结果、checkpoint 后 **break 退出循环**（流程以 waiting_approval 状态"结束"，等待外部 `approve()` + `resume()`，L482-518）；
   - reject → skipped 结果、状态 FLOW_FAILED、break (L519-537)；
   - edit → 用 decision.arguments["query"] 替换 step_query 继续执行 (L538-541)；
   - respond → **不调用 agent**，直接把 decision.response 作为本 step 成功结果 (L542-576)。
5. **执行**：step_start trace (L578) → `_run_step` (L586)：
   - 重试循环（max_retry 次，L679）；每次 `_call_agent`（无 timeout 直接调；有 timeout 用单线程池等待，L764-772）；
   - 超时→error=`step ... timed out`、content 加 `[LA-FLOW-TIMEOUT]` 前缀 (L690-692)；
   - 全部重试失败且有 fallback_agent→再调一次 fallback，`used_fallback=True` (L711-740)。
6. **after_flow_step hook** (L598) → 写入 context.steps/outputs (L609-610) → step_end trace (L613) → checkpoint (L626)。
7. **失败终止**：step 有 error → 状态 FLOW_FAILED、`_remaining_skipped_results` 补齐被连坐的 step (L637)、再 checkpoint、记录 flow_end、返回 (L634-651)。
8. 全部成功 → flow_end (L653)、按 result_format 返回 (L654-665)。

### 检查点（checkpoint）数据形态
`_checkpoint` (L871-904) 产出 dict：`{run_id, query, status, error, steps:[LightFlowStepResult.asdict()...], approvals:{step_name: ApprovalDecision.to_dict()}, updated_at}`；`steps` 里未执行的 step 以 `attempts=0, status="pending"` 占位补齐 (L882-888)。存内存 `_records` + 可选 JsonLightFlowStore（每 run 一个 JSON 文件）。resume/rerun 用 `_step_result_from_dict` (L1031) 按数据类字段过滤反序列化。

### 审批生命周期
定义 requires_approval=True (L53) → 执行时 pending 挂起 → 外部调 `approve(run_id, step_name, decision)` (L357) 把决定写进 `_approval_decisions[(run_id, step)]` 并持久化到记录的 `approvals` → `resume()` 时 `_restore_approval_decisions` (L1004) 恢复 → 重跑该 step 时 `_check_approval` 直接复用持久化决定 (L942-944)，不再询问。

### context 数据流
`context = {"input": query, "steps": {name: LightFlowStepResult}, "outputs": {name: content}}` (L410-414)；resume 时 initial_completed 先回填 (L416-419)。callable query 拿到整个 context（示例里用 `context['outputs']['research']`）；无显式 query 的 step 自动拼依赖输出。

### trace
`TraceRecorder(enabled=trace, trace_id=uuid4, parent_trace_id, run_group_id)` (L406)；事件类型：flow_start (L408)、hook_decision/hook_block (L799-806)、approval_* (L475)、step_start (L578)、step_end (L613/561)、flow_end (L639/653)。parent_trace_id=flow 的 trace_id 传给每个 agent.run，实现 agent trace 挂到 flow trace 下 (L591)。

## 与其他模块的关系
| 本模块符号:行号 | 对方模块.符号 | 说明 |
|---|---|---|
| LightFlowStep.agent (L45)；_call_agent (L765,767) | core.LightAgent.run（core.py:480） | step 的 agent 通常为 LightAgent 实例，flow 以 `result_format="object"` 调 run 拿 RunResult |
| _normalize_agent_result (L848) | result.RunResult（result.py:15） | 统一步骤返回类型：content/error/trace 三元组 |
| LightFlow.__init__ (L138)；_run_flow_hook (L797) | hooks.HookManager.run（hooks.py:101）、HOOK_BLOCK（hooks.py:20） | flow 级 hook 拦截（before/after_flow_step、on_resume、on_rerun、on_approval_required） |
| _execute 内 ApprovalRequest (L453)、_check_approval (L970) | review.ApprovalRequest（review.py:38）、ApprovalDecision（review.py:66）及 APPROVAL_* 常量（review.py:19-23） | 人工审批模型与四种决定（approve/reject/edit/respond） |
| _execute recorder (L406)；recorder.record (L798-806) | tracing.TraceRecorder（tracing.py:229） | flow 全程 trace，parent_trace_id 串联子 agent trace |
| JsonLightFlowStore.save_run (L109) | 自身 JSON 文件 | 检查点持久化（独立于 session.py 的 SessionStore 体系） |
| LightAgent/__init__.py:213 `"LightFlow"` | 包导出 | 公开 API |
| 示例 example/10.lightflow.py:35-60 | LightFlow().step(...) 链式注册 | 官方用法：research→write→review 依赖链、callable query 读 context['outputs'] |

## 阅读陷阱
1. `_ordered_steps` 是 DFS 后序（依赖先执行），**不是注册顺序**；且每次 run/resume 都重新 validate，注册顺序错误不会提前报错，到 run 时才 raise（L810-812）。
2. 审批 pending 时流程是 **break 半途退出**而非阻塞等待（L518）；"等待人工"是靠状态 waiting_approval + 检查点 + 外部 approve/resume 组合实现的，容易误以为有挂起协程。
3. timeout 用 `ThreadPoolExecutor` + `future.result(timeout)` 模拟（L766-772）：超时后 `future.cancel()` 只能取消未开始的任务，**agent.run 仍会在后台线程继续跑完**，只是结果被丢弃。
4. `_normalize_agent_result` 把任何以 `[LA-` 开头的字符串当作错误（L851）；Agent 正常输出若恰好以该前缀开头会被误判为失败并触发重试/fallback。
5. 无显式 query 且有依赖时，输入是 `original_query + 全部依赖输出` 拼接（L841-844），不是只有依赖输出；approval respond 分支会完全跳过 agent 执行（L542-576）。
6. `resume` 重跑所有非 success 的 step，`rerun_step` 只重跑指定 step 及其传递下游（含清空下游已有审批决定，L322-324）——两者检查点语义不同。

## 高频符号中文短语表
| 符号 | 中文短语 |
|---|---|
| LightFlowStep (L40) | 工作流单步定义（agent+依赖+重试/超时/审批） |
| LightFlowStepResult (L58) | 单步执行结果快照（含耗时与审批信息） |
| LightFlowResult (L82) | 整次流程结果（content+steps+trace） |
| LightFlow (L132) | 确定性 DAG 工作流执行器 |
| JsonLightFlowStore (L102) | 每 run 一 JSON 文件的检查点存储 |
| step (L144) | 链式注册一个工作流步骤 |
| validate (L192) | DAG 校验（未知依赖/孤立项/环） |
| run (L236) | 按拓扑序同步执行全流程 |
| arun (L262) | 线程池包装的异步执行入口 |
| resume (L266) | 从检查点续跑未成功步骤 |
| rerun_step (L300) | 重跑指定步骤及其全部下游 |
| approve (L357) | 落一笔人工审批决定供续跑复用 |
| _execute (L391) | 主循环：hook→审批→执行→checkpoint |
| _run_step (L667) | 单步重试与 fallback 降级执行 |
| _call_agent (L743) | 带超时调用 agent.run |
| _ordered_steps (L809) | 校验并生成依赖优先的执行序 |
| _build_step_query (L829) | 构造步骤输入（callable/依赖拼接） |
| _checkpoint (L871) | 写运行记录（内存+存储） |
| _check_approval (L932) | 审批门判定（pending/reject/edit/respond） |
| _downstream_steps (L1016) | 求传递下游闭包集合 |

---

# AgentRuntime 运行时管家（LightAgent/runtime.py，共 843 行）

## 模块概览
runtime.py 是"长任务运行时控制平面"：以**Session 事件日志为唯一持久化介质**，把收件箱（AgentInbox）、目标（GoalManager）、预算（BudgetManager）、后台任务（JobManager）、子代理（SubagentManager）、进度停滞检测（ProgressTracker）打包进 AgentRuntime。所有组件自身只持内存状态，每次变更通过 event_sink 回调写进 Session 事件并落存储；`open_session` 时按事件回放恢复各组件状态。注意：AgentRuntime **不驱动** LightAgent 的对话循环，它只是被 LightAgent 持有的状态/治理管家。

## 类与符号清单
- InboxMessageType (L17-21)：枚举 followup/steering/context/approval 四种收件箱消息类型。
- InboxMessageStatus (L24-28)：枚举 pending/claimed/completed/rejected。
- InboxMessage (L31-61)：收件箱消息 dataclass（message_id、content 深拷贝、correlation_id、metadata）；to_dict (L43) 枚举转字符串、from_dict (L49)。
- AgentInbox (L64-161)：有序、幂等（按 message_id 去重）收件箱，所有变更发 `inbox.*` 事件。
- GoalStatus (L164-169)：枚举 pending/active/completed/blocked/cancelled。
- Goal (L172-203)：目标 dataclass（objective、acceptance_criteria、parent_goal_id、evidence、blocker）；to_dict (L185)、from_dict (L190)。
- GoalManager (L206-286)：目标 CRUD + 状态机，事件 `goal.created/updated/completed/blocked/cancelled`。
- BudgetLimits (L289-300)：frozen dataclass，model_calls/tool_calls/tokens/seconds/cost 五维上限（None=不限）；__post_init__ 拒绝负值 (L297)。
- BudgetUsage (L303-312)：五维已用量计数器。
- BudgetExceeded (L315-320)：超限异常，携带 dimension/limit/used。
- BudgetManager (L323-375)：预算消耗与校验，事件 `budget.consumed` / `budget.exhausted`。
- ProgressState (L378-384)：steps、unchanged_steps、repeated_tool_calls、last_output、last_tool_signature。
- ProgressTracker (L387-429)：检测"输出无变化"与"重复工具调用"两类停滞，事件 `progress.stalled`。
- JobStatus (L432-438)：枚举 pending/running/success/failed/cancelled/interrupted。
- JobRecord (L441-458)：后台任务记录；to_dict (L455)。
- JobManager (L461-581)：可取消的后台 asyncio 任务管理，事件 `job.created/started/completed/cancelled/failed/output/interrupted`。
- SubagentRecord (L584-593)：子代理登记（agent_id、parent_agent_id、depth、permissions、persistent、status）。
- SubagentManager (L596-711)：子代理注册/运行/树状展示/跨代理发消息，事件 `subagent.created/started/completed/failed`。
- AgentRuntime (L714-820)：总管家，聚合以上全部 + Session/CapabilityRegistry。

## 关键方法
- `AgentInbox.enqueue` (L71) — 幂等入队：同 message_id 已存在则直接返回旧消息 (L81-83)；content/metadata 深拷贝隔离；发 `inbox.enqueued`。调用方：JobManager._execute（runtime.py:517）、SubagentManager.send（runtime.py:696）、外部 steer。
- `AgentInbox.claim_next` (L103) — 按序取第一条 pending；STEERING 类型仅在 safe_boundary=True 时可取 (L107-108)；置 claimed 并发 `inbox.claimed`。
- `AgentInbox.complete` (L115) — 仅 claimed 可完成（L119-120），已完成幂等返回 (L117)；发 `inbox.completed`（含 result）。
- `AgentInbox.restore` (L140) — 回放 session.events 中所有 `inbox.*` 事件，取每个事件 data["message"]，按 message_id 去重后按 created_at 排序重建列表 (L142-151)。调用方：AgentRuntime.open_session（runtime.py:754）。
- `GoalManager.create` (L211) — 校验 objective 非空、父目标存在 (L219-222)，发 `goal.created`。
- `GoalManager._transition` (L270) — 状态迁移守卫：terminal（completed/cancelled）目标不得再迁移 (L272-273)；发对应事件。
- `GoalManager.restore` (L259) — 回放 `goal.*` 事件，**后写覆盖** by_id（L260-268），恢复为每个 goal 的最后已知状态。
- `BudgetManager.consume` (L333) — 先构造 candidate 用量，任一维超限→发 `budget.exhausted` 并 raise BudgetExceeded（**不更新 usage**，天然回滚，L349-358）；通过则提交 usage 并发 `budget.consumed` (L359-362)。调用方：core.py:1014（seconds）、core.py:1082（model_calls）、core.py:1137（tokens）、core.py:1294（tool_calls）。
- `BudgetManager.restore` (L370) — 倒序找最近一条 `budget.consumed` 事件，直接取其 usage 快照 (L371-375)。
- `ProgressTracker.record` (L402) — 每步记录输出 repr 与 (tool, arguments) repr 签名；连续不变计数达到阈值→发 `progress.stalled` (L414-417)；`stalled` property (L420) 汇总判断。
- `JobManager.start` (L474) — **要求运行中的事件循环**（`asyncio.get_running_loop()`，L482）；create_task 执行 `_execute`，发 `job.created`。
- `JobManager._execute` (L489) — 置 running→执行（callable 或 awaitable 均可，L495-497）→success/cancelled/failed 各发事件；finally 里向 inbox 塞一条 CONTEXT 类型"任务完成通知" (L516-522)。
- `JobManager.wait` (L524) / `cancel` (L535) / `emit_output` (L541) — 等待结果 / 取消任务 / 流式产出登记。
- `JobManager.mark_interrupted` (L557) — 把 PENDING/RUNNING 的记录改成 INTERRUPTED（open_session 恢复后调用，表示上次进程中断）。
- `JobManager.restore` (L564) — 回放 `job.*` 事件重建记录；`self._tasks = {}`（任务本体不可恢复，只恢复档案）。
- `SubagentManager.register` (L612) — 校验数量上限 (L623)、深度=父深度+1 且不超 max_depth (L625-627)；权限=父权限 `PermissionSet.narrow(allowed=..., max_risk=...)` 收窄 (L629-633)；发 `subagent.created`。
- `SubagentManager.run` (L648) — 并发上限检查 (L652)；优先 `agent.arun`，无则 `asyncio.to_thread(agent.run)` (L658-662)；成功/失败发事件并维护 `_running` 计数。
- `SubagentManager.send` (L689) — 向子代理的 `runtime.inbox.enqueue` 投递消息；要求目标 agent 已 open_session（L694-695）。
- `AgentRuntime.__init__ (L717)` — 建默认 InMemorySessionStore 与 CapabilityRegistry (L726-727)，创建 inbox/goals/budget/jobs/subagents/progress 并把 `self._append` 作为统一 event_sink 注入 (L730-735)。调用方：core.py:332。
- `AgentRuntime.open_session` (L737) — get-or-create Session（新建才 append `session.started`，L745-749）；绑定 context（session_id/agent_id/user_id，L751-753）；依次 inbox/goals/budget/jobs restore (L754-757)；`jobs.mark_interrupted()` (L758)；返回 Session 深拷贝。调用方：core.py:861（`_begin_session_run`）。
- `AgentRuntime.checkpoint` (L761) — session.checkpoint 打点 + 落存储。调用方：core.py:800。
- `AgentRuntime.fork` (L767) — session.fork 出新会话并 create 进 store。调用方：core.py:808。
- `AgentRuntime.snapshot` (L777) — 汇总 runtime_id、session.to_dict、replay、inbox、goals、budget（limits/usage/remaining）、jobs、progress 成一个可序列化 dict。
- `AgentRuntime.pause/resume/cancel/continue_run` (L794-804) — 仅追加 `session.paused/resumed/cancelled/continued` 事件（语义标记，不改变执行流）。
- `AgentRuntime._append` (L806) — 统一事件出口：`session.append(event_type, data, turn_id, run_id, agent_id)` + `session_store.save` (L808-815)；是所有管理器 event_sink 的落点。

## 关键机制细节
### "事件即持久化"架构
每个管理器构造时接收 `event_sink: Callable[[str, dict], Any]`（如 AgentInbox.__init__ L67、GoalManager L207、BudgetManager L324、JobManager L464、SubagentManager L596、ProgressTracker L390）。AgentRuntime.__init__ 把自己的 `_append` 统一注入 (L730-735)。于是：内存状态变更 → _append → Session.append + store.save。**没有任何组件直接写文件/数据库**，持久化完全由 Session 事件日志承载。

### 恢复（restore）回放流程（open_session L737-759）
1. `session_store.get(session_id)`；没有则新建 Session 并 append `session.started`。
2. `inbox.restore(session)`：过滤 `inbox.*` 事件，逐条取 `data["message"]` dict → InboxMessage.from_dict → 按 message_id 去重（保留最后一次状态）→ 按 created_at 排序 (L142-151)。
3. `goals.restore(session)`：过滤 `goal.*`，取 `data["goal"]` → Goal.from_dict → 后写覆盖 (L260-268)。
4. `budget.restore(session)`：**倒序**找第一条 `budget.consumed`，usage 直接取事件里的快照 (L371-375)。
5. `jobs.restore(session)`：回放 `job.*` 事件重建 JobRecord 档案；`_tasks` 清空（协程本体不恢复）(L564-577)；随后 `mark_interrupted()` 把未完结任务标为 INTERRUPTED (L557-562)。
6. 注意：恢复已存在 session 时**不**再 append session.started（仅新建时 L748）。

### 事件类型清单（本模块产出）
`inbox.enqueued/claimed/completed/rejected`；`goal.created/updated/completed/blocked/cancelled`；`budget.consumed/exhausted`；`progress.stalled`；`job.created/started/completed/cancelled/failed/output/interrupted`；`subagent.created/started/completed/failed`；`session.started/paused/resumed/cancelled/continued/checkpointed(由 Session.checkpoint 发)`。

### Inbox 消息语义
四种类型（L17-21）：followup（追问）、steering（中途转向，仅安全边界可 claim，L107-108）、context（上下文补充，JobManager 完成回执也走这里，L517-522）、approval（审批请求）。状态机 pending→claimed→completed/rejected。入队幂等靠显式 message_id（调用方自己保证语义）。

### 与 LightAgent 的实际接线（core.py 侧）
- core.py:332-337 创建 AgentRuntime 并把 `runtime.registry` 暴露为 `capability_registry`。
- core.py:849/873-875 读写 `runtime.context`（RuntimeContext，capabilities.py:76）的 turn_id/run_id。
- core.py:891-906 `_record_session_event` **绕过 runtime._append**，直接 `session.append + session_store.save`（带异常兜底，错误存 `_session_store_error`）——所以 Agent 对话产生的事件（turn.started、message.received、model.requested 等）与 runtime 管理器事件共用同一个 Session。
- core.py:1014/1082/1137/1294 在模型调用、工具调用、token 统计后调 `runtime.budget.consume(...)`。

## 与其他模块的关系
| 本模块符号:行号 | 对方模块.符号 | 说明 |
|---|---|---|
| AgentRuntime (L714) ← core.py:332 | core.LightAgent.__init__ | LightAgent 持有 runtime，作为会话/预算/子代理管家 |
| open_session (L737) ← core.py:861 | core.LightAgent._begin_session_run | 每次 run 前 open/复用 Session 并恢复管理器状态 |
| checkpoint (L761) / fork (L767) ← core.py:800 / core.py:808 | core.LightAgent.checkpoint_session / fork_session | 对外暴露的会话打点与分叉 API |
| session_store (L726, 默认 InMemorySessionStore) | session.SessionStore（session.py:377） | 会话持久化后端注入点 |
| _append (L806) | session.Session.append（session.py:216）、session_store.save | 全部管理器事件的落盘路径 |
| InboxMessage/Goal/_utc_now (L14) | session.SessionEvent、session._utc_now（session.py:31） | 复用 UTC 时间戳与事件载荷形态 |
| SubagentManager.register (L630) | capabilities.PermissionSet.narrow（capabilities.py:234） | 子代理权限收窄 |
| AgentRuntime.__init__ (L727) | capabilities.CapabilityRegistry（capabilities.py:370）、RuntimeContext（capabilities.py:76） | 能力注册表与运行时上下文 |
| SubagentManager.run (L658-662) | agent.arun / agent.run | 子代理执行入口（通常是 LightAgent） |
| core.py:1014/1082/1137/1294 | BudgetManager.consume (L333) | LightAgent 主循环在模型/工具调用处扣预算 |
| LightAgent/__init__.py:293 `"AgentRuntime"` | 包导出 | 公开 API |

## 阅读陷阱
1. AgentRuntime **不驱动**对话/工作流：它不调用 agent.run；LightAgent 的执行循环在 core.py，runtime 只是状态与治理容器。名字里的 "Runtime" 容易让人以为有调度循环。
2. restore 是"事件回放重建最后状态"，不是读快照；Job 只恢复档案不恢复协程（`_tasks={}`，runtime.py:577），恢复后立即把未完结任务标 INTERRUPTED (L558)。
3. `BudgetManager.consume` 超限时 usage **不更新**（candidate 校验失败即抛，L349-358），但 `budget.exhausted` 事件已发出——事件日志里可能出现"超限但用量未变"的序列。
4. `claim_next(safe_boundary=True)` 默认可取 STEERING 消息；safe_boundary=False（"不在安全边界"）时才跳过 steering（L107-108）——参数名读反极易搞错语义。
5. `JobManager.start` 依赖 `asyncio.get_running_loop()`（L482），在无事件循环的同步上下文直接 RuntimeError；同步场景需 `asyncio.run` 包裹或另行处理。
6. core.py 的事件写入走自己的 `_record_session_event`（core.py:891，含 try/except 兜底），不走 runtime._append；两条写入路径并存，排错时要分开看。

## 高频符号中文短语表
| 符号 | 中文短语 |
|---|---|
| AgentRuntime (L714) | 聚合会话/收件箱/目标/预算/任务/子代理的管家 |
| AgentInbox (L64) | 幂等有序收件箱（事件即持久化） |
| InboxMessage (L31) | 四类收件箱消息实体 |
| GoalManager (L206) | 目标状态机（created/updated/blocked…） |
| BudgetManager (L323) | 五维预算消耗与超限熔断 |
| BudgetExceeded (L315) | 预算超限异常（带维度与用量） |
| ProgressTracker (L387) | 输出停滞与重复工具调用检测 |
| JobManager (L461) | 可取消后台协程的任务档案 |
| SubagentManager (L596) | 子代理注册/限深/限并发/权限收窄 |
| open_session (L737) | 打开或复用会话并回放恢复各管理器 |
| _append (L806) | 统一事件出口（写 Session 并落盘） |
| checkpoint (L761) | 会话打点并保存 |
| fork (L767) | 到指定序列为止分叉新会话 |
| snapshot (L777) | 全量运行时状态汇总 |
| claim_next (L103) | 按序领取下一条收件箱消息 |

---

# 会话存储与恢复（LightAgent/session.py，共 842 行）

## 模块概览
session.py 实现**事件溯源（event-sourced）的会话体系**：Session 是只追加的 SessionEvent 日志（严格连续 sequence），在其上提供检查点、分叉、重放统计；三种 SessionStore（内存 / JSONL 文件 / SQLite）负责持久化；ContextProjector 从事件投影出模型消息列表与 trace 视图；ContextBudget + ContextCompactor 做**无依赖的确定性上下文压缩**（超长工具结果外溢 + 按条数/预算裁剪 + 可选摘要）。模块自述 "dependency-free"，仅用标准库。

## 类与符号清单
- SESSION_SCHEMA_VERSION (L18)：当前 schema 版本（=1），迁移与校验的基准。
- _SENSITIVE_KEYS (L19-28)：api_key/token/password 等敏感字段名集合（序列化时 redact）。
- _utc_now (L31)：UTC ISO 时间戳工具（被 runtime.py 复用）。
- SessionMigrationRegistry (L35-77)：按 from_version 逐版升级 Session/事件 payload 的迁移注册表；`session_migrations` (L80) 为模块级单例。
- _json_safe (L83-100)：递归转 JSON 安全值；敏感 key→"[redacted]" (L85-86)；dataclass→asdict；有 to_dict 就调用；set/tuple→list；其余 repr()。
- SessionEvent (L103-164)：一条不可变事实。字段：type、session_id、data、event_id(uuid)、timestamp、sequence、schema_version、turn_id、step_id、run_id、agent_id、parent_event_id。`__post_init__` 校验 type/session_id/sequence 并对 data 做 _json_safe 清洗 (L120-129)；to_dict (L131)；from_dict (L147)。
- SessionCheckpoint (L167-177)：检查点（checkpoint_id、sequence、label、metadata）。
- SessionReplay (L180-191)：重放统计结果（completed/incomplete/failed turns、last_sequence/type）。
- Session (L194-374)：追加式会话聚合根。
- SessionStore (L377-391)：存储协议（typing.Protocol）：create/get/save/list/delete 五方法。
- InMemorySessionStore (L394-432)：线程安全内存实现。
- JsonlSessionStore (L435-518)：每会话一个 .jsonl 文件。
- SqliteSessionStore (L521-641)：标准库 SQLite 实现（WAL、外键级联）。
- ContextProjector (L644-706)：从事件投影 messages / model_request / trace。
- CompactionResult (L709-714)：压缩结果（messages、removed_count、summary、spilled）。
- ContextBudget (L717-738)：frozen 预算估算器（chars_per_token=4 估算 token）。
- ContextCompactor (L741-823)：确定性消息裁剪与摘要压缩。

## 关键方法
- `Session.append` (L216) — 追加事件：sequence 自动取 `next_sequence`（最后一条+1，L212-214），updated_at 同步为事件时间戳。调用方：runtime.py:808（AgentRuntime._append）、core.py:896（_record_session_event）、Session.checkpoint (L270)、Session.fork (L292,296,310)。
- `Session.append_event` (L243) — 追加**外部构造**的完整事件：session_id 必须一致、sequence==0 自动补位、否则必须精确等于期望值、event_id 不得重复 (L244-252)。
- `Session.page` (L257) — 按 sequence 游标分页读事件。
- `Session.checkpoint` (L262) — 生成 SessionCheckpoint 并向自身 append 一条 `session.checkpointed` 事件（检查点本身也是事件）。调用方：runtime.py:763。
- `Session.fork` (L273) — 到 through_sequence 为止分叉：新 Session 的 metadata 记 forked_from/forked_at_sequence (L288-291)；逐条复制事件并在 data 里加 source_session_id/source_event_id/source_sequence 溯源字段、parent_event_id 指向原事件 (L296-309)；首尾各 append `session.started` / `session.forked`。调用方：runtime.py:773。
- `Session.replay` (L313) — **不是重执行**：只扫描 turn_id 相关事件，统计 `turn.started`/`turn.completed`/`turn.failed` 三个集合，incomplete = started − completed − failed (L313-334)。
- `Session.validate` (L336) — 校验 session_id 归属、event_id 唯一、sequence 从 1 起严格连续无洞、schema_version 不超当前版本 (L336-352)。__post_init__ (L210) 与所有 store.save 前都会调用。
- `Session.to_dict` (L354) / `from_dict` (L364) — 序列化；from_dict 先过 `session_migrations.migrate` (L366)。
- `InMemorySessionStore.save` (L414) — validate 后落 dict；**拒绝用更旧 sequence 的 Session 覆盖** (L418-420)；读写均 deepcopy 隔离。
- `JsonlSessionStore.save` (L480) — validate → 写临时文件（首行 `{"kind":"session","value":header}`，之后每行 `{"kind":"event","value":event.to_dict()}`）→ flush+fsync → `os.replace` 原子替换 (L483-498)。`get` (L461) 校验首行 header 的 kind=="session" (L467-468)。`_safe_id` (L443) 白名单字符校验文件名。
- `SqliteSessionStore._initialize` (L535) — 建表：`sessions`（session_id 主键）+ `session_events`（(session_id, sequence) 联合主键、event_id 唯一、ON DELETE CASCADE），PRAGMA journal_mode=WAL (L537)。
- `SqliteSessionStore.save` (L593) — validate → UPSERT sessions → **DELETE 该会话全部事件再整批重插** (L614-626)（全量覆盖式事务保存）。
- `ContextProjector.messages` (L647) — 事件→OpenAI 风格消息列表：`message.received`/`message.created`→{role(默认user),content}；`assistant.completed`/`model.completed`→assistant；`tool.completed`→{role:"tool",tool_call_id,output} (L657-667)；**没有任何消息事件时**回退到最后一条 `model.requested` 事件 data["messages"] 快照 (L668-671)。调用方：core.py:819（compact_session）。
- `ContextProjector.model_request` (L674) — 精确还原某次（或最后一次）`model.requested` 事件保存的 messages（core.py:920 在 model_request 时把 chat_params["messages"] 深拷贝进事件）。
- `ContextProjector.trace` (L691) — 把带 `trace_type` 字段的事件还原为 trace 视图（type/data/timestamp/trace_id/parent_trace_id/run_group_id）。
- `ContextBudget.estimate` (L733) — `json.dumps(全部消息)` 的字符数 ÷ chars_per_token(4) 估算 token；`fits` (L737) = estimate ≤ max_tokens − reserved_output_tokens。
- `ContextCompactor.compact` (L753) — 先 `_spill_tool_results` (L802)：超 max_inline_tool_chars(默认12000) 的 tool 消息内容替换为 `tool-result:sha256:<digest>` 引用、原文进 spilled (L811-821)；再保第一条 system + 保留最近 keep_count 条非 system 消息；被裁掉的头部若配了 summarizer 则生成摘要消息插回 (L768-777)；开头连续 tool 消息会被移除（避免孤立 tool 结果，L766-767）。
- `ContextCompactor.compact_to_budget` (L785) — 超预算时从 max_messages=len(messages) 逐次降一档重试 compact 直到 fits，最低降到 2 (L794-800)。
- `SessionMigrationRegistry.migrate` (L48) / `migrate_event` (L64) — 按 schema_version 逐版套用注册的迁移函数；版本高于当前支持值直接 raise (L51-53)。

## 关键机制细节
### 三种存储对比与适用场景
| 存储 | 行号 | 数据形态 | 适用场景 |
|---|---|---|---|
| InMemorySessionStore | L394-432 | `dict[session_id → Session]` + RLock，全部 deepcopy 隔离；拒绝旧序列覆盖 (L418-420) | 默认后端、单进程、测试；AgentRuntime 未传 session_store 时用它（runtime.py:726） |
| JsonlSessionStore | L435-518 | 每会话一个 `<session_id>.jsonl`：首行 header（kind:"session"，含 metadata/created_at/updated_at/schema_version），后续每行一条事件（kind:"event"）；保存为 tmp+fsync+os.replace 的**原子全量重写** | 单机持久化、人类可读可 grep、易备份/手工检查；会话数与事件量不大时 |
| SqliteSessionStore | L521-641 | 单库两表：sessions（元数据）+ session_events（按 (session_id, sequence) 主键，payload 为 JSON 文本）；WAL；保存 = UPSERT + DELETE 全部旧事件再重插（事务） | 多会话管理、需要 SQL 查询/统计、跨进程共享文件级持久化 |

三者都实现同一 SessionStore 协议（L377-391：create/get/save/list/delete），`create` 均拒绝重复 id，`save` 前均强制 `session.validate()`。

### 事件格式（SessionEvent，L103-145）
序列化字段：`event_id`（uuid hex）、`session_id`、`type`（如 "turn.started"、"model.requested"）、`data`（dict，写入时经 _json_safe 脱敏）、`timestamp`（UTC ISO）、`sequence`（从 1 连续递增）、`schema_version`、可选 `turn_id/step_id/run_id/agent_id/parent_event_id`（用于按轮次/运行/代理切片与事件溯源链接）。写入方：AgentRuntime._append（runtime.py:806）与 core.py:_record_session_event（core.py:891）。

### 事件类型（由 core.py 生产，session.py 消费）
core.py:876 `turn.started`、core.py:881 `message.received`、core.py:915-918（trace→session 类型映射：model_request→`model.requested`、model_response→`assistant.completed`、tool_call→`tool.requested`、tool_result→`tool.completed`、guardrail/hook_block→`policy.blocked`、run_end→`run.completed`/`run.failed`）、core.py:1052 `turn.completed`/`turn.failed`、core.py:1129 `model.completed`/`model.failed`。runtime.py 产 `inbox.*`、`goal.*`、`budget.*`、`job.*`、`subagent.*`、`progress.*`、`session.*`。

### 恢复/回放两条路径
1. **整会话恢复**：`store.get()` → 逐行/逐行 payload → SessionEvent.from_dict → Session.__post_init__ 排序+validate；跨版本 payload 先过 migrate（from_dict L366）。
2. **运行时管理器状态恢复**：AgentRuntime.open_session（runtime.py:754-758）在 Session 之上回放各命名空间事件（见 runtime.py 知识节）。
3. **重放统计**：`Session.replay()`（L313）只算 turn 完成度，供 UI/诊断；`ContextProjector.messages()` 则把事件重新投影成"模型可用的对话历史"。

### 上下文压缩流程
`compact` (L753)：spill 超长 tool 结果（sha256 引用外置）→ 若条数超 max_messages：保首条 system → 保最新 N 条非 system → 移除头部孤立 tool 消息 → 可选 summarizer 生成 "Previous conversation summary" 系统消息插回 (L769-775)。`compact_to_budget` (L785) 以二分式递减 max_messages 收敛到预算内。全程确定性（不用 LLM，除非显式传 summarizer）。

## 与其他模块的关系
| 本模块符号:行号 | 对方模块.符号 | 说明 |
|---|---|---|
| Session/SessionStore/_utc_now (L14 被 import) | runtime.AgentRuntime（runtime.py:14） | runtime 全部持久化建立在 Session 之上 |
| Session.append (L216) ← runtime.py:808 | runtime.AgentRuntime._append | 管理器事件出口 |
| Session.append (L216) ← core.py:896 | core.LightAgent._record_session_event | 对话事件出口（turn/model/tool 等类型） |
| InMemorySessionStore (L394) ← runtime.py:726 | runtime.AgentRuntime.__init__ 默认后端 | 未注入 store 时的缺省 |
| SessionStore.get/create/save (L377) ← core.py:781/827 | core.LightAgent.get_session / compact_session | 会话查询与压缩落盘 |
| ContextProjector.messages (L647) ← core.py:819 | core.LightAgent.compact_session | 压缩前从事件投影消息 |
| Session.checkpoint (L262) ← runtime.py:763 | runtime.AgentRuntime.checkpoint | 打点即事件 |
| Session.fork (L273) ← runtime.py:773 | runtime.AgentRuntime.fork | 会话分叉 |
| LightAgent/__init__.py:234 `"Session"` 等导出 | 包导出 | Session/各 Store/Projector/Compactor 均公开 |

## 阅读陷阱
1. "append-only" 是**逻辑**语义：JsonlSessionStore.save 是临时文件+os.replace 的原子全量重写 (L480-498)，SqliteSessionStore.save 是 DELETE+整批重插 (L614-626)——都不是物理追加；只有 JSONL 的命名容易让人误会。
2. `Session.replay()` **不重放执行**任何东西，只是扫描 turn.started/completed/failed 事件做集合统计 (L313-334)；"重放"在 runtime 层另有"事件回放重建状态"的含义，两处同名概念不同。
3. `_json_safe` 在事件**写入时**就把敏感 key 替换为 "[redacted]"、不可序列化对象 repr 化 (L83-100)；之后无法从日志找回原文，也别以为 data 里存的是原始 Python 对象。
4. `ContextProjector.messages` 平时用 message.* 事件重建，但完全没有消息事件时回退到最后一条 model.requested 里存的 messages 快照 (L668-672)——两种来源的粒度和内容可能不同。
5. ContextBudget 的 token 估算是 `字符数/4`（L733-735），不是真实 tokenizer，中文场景偏差更大；budget 校验只用于压缩收敛，不是硬保证。
6. sequence 从 1 开始且必须严格连续（validate L344-345）；手工构造事件用 `append_event` 时 sequence=0 会自动补位，但给错非零值直接 raise (L249-250)。
7. `create` 与 `save` 分离：`create` 拒绝已存在 id；重复 create 同一 session_id 会 ValueError（三个 store 均如此），恢复现场应走 `get` 判空。

## 高频符号中文短语表
| 符号 | 中文短语 |
|---|---|
| SessionEvent (L103) | 会话事件最小事实（type+data+sequence） |
| Session (L194) | 只追加事件日志的会话聚合根 |
| SessionCheckpoint (L167) | 序列号级检查点元数据 |
| SessionReplay (L180) | 轮次完成度重放统计 |
| SessionStore (L377) | 会话存储协议（create/get/save/list/delete） |
| InMemorySessionStore (L394) | 线程安全深拷贝内存后端 |
| JsonlSessionStore (L435) | 每会话一 JSONL 文件（原子全量重写） |
| SqliteSessionStore (L521) | WAL+事务的 SQLite 后端 |
| SessionMigrationRegistry (L35) | 逐版本 schema 迁移注册表 |
| ContextProjector (L644) | 事件→模型消息/trace 投影器 |
| ContextBudget (L717) | 字符估算的上下文 token 预算 |
| ContextCompactor (L741) | 确定性裁剪+摘要+超长工具结果外溢 |
| append (L216) | 追加事件并自增 sequence |
| fork (L273) | 到指定序列为止复制分叉新会话 |
| replay (L313) | 统计完成/未完成/失败轮次 |
| validate (L336) | 校验 sequence 连续与 event_id 唯一 |
| _json_safe (L83) | 递归脱敏与 JSON 安全化 |

---

# 记忆协议与安全策略（LightAgent/protocol.py，共 559 行）

## 模块概览
protocol.py 定义记忆子系统的"契约层"：`MemoryProtocol`（结构化 Protocol，记忆后端只需实现 store/retrieve 两方法）；`MemoryScope`（来源/作用域等溯源元数据的推荐形态）；`MemoryCandidate`（**不可注入**的候选记忆，等待显式晋升）；`MemoryPromotionDecision`/`MemoryAdmissionDecision`（晋升与写入的决策结果对象）；`MemoryPolicy`（共享记忆后端的可选安全策略：命名空间、来源/作用域白名单、置信度阈值、过期检查、写入准入/频控/去重、晋升准入，以及**防提示注入**的内部记忆晋升要求）。本模块纯声明与纯函数，无 I/O。

## 类与符号清单（全部 Protocol/抽象类及方法签名）
- **MemoryProtocol** (L16-22)（typing.Protocol，结构化类型，实现类无需继承）：
  - `store(self, data: str, user_id: str) -> Any`
  - `retrieve(self, query: str, user_id: str) -> Any`
  - 实现类：shared_memory.SharedMemoryPool（L40，签名扩展了关键字参数）；用户自定义适配器（example/11.vector_memory_adapter.py:52、example/clawmem_memory_adapter.py:22 等）；LightAgent 构造参数 `memory: Optional[MemoryProtocol]`（core.py:130）。
- MemoryScope (L25-75)：frozen dataclass。字段 source(默认"user")/scope(默认"user")/agent_name/trace_id/parent_trace_id/confidence/trust_level/metadata。方法：
  - `to_metadata(self) -> dict[str, Any]` (L38)
  - `user(cls, *, agent_name=None, trace_id=None, **metadata) -> MemoryScope` (L56)
  - `reflection(cls, *, agent_name=None, trace_id=None, parent_trace_id=None, **metadata) -> MemoryScope` (L60，source="reflection", scope="agent")
- 晋升动作常量 (L78-81)：MEMORY_PROMOTION_APPROVE/REJECT/REWRITE/KEEP。
- MemoryCandidate (L84-156)：frozen dataclass。字段 data/memory_user_id/original_user_id/source/scope/agent_name/trace_id/parent_trace_id/run_id/run_group_id/confidence/trust_level/candidate_id(uuid)/status(默认"candidate")/injectable(默认 False)/metadata。方法：
  - `with_updates(self, **updates) -> MemoryCandidate` (L105，dataclasses.replace)
  - `to_metadata(self) -> dict[str, Any]` (L109，导出为适配器持久化元数据，含 promotion_status/injectable)
  - `to_dict(self, *, include_data: bool = True) -> dict[str, Any]` (L135，API/hook/测试用序列化，剔除 None)
- MemoryPromotionDecision (L159-219)：frozen dataclass（action 默认 KEEP；__post_init__ 校验 action ∈ 四常量并小写化，L168-177）。
  - `promotes` property (L179)：action ∈ {approve, rewrite}
  - `approve(cls, value=None, *, reason=None, metadata=None)` (L183)
  - `reject(cls, reason=None, *, metadata=None)` (L193)
  - `rewrite(cls, value, *, reason=None, metadata=None)` (L202)
  - `keep(cls, reason=None, *, metadata=None)` (L212)
- MemoryAdmissionDecision (L222-228)：frozen dataclass（allowed: bool, reason, value）——写入准入结果。
- MemoryPolicy (L231-559)：frozen dataclass 策略对象。字段 (L235-250)：namespace、allow_unattributed_results(默认True)、allowed_sources、allowed_scopes、allowed_agent_names、allowed_trust_levels、min_confidence、enforce_expires_at、memory_write_admission 回调、max_writes_per_run、reject_duplicate_writes、min_write_length、reject_write_patterns、memory_promotion_admission 回调、require_promotion_for_internal_memory(默认True)、require_write_admission(默认False)。

## 关键方法
- `MemoryScope.to_metadata` (L38) — 把 scope 字段平铺进一个 metadata dict（None 字段跳过）。调用方：shared_memory.py:154/159。
- `MemoryPolicy.scoped_user_id` (L264) — 有 namespace 时返回 `"{namespace}:{user}"`，否则原样；实现"同池多租户隔离"。调用方：core.py:1442、core.py:1463。
- `MemoryPolicy.allows_result(item, scoped_user_id, original_user_id) -> bool` (L270) — 检索结果能否注入上下文：非 dict item 按 allow_unattributed_results (L272-273)；命中防注入块 (L282) 直接 False；user_id 归因缺失→allow_unattributed_results；归因 user_id 必须等于 original 或 scoped 之一 (L285-289)；再依次过 source/scope/agent_name/trust_level 白名单、min_confidence、未过期 (L292-299)。调用方：core.py:1887。
- `MemoryPolicy.allows_write(data, context, *, write_count, recent_fingerprints) -> MemoryAdmissionDecision` (L409) — 写入准入流水线：max_writes_per_run 频控 (L421)→min_write_length (L427)→reject_write_patterns 正则 (L433-435)→write_fingerprint 去重 (L437-439)→无回调时：require_write_admission 则拒、否则放行 (L441-447)→有回调：异常吞掉转拒绝 (L449-455)，None 在 require_write_admission 下视为未批准 (L456-460)，其余 `_coerce_write_decision` 归一 (L461)。调用方：core.py:1576。
- `MemoryPolicy.allows_promotion(candidate, context) -> MemoryPromotionDecision` (L463) — 内部记忆晋升准入：无回调→keep("需要显式批准") (L469-470)；回调异常→keep（带错误类型 metadata）(L471-477)；否则 `_coerce_promotion_decision`。调用方：core.py:1724。
- `MemoryPolicy.write_fingerprint(data, context) -> str` (L480) — 去重键：`(memory_user_id|source|scope|agent_name)|小写空白归一化的内容` (L484-489)。调用方：core.py:1641、core.py:1810。
- `MemoryPolicy._blocks_prompt_injection(item, metadata) -> bool` (L352) — 防注入核心：injectable 显式为假→阻断；promotion_status ∈ 候选/待审/kept/rejected 等状态→阻断 (L357-369)；`require_promotion_for_internal_memory=True` 时，来源或作用域属于内部集合（reflection/delegation/self_learning/agent/derived/swarm/trace/tool；scope: agent/delegation/shared/internal/swarm/flow，L374-393）而未 promoted/approved→阻断 (L394-399)。
- `_allows_value` (L310) / `_allows_confidence` (L326) / `_allows_not_expired` (L337) — 三项过滤器：白名单（字段缺失即 False）、置信度阈值（解析失败 False）、过期时间（ISO 或时间戳，解析失败 False，未设 expires 且 enforce_expires_at=False 放行）。
- `_coerce_write_decision` (L491) — 回调返回值归一：Decision 原样；None/True→放行；False→拒绝；str→拒绝并作为 reason；dict 按 allowed/reason/value；其他真值→放行并 str() 为 value。
- `_coerce_promotion_decision` (L509) — 晋升回调归一：None→keep；True→approve(原文)；False→reject；str→reject(reason)；dict：有 action 直接用；allowed=True 且 value≠原文→rewrite、否则 approve；allowed=False→reject；仅 value→rewrite；其余 keep (L510-559)。
- `MemoryPolicy.__post_init__` (L252) — 各 allowed_* Iterable 统一转 tuple[str]；max_writes_per_run/min_write_length 负数报错；reject_write_patterns 转 tuple。

## 关键机制细节
### MemoryProtocol 接口约定
只有两个方法（L18-22），参数是位置参数 data/user_id，返回值 Any（框架不解释返回结构，由 allows_result 逐 item 检查 dict 形态）。SharedMemoryPool 的 retrieve 返回 `{"results": [ {memory, user_id, metadata, memory_id, created_at} ]}`（shared_memory.py:29-37 的 to_result 形态），MemoryPolicy.allows_result 正是按这种 item dict 检查。写入路径在 core.py：先 memory_policy.allows_write 准入 (core.py:1576)，再 scoped_user_id 定位命名空间 (core.py:1442)，检索时 memory_policy.allows_result 过滤 (core.py:1887)。

### 两级准入模型（写入准入 vs 晋升准入）
- **写入准入**（allows_write，L409）：发生在"要不要把内容存进后端"，产出 MemoryAdmissionDecision。
- **晋升准入**（allows_promotion，L463）：发生在"内部产生的记忆（reflection 等）能不能从 candidate 升级为可注入 prompt"，产出 MemoryPromotionDecision（approve/reject/rewrite/keep）。`MemoryCandidate.injectable` 默认 False（L102），未晋升的内部记忆在检索侧还会被 `_blocks_prompt_injection` 二次拦截（L352-399）——**准入与检索双重防线**。

### 归因（user_id）模型
写入时区分 memory_user_id（实际存储用的 scoped id）与 original_user_id（真实用户）；检索项的 user_id 必须等于二者之一才可能通过 (L288-289)，配合 namespace 前缀（scoped_user_id L264）实现共享池内的租户隔离。

## 与其他模块的关系
| 本模块符号:行号 | 对方模块.符号 | 说明 |
|---|---|---|
| MemoryProtocol (L16) ← core.py:32, core.py:130 | core.LightAgent.__init__ 的 memory 参数 | Agent 的记忆后端注入点 |
| MemoryPolicy (L231) ← core.py:31, core.py:220 | core.LightAgent.__init__（memory_policy/memory_namespace） | 默认 `MemoryPolicy(namespace=memory_namespace)` |
| scoped_user_id (L264) ← core.py:1442/1463 | core 记忆检索与写入路径 | 命名空间隔离 |
| allows_write (L409) ← core.py:1576 | core 记忆写入准入（含 fingerprints 计数，core.py:1641） | 写入防线 |
| allows_promotion (L463) ← core.py:1724 | core 记忆晋升流程（候选→可注入） | 晋升防线 |
| allows_result (L270) ← core.py:1887 | core 记忆检索过滤 | 注入防线 |
| write_fingerprint (L480) ← core.py:1641/1810 | core 写入去重指纹集合 | 重复写入拦截 |
| MemoryScope (L25) ← shared_memory.py:16 | shared_memory.SharedMemoryPool._build_metadata (L146) | 记录溯源元数据基底 |
| MemoryProtocol 形态 ← shared_memory.py:29-37 | SharedMemoryRecord.to_result | retrieve 返回的 item dict 形态 |
| LightAgent/__init__.py:13-17,167-172 | 包导出 | 全部记忆类型公开 |

## 阅读陷阱
1. MemoryProtocol 是 `typing.Protocol`（结构化子类型）：实现类**不需要**继承它，只要签名兼容即视为实现；给"实现类清单"下结论时不能靠 `issubclass` 检查。
2. `allow_unattributed_results=True`（默认）意味着**无归因的检索结果默认放行** (L272-273, L285-286)——安全上想收紧必须显式关掉；但 user_id 归因了却不匹配则必拒 (L288-289)。
3. 自定义 admission 回调抛异常会被吞掉并转为"拒绝/keep"（L449-455、L471-477），回调里看不到 traceback；调试时应主动打日志。
4. `_coerce_promotion_decision` 中 dict 返回 `{"allowed": True, "value": "..."}`：value 与原文不同会被解释成 **rewrite** 而非 approve (L532-538)——语义由"是否改写内容"隐式决定。
5. `_truthy` (L401-407) 把 "promoted"/"approved" 字符串也当真值；promotion_status 检查先于 injectable 的 truthy 兜底，两组状态字符串（candidate/pending/…/promoted/approved）是**约定俗成**、没有枚举类约束。
6. MemoryPolicy 是 frozen dataclass 但 __post_init__ 用 `object.__setattr__` 改字段（tuple 化，L252-262），构造后不可变是约定而非强制。

## 高频符号中文短语表
| 符号 | 中文短语 |
|---|---|
| MemoryProtocol (L16) | 记忆后端最小接口（store/retrieve） |
| MemoryScope (L25) | 记忆溯源元数据形态（source/scope/agent） |
| MemoryCandidate (L84) | 待晋升的不可注入候选记忆 |
| MemoryPromotionDecision (L159) | 晋升决策（approve/reject/rewrite/keep） |
| MemoryAdmissionDecision (L222) | 写入准入决策（allowed+reason） |
| MemoryPolicy (L231) | 共享记忆安全策略（白名单+频控+防注入） |
| scoped_user_id (L264) | 命名空间前缀隔离用户 ID |
| allows_result (L270) | 检索结果可否注入上下文的过滤 |
| allows_write (L409) | 写入准入流水线（频控/长度/正则/去重） |
| allows_promotion (L463) | 内部记忆晋升准入回调 |
| write_fingerprint (L480) | 写入去重指纹（scope+归一化内容） |
| _blocks_prompt_injection (L352) | 未晋升内部记忆的注入阻断 |
| promotes (L179) | 是否实际晋升（approve/rewrite） |
| to_metadata (L38/L109) | scope/候选导出为持久化 metadata |

---

# 共享记忆池（LightAgent/shared_memory.py，共 196 行）

## 模块概览
shared_memory.py 提供**进程内、只追加、无持久化**的共享记忆原型 SharedMemoryPool：满足 MemoryProtocol（`store(data, user_id)` / `retrieve(query, user_id)`），内部是带 RLock 的 SharedMemoryRecord 列表，检索用**词面 token 重叠**打分排序，记录 metadata 携带 MemoryScope 溯源（source/scope/agent_name/user_id）。定位是 LightSwarm/LightFlow 多代理实验的轻量后端，模块自述 "not as durable storage" (L47)；外部后端可镜像其记录形态。

## 类与符号清单
- SharedMemoryRecord (L19-37)：frozen dataclass——memory、user_id、metadata、memory_id(uuid)、created_at(UTC ISO)；`to_result` (L29) 返回 MemoryProtocol 检索形态 dict。
- SharedMemoryPool (L40-196)：共享记忆池主体。构造参数 (L50-57)：agent_name（本池归属代理，写入默认元数据用）、default_source（默认"user"）、default_scope（默认"user"）、max_results（默认5，>0 校验 L58）。

## 关键方法
- `store` (L67) — 追加一条记录：`_build_metadata` 生成溯源 metadata (L76)、RLock 下 append (L82-83)；返回 `{"stored": True, "memory_id", "user_id"}`。调用方：作为 `LightAgent(memory=pool)` 的后端被 core.py 记忆写入路径调用（core.py:1866 `store = getattr(self.memory, "store")`）。
- `retrieve` (L86) — 过滤（`_record_matches`：user_id 必须精确匹配 record.user_id，agent_name/source/scope 按 metadata 可选过滤，L103-106）→ token 重叠打分 `_score` (L108-112) → 按 (score, index) **reverse** 排序（同分时后写入靠前）→ 取前 max_results 且 score>0（query 为空 token 时返回全部匹配）(L113)。调用方：core.py:1514（`self.memory.retrieve(query=..., user_id=memory_user_id)`）。
- `list_records` (L115) — 同样的过滤条件但**不排序不打分**，全量返回（巡检用）。
- `clear` (L131) — 清空全部或指定 user_id 的记录，返回清除条数。
- `__len__` (L142) — 记录总数（RLock 保护）。
- `_build_metadata` (L146) — 传入 MemoryScope 则以其 `to_metadata()` 为基底 (L153-154)；否则按 default_source/default_scope/agent_name 构造 MemoryScope 并附 user_id (L156-161)；再 update 调用方 metadata；最后 `setdefault("user_id", ...)` (L164)。
- `_record_matches` (L167) — 静态过滤谓词：user_id 比 record.user_id，其余三项比 metadata。
- `_tokenize` (L187) — 小写 split 的词集合。
- `_score` (L191) — `len(query_tokens & record_tokens)`；query 无 token 时恒 1。

## 关键机制细节
### 读写语义
- **写**：纯 append，无去重、无容量上限、无落盘；metadata 统一走 MemoryScope 形态（保证 allows_result/allows_promotion 能读到 source/scope/agent_name）。
- **读**：user_id 是**硬过滤**（精确相等，L177-178）——池内多用户天然隔离；agent_name/source/scope 是可选软过滤（None 即不过滤）。排序=(重叠 token 数, 写入序号) 双键倒序，同分时**最新写入优先**。
- **与 MemoryPolicy 的分工**：池本身只做"按 user_id 取回"，能否注入 prompt 由 core.py:1887 的 `memory_policy.allows_result` 决定；池的 metadata 形态（含 user_id/source/scope）正是 policy 过滤所依赖的输入。
- **多代理共享**：同一 pool 可被多个 LightAgent 以 `memory=` 注入；写时 agent_name 区分来源，读时用 scope/agent_name 过滤可实现"只看自己的反思"或"共享用户记忆"。

## 与其他模块的关系
| 本模块符号:行号 | 对方模块.符号 | 说明 |
|---|---|---|
| SharedMemoryPool (L40) ← core.py:1866 | core 记忆写入路径（store 回调） | 作为 MemoryProtocol 实现被 LightAgent 调用 |
| SharedMemoryPool.retrieve (L86) ← core.py:1514 | core 记忆检索路径 | 返回 results 列表交 policy 过滤 |
| MemoryScope (L25 of protocol.py) ← shared_memory.py:16 | protocol.MemoryScope._build_metadata (L146) | 记录溯源元数据基底 |
| SharedMemoryRecord.to_result (L29) | protocol.MemoryProtocol 检索形态 | item dict：memory/user_id/metadata/memory_id/created_at |
| LightAgent/__init__.py:59,218 | 包导出 | SharedMemoryPool/SharedMemoryRecord 公开 |

## 阅读陷阱
1. 检索是**词面 token 重叠**（bag-of-words 交集大小，L191-196），没有向量/模糊/语义匹配；同义改写检索不到。query 为空时返回全部匹配记录而非空结果 (L113)。
2. user_id 过滤是**精确相等** (L177-178)：若 core 侧用 `scoped_user_id`（带 namespace 前缀）检索，池里存的 user_id 也必须是同一个 scoped 值才查得到——隔离语义在写入侧就决定了。
3. 池**无持久化、无去重、无上限**（模块自述 prototype，L46-47）；进程重启即空，重复 store 会重复返回。
4. `max_results` 构造时校验 >0 (L58)，但 retrieve 的 `limit` 参数传 <=0 时静默返回空 (L98-99)——两处行为不一致。

## 高频符号中文短语表
| 符号 | 中文短语 |
|---|---|
| SharedMemoryPool (L40) | 进程内只追加共享记忆原型 |
| SharedMemoryRecord (L19) | 单条记忆记录（含溯源 metadata） |
| store (L67) | 追加记忆并返回 memory_id |
| retrieve (L86) | token 重叠打分的范围检索 |
| list_records (L115) | 按溯源条件巡检全部记录 |
| clear (L131) | 清空全部或单用户记录 |
| _build_metadata (L146) | 以 MemoryScope 为基底的元数据合成 |
| _score (L191) | 查询与记录的词集合交集数 |
| to_result (L29) | 输出 MemoryProtocol 检索 item 形态 |
