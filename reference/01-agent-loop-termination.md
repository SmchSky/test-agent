# Claude Code 分析报告：Agent Loop 终止条件设计

> **分析范围**: `src/query.ts`, `src/QueryEngine.ts`, `src/query/tokenBudget.ts`, `src/query/stopHooks.ts`
> **产出目标**: 指导 Test Agent 的 ReAct 循环引擎设计

---

## 1. 架构总览

Claude Code 的 Agent Loop 采用 **两层架构**：

| 层级                     | 文件               | 职责                                |
|------------------------|------------------|-----------------------------------|
| **会话层 (QueryEngine)**  | `QueryEngine.ts` | 管理整个会话生命周期，跨 turn 持久化状态，处理费用预算检查  |
| **Turn 层 (queryLoop)** | `query.ts`       | 管理单次 LLM 推理→工具调用→观察结果 的循环，处理上下文压缩 |

调用关系：

```
QueryEngine.submitMessage()
  └── query()            // 入口，包装 queryLoop + 命令生命周期通知
        └── queryLoop()  // 核心 while(true) 循环
```

### 1.1 核心循环结构

```typescript
// query.ts — queryLoop 简化骨架
async function* queryLoop(params, consumedCommandUuids) {
  let state: State = { turnCount: 1, ... };

  while (true) {
    // 1. 上下文压缩（snip → microcompact → contextCollapse → autoCompact）
    // 2. 阻塞限制检查（token 超限时直接 return）
    // 3. 调用 LLM（streaming）
    // 4. 处理 LLM 响应
    // 5. 如果没有 tool_use → 进入终止判断逻辑
    // 6. 如果有 tool_use → 执行工具 → 检查中断/maxTurns → continue
    state = next;
  }
}
```

**关键设计决策**：Claude Code 使用 `AsyncGenerator` (yield/return) 而非回调或 Promise 链来实现循环控制。这使得：

- 每个 `return { reason: '...' }` 就是一个终止点
- 每个 `continue` 就是继续下一轮循环
- 调用方可通过 `for await` 逐步消费消息流

---

## 2. 终止条件完整清单

通过对 `query.ts` 和 `QueryEngine.ts` 中所有 `return` 语句的分析，Claude Code 共有 **12+ 种终止条件**：

### 2.1 queryLoop 层的终止条件

| #  | 终止原因 (reason)         | 检查位置        | 触发条件            |
|----|-----------------------|-------------|-----------------|
| 1  | `blocking_limit`      | 循环开始、API调用前 | token 用量达到硬阻塞限制 |
| 2  | `image_error`         | 异常捕获        | 图片尺寸/缩放错误       |
| 3  | `model_error`         | 异常捕获        | LLM API 抛出未处理异常 |
| 4  | `aborted_streaming`   | 流式响应后       | 用户在流式输出期间中断     |
| 5  | `prompt_too_long`     | 响应后恢复失败     | 上下文超限且所有恢复策略耗尽  |
| 6  | `stop_hook_prevented` | 停止钩子        | 外部钩子阻止继续        |
| 7  | `completed`           | 正常完成        | LLM 未调用工具，正常结束  |
| 8  | `hook_stopped`        | 工具执行后       | 工具执行的钩子阻止继续     |
| 9  | `aborted_tools`       | 工具执行后       | 用户在工具执行期间中断     |
| 10 | `max_turns`           | 工具执行后       | 达到最大轮次限制        |

### 2.2 QueryEngine 层的终止条件

| #  | SDK subtype                           | 检查时机       | 触发条件                 |
|----|---------------------------------------|------------|----------------------|
| 11 | `error_max_budget_usd`                | 每条消息yield后 | 累计费用 >= maxBudgetUsd |
| 12 | `error_max_structured_output_retries` | 每条user消息后  | 结构化输出重试 >= 5次        |

### 2.3 内部继续条件（continue，不终止但会重新进入循环）

| 原因                           | 触发条件                     |
|------------------------------|--------------------------|
| `collapse_drain_retry`       | context collapse 释放空间后重试 |
| `reactive_compact_retry`     | reactive compact 成功压缩后重试 |
| `max_output_tokens_escalate` | 输出token从8K升级到64K         |
| `max_output_tokens_recovery` | 注入恢复消息让LLM继续（最多3次）       |
| `stop_hook_blocking`         | 停止钩子返回阻塞错误，注入消息重试        |
| `token_budget_continuation`  | token budget 未用完，继续工作    |
| `next_turn`                  | 正常工具执行完成，继续下一轮           |

---

## 3. 终止条件详细分析

### 3.1 最大轮次限制 (max_turns)

**源码位置**: `query.ts:1704-1712`

```typescript
const nextTurnCount = turnCount + 1;
if (maxTurns && nextTurnCount > maxTurns) {
  yield createAttachmentMessage({
    type: 'max_turns_reached',
    maxTurns,
    turnCount: nextTurnCount,
  });
  return { reason: 'max_turns', turnCount: nextTurnCount };
}
```

**检查时机**: 在工具执行完毕、附件处理完毕之后，准备进入下一轮循环之前。

**QueryEngine 侧的处理** (`QueryEngine.ts:842-874`):

```typescript
else if (message.attachment.type === 'max_turns_reached') {
  yield {
    type: 'result',
    subtype: 'error_max_turns',   // ← 明确的错误子类型
    is_error: true,
    num_turns: message.attachment.turnCount,
    errors: [`Reached maximum number of turns (${message.attachment.maxTurns})`],
  };
  return;
}
```

**设计要点**:

- `maxTurns` 是可选外部配置，通过 `QueryParams` 传入
- 轮次在每次工具执行后递增（`nextTurnCount = turnCount + 1`）
- 通过 `yield createAttachmentMessage` 发出结构化信号，上层捕获后转换为SDK结果

### 3.2 费用预算限制 (maxBudgetUsd)

**源码位置**: `QueryEngine.ts:971-1002`

```typescript
if (maxBudgetUsd !== undefined && getTotalCost() >= maxBudgetUsd) {
  yield {
    type: 'result',
    subtype: 'error_max_budget_usd',
    is_error: true,
    errors: [`Reached maximum budget ($${maxBudgetUsd})`],
  };
  return;
}
```

**检查时机**: 在 `QueryEngine.submitMessage()` 的消息处理循环中，**每处理一条消息后**都检查。粒度非常细。

### 3.3 用户中断 (abort)

区分两种场景：

**流式输出期间中断** (`query.ts:1015-1052`):

```typescript
if (toolUseContext.abortController.signal.aborted) {
  if (streamingToolExecutor) {
    // 消费剩余结果 — executor 为中止的工具生成合成 tool_results
    for await (const update of streamingToolExecutor.getRemainingResults()) {
      if (update.message) yield update.message;
    }
  } else {
    yield* yieldMissingToolResultBlocks(assistantMessages, 'Interrupted by user');
  }
  if (toolUseContext.abortController.signal.reason !== 'interrupt') {
    yield createUserInterruptionMessage({ toolUse: false });
  }
  return { reason: 'aborted_streaming' };
}
```

**工具执行期间中断** (`query.ts:1484-1516`):

```typescript
if (toolUseContext.abortController.signal.aborted) {
  if (toolUseContext.abortController.signal.reason !== 'interrupt') {
    yield createUserInterruptionMessage({ toolUse: true });
  }
  // 即使中断也检查 maxTurns
  if (maxTurns && nextTurnCountOnAbort > maxTurns) {
    yield createAttachmentMessage({ type: 'max_turns_reached', ... });
  }
  return { reason: 'aborted_tools' };
}
```

**关键设计**:

- 使用标准 `AbortController`，通过 `signal.aborted` 检查
- `signal.reason` 区分 "submit-interrupt"（用户提交新消息打断）和普通中断
- **即使中断也检查 maxTurns**，确保限制不被绕过
- 中断后要清理未完成的 tool_use 块（补充 tool_result 以保持 API 协议一致性）

### 3.4 输出 Token 超限恢复

**源码位置**: `query.ts:1188-1256`

分层恢复策略（3层）:

```
第1步: 升级 max_output_tokens 从 8K → 64K (escalate)
第2步: 如果还超限，注入恢复消息让LLM继续（最多3次）
第3步: 恢复次数耗尽，表面化错误
```

```typescript
const MAX_OUTPUT_TOKENS_RECOVERY_LIMIT = 3;

// 第1步：升级
if (capEnabled && maxOutputTokensOverride === undefined) {
  state = { ...state, maxOutputTokensOverride: ESCALATED_MAX_TOKENS };
  continue; // 不终止，继续循环
}

// 第2步：注入恢复消息
if (maxOutputTokensRecoveryCount < MAX_OUTPUT_TOKENS_RECOVERY_LIMIT) {
  const recoveryMessage = createUserMessage({
    content: 'Output token limit hit. Resume directly — no apology, no recap...',
    isMeta: true,
  });
  state = { ...state,
    messages: [...messagesForQuery, ...assistantMessages, recoveryMessage],
    maxOutputTokensRecoveryCount: maxOutputTokensRecoveryCount + 1,
  };
  continue; // 不终止，继续循环
}

// 第3步：恢复耗尽，表面化
yield lastMessage;
```

### 3.5 阻塞限制 (blocking_limit)

**源码位置**: `query.ts:628-648`

```typescript
if (!compactionResult && querySource !== 'compact' && querySource !== 'session_memory'
    && !(reactiveCompact?.isReactiveCompactEnabled() && isAutoCompactEnabled())
    && !collapseOwnsIt) {
  const { isAtBlockingLimit } = calculateTokenWarningState(
    tokenCountWithEstimation(messagesForQuery) - snipTokensFreed,
    toolUseContext.options.mainLoopModel,
  );
  if (isAtBlockingLimit) {
    yield createAssistantAPIErrorMessage({
      content: PROMPT_TOO_LONG_ERROR_MESSAGE,
    });
    return { reason: 'blocking_limit' };
  }
}
```

**检查时机**: 在循环开始、API调用之前，上下文压缩之后。
**设计要点**: 这是最高优先级检查。只在 auto-compact 关闭时生效（开启时由 auto-compact 处理）。

---

## 4. 终止后的用户反馈机制

### 4.1 分层结果类型

```typescript
type SDKResultSubtype =
  | 'success'                              // 正常完成
  | 'error_max_turns'                      // 达到最大轮次
  | 'error_max_budget_usd'                // 达到费用上限
  | 'error_max_structured_output_retries' // 结构化输出重试耗尽
  | 'error_during_execution'              // 执行中错误（兜底）
```

### 4.2 统一的结果元数据

所有结果消息都包含：

```typescript
{
  duration_ms: number,        // 总耗时
  duration_api_ms: number,    // API 调用耗时
  num_turns: number,          // 执行轮次数
  total_cost_usd: number,     // 总费用
  usage: NonNullableUsage,    // Token 用量
  permission_denials: [],     // 权限拒绝记录
  stop_reason: string | null, // LLM 的 stop_reason
  errors?: string[],          // 错误详情（仅错误类型）
}
```

---

## 5. 死循环检测与打破机制

Claude Code **没有显式的重复操作检测器**，但通过以下机制间接防止死循环：

### 5.1 max_turns 硬限制

最直接的保护。SDK/headless 调用者可设置 `maxTurns`。

### 5.2 Token Budget 收益递减检测

**源码位置**: `query/tokenBudget.ts:59-76`

```typescript
const COMPLETION_THRESHOLD = 0.9;
const DIMINISHING_THRESHOLD = 500;

const isDiminishing =
  tracker.continuationCount >= 3 &&
  deltaSinceLastCheck < DIMINISHING_THRESHOLD &&
  tracker.lastDeltaTokens < DIMINISHING_THRESHOLD;
```

如果连续 3 次以上的循环中，每次的 token 增量都低于 500，判定为低效重复，自动停止。

### 5.3 AutoCompact 断路器

**源码位置**: `services/compact/autoCompact.ts:70`

```typescript
const MAX_CONSECUTIVE_AUTOCOMPACT_FAILURES = 3;
```

防止"压缩失败→重试→再失败"的无限循环。连续失败3次后停止重试。

### 5.4 费用预算兜底

即使没有 maxTurns，费用累计最终会触发 `maxBudgetUsd` 限制。

---

## 6. 对 Test Agent 的设计建议

### 6.1 推荐的终止条件层级

```python
class TerminationReason(Enum):
    # 最高优先级 — 每轮循环开始前检查
    CONTEXT_OVERFLOW = "context_overflow"
    
    # 高优先级 — 异常和中断
    USER_ABORT = "user_abort"
    API_ERROR = "api_error"
    
    # 中优先级 — 资源限制
    MAX_TURNS = "max_turns"
    MAX_BUDGET = "max_budget"
    
    # 低优先级 — 正常完成
    TASK_COMPLETED = "task_completed"
    DIMINISHING_RETURNS = "diminishing_returns"
```

### 6.2 推荐的检查点设计

```python
while True:
    # ===== 循环开始前检查 =====
    if context_tokens > blocking_limit:
        return TerminationReason.CONTEXT_OVERFLOW
    
    # ===== LLM 调用 =====
    try:
        response = call_llm(messages)
    except UserAbortError:
        return TerminationReason.USER_ABORT
    except APIError:
        return TerminationReason.API_ERROR
    
    # ===== 响应后检查 =====
    if not response.has_tool_calls:
        return TerminationReason.TASK_COMPLETED
    
    # ===== 工具执行 =====
    results = execute_tools(response.tool_calls)
    
    # ===== 工具执行后检查 =====
    turn_count += 1
    if max_turns and turn_count > max_turns:
        return TerminationReason.MAX_TURNS
    if total_cost >= max_budget:
        return TerminationReason.MAX_BUDGET
```

### 6.3 关键实现原则

1. **终止条件分层检查**: 越严重的条件越早检查
2. **每种终止原因有独立反馈**: 给调用者明确的终止原因，不要用通用错误
3. **恢复优先于终止**: 对可恢复的错误先尝试自动恢复
4. **断路器模式**: 对可能无限重试的操作设置最大重试次数
5. **中断清理**: 用户中断后要清理未完成的工具调用，保持状态一致性
