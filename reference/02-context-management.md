# Claude Code 分析报告：上下文窗口管理策略

> **分析范围**: `src/services/compact/` 目录, `src/utils/tokens.ts`, `src/utils/context.ts`
> **产出目标**: 指导 Test Agent 的上下文管理与压缩策略设计

---

## 1. 上下文管理架构总览

Claude Code 采用了极为精细的多层上下文管理策略。不仅在达到 token 上限时进行粗暴的截断，而是通过四种不同粒度和机制的策略来最大化上下文的有效载荷。

### 1.1 核心策略矩阵

| 策略名称                 | 机制类型  | 触发时机                 | 适用场景                        |
|----------------------|-------|----------------------|-----------------------------|
| **History Snip**     | 边界截断  | 每个 Turn 前            | 长时间跨度、工具输出多，抛弃过时工具结果        |
| **Micro Compact**    | 细粒度清洗 | 达到配置的时间/数量阈值         | 清理特定的工具结果（如 grep/ls 的输出）    |
| **Context Collapse** | 滚动总结  | LLM 生成期间 / Turn 间    | 在不中断用户体验的情况下，动态将历史折叠为摘要     |
| **Auto Compact**     | 全局压缩  | 达到警戒阈值 (`threshold`) | 作为终极保底，利用 LLM 将整个历史提炼为精简的总结 |

### 1.2 Token 估算与监控机制

Claude Code 的决策高度依赖精确的 Token 计算。`src/utils/tokens.ts` 中提供了多种计算方式：

- `getTokenCountFromUsage(usage)`: 依赖 API 返回的实际 token 用量（最准确）。
- `tokenCountWithEstimation(messages)`: **核心监控函数**。结合最后一次 API 的准确用量和对新增消息的粗略估算。
- `roughTokenCountEstimationForMessages`: 完全基于文本长度和规则的启发式估算（用于尚未发送给 API 的消息）。

---

## 2. Token 容量计算与阈值设计

**源码位置**: `src/services/compact/autoCompact.ts` 与 `src/utils/context.ts`

### 2.1 上下文窗口定义

```typescript
// 预留给 LLM 生成总结的 Output Tokens
const MAX_OUTPUT_TOKENS_FOR_SUMMARY = 20_000

export function getEffectiveContextWindowSize(model: string): number {
  const reservedTokens = Math.min(
    getMaxOutputTokensForModel(model),
    MAX_OUTPUT_TOKENS_FOR_SUMMARY,
  )
  let contextWindow = getContextWindowForModel(model) // 默认 200,000
  return contextWindow - reservedTokens
}
```

**设计要点**：实际可用窗口不是模型的物理上限（如 200k），必须减去执行“压缩操作”本身所需的 Token 空间。

### 2.2 阈值分层 (Thresholds)

```typescript
export const AUTOCOMPACT_BUFFER_TOKENS = 13_000
export const WARNING_THRESHOLD_BUFFER_TOKENS = 20_000
export const ERROR_THRESHOLD_BUFFER_TOKENS = 20_000
export const MANUAL_COMPACT_BUFFER_TOKENS = 3_000

export function getAutoCompactThreshold(model: string): number {
  return getEffectiveContextWindowSize(model) - AUTOCOMPACT_BUFFER_TOKENS
}
```

这产生了一个梯度：

1. `Warning Threshold` (有效窗口 - 20k)
2. `AutoCompact Threshold` (有效窗口 - 13k)：触发全局压缩
3. `Blocking Limit` (有效窗口 - 3k)：硬阻塞限制

---

## 3. 核心压缩策略分析

### 3.1 Micro Compact (细粒度清洗)

**源码位置**: `src/services/compact/microCompact.ts`

**机制**：只清洗掉（修改为占位符）那些容易占用大量 Token 且时效性差的工具结果（如 `grep`, `glob`, `read_file`）。

**触发方式一：Cached Path (结合 Prompt Cache)**
如果不改变前面的消息，可以继续利用 Prompt Cache。Claude 记录需要删除的 Tool IDs，然后在下一次 API 请求中，利用 Anthropic API 的 `cache_edits`
功能“虚空”删除它们，而不需要在客户端重写整个消息树。

**触发方式二：Time-based Path**

```typescript
// evaluateTimeBasedTrigger
const gapMinutes = (Date.now() - new Date(lastAssistant.timestamp).getTime()) / 60_000
if (gapMinutes > config.gapThresholdMinutes) { ... }
```

当用户停顿时间超过阈值（缓存已失效），代码会直接将旧的工具输出（保留最近的 `keepRecent` 个）替换为 `[Old tool result content cleared]`。

### 3.2 Auto Compact (全局 LLM 总结)

**源码位置**: `src/services/compact/compact.ts` 与 `src/services/compact/prompt.ts`

这是应对即将突破 Token 限制的终极手段。

**核心流程 (`compactConversation`)**:

1. 检查限制并触发前置 Hook。
2. 剥离图像等重资产：`stripImagesFromMessages`。
3. 剥离容易重新获取的附件：`stripReinjectedAttachments`。
4. **生成请求：** 发送特殊的 Prompt 让 LLM（通常使用主模型或专门的 summarization 模型）生成历史记录的总结。
5. **保存总结，截断历史：** 创建一个 `CompactBoundaryMessage` 记录截断点，将生成的摘要作为一条新的 User 消息推入。
6. **状态恢复：** 重新注入被清理的必要附件（如 File Read 的最新状态、Plan 计划等）。

**总结 Prompt 设计 (`prompt.ts`)**:
Claude Code 为 LLM 设计了极为详尽的 Summarization Prompt：

- 要求包含：Primary Request, Key Technical Concepts, Files and Code Sections, Errors and fixes, Pending Tasks。
- **思维链强制**：强制要求 LLM 先输出 `<analysis>` 标签进行分析，再输出 `<summary>`。在应用总结前，客户端会主动**剔除** `<analysis>` 标签，以节省被再次送入上下文的
  Token。

```typescript
// formatCompactSummary
formattedSummary = formattedSummary.replace(/<analysis>[\s\S]*?<\/analysis>/, '')
```

### 3.3 History Snip 与 Partial Compact

**机制**：`partialCompactConversation` 允许基于某个转折点（`pivotIndex`），只总结转折点**之后**（或之前）的消息。
这对于那些“保留核心设定，只抛弃近期无关闲聊”的场景非常有效。

---

## 4. 上下文状态的连续性保障

上下文被“压缩”或“截断”后，如何保证 Agent 不会失忆？Claude Code 有两套机制：

### 4.1 核心状态对象的重新注入 (Re-injection)

在 `compactConversation` 完成截断后，并不是只留下一个字符串总结，系统会立刻执行：

```typescript
// 1. 重新抓取并注入被修改的文件内容
const fileAttachments = createPostCompactFileAttachments(preCompactReadFileState...);
// 2. 注入当前的计划 (Plan)
const planAttachment = createPlanAttachmentIfNeeded(context.agentId);
// 3. 重新宣告所有工具（因为上文被截断，模型可能忘了当前可用工具）
const deferredTools = getDeferredToolsDeltaAttachment(...);
```

这意味着：**结构化的业务状态（如当前读了什么文件、有哪些工具）是通过机制硬重置进上下文的，而不是指望 LLM 在总结中记住。**

### 4.2 特殊的系统消息标记 (Compact Boundary)

```typescript
const boundaryMarker = createCompactBoundaryMessage(
  isAutoCompact ? 'auto' : 'manual',
  preCompactTokenCount,
  messages.at(-1)?.uuid
)
```

系统会插入一个特殊的 `SystemCompactBoundaryMessage`。这不仅是对用户的 UI 提示，也是系统层面的“游标”，用于告诉其他依赖消息树历史的模块（如 Prompt Cache
生成器）：“在计算 Cache 时，从这里重新开始”。

---

## 5. 对 Test Agent 的设计建议

在设计 Test Agent 的 ReAct 引擎时，上下文管理是保证长期稳定运行的关键。基于 Claude Code 的实践，提出以下建议：

### 5.1 采用分级的缓冲策略 (Threshold Buffer)

不要等到触发 API 的 `max_tokens` 报错才处理。

- 设定 `EFFECTIVE_CONTEXT = API_LIMIT - SUMMARY_RESERVE_TOKENS(20k)`
- 设定 `WARNING_LIMIT = EFFECTIVE_CONTEXT - 10k`
- 设定 `AUTO_COMPACT_LIMIT = EFFECTIVE_CONTEXT - 5k`

### 5.2 实施“微压缩” (Micro Compact) 优先于“全量总结”

针对网络设备交互（Test Agent 核心场景），设备返回的 `show tech-support` 或 `display current-configuration` 可能长达数万 Token。

- **策略**：在达到 `AUTO_COMPACT_LIMIT` 前，优先寻找并截断历史中冗长的**命令执行结果**。将它们替换为 `[Command output cleared due to length]`。这比调用
  LLM 做全量总结要快得多，且更便宜。

### 5.3 构建状态外置与重新注入机制

不要依赖 LLM 在自我总结中记住所有关键状态。

- Test Agent 应该有一个明确的 `ContextState` 对象（记录当前连接了哪些设备、拿到了哪些关键拓扑信息）。
- 当触发全量上下文压缩后，不仅要生成历史摘要，还要**硬编码**将当前的 `ContextState` 重新作为系统附件或强制用户消息注入到新的会话开头。

### 5.4 Summarization Prompt 最佳实践

如果必须使用 LLM 总结历史，请借鉴 Claude Code 的 Prompt 结构：

1. **要求思考隔离**：强制模型使用 `<analysis>` 标签分析，但在保存摘要时去除它。
2. **强制分类**：要求模型分别列出：当前明确的目标 (Primary Intent)、遇到过的错误与修复方法 (Errors and Fixes)、当前的执行进度 (Current Work)。
3. **消除幻觉约束**：严禁在总结中幻想未发生的操作，必须基于实际对话。

### 5.5 监控与兜底

- 必须有准确的 Token 估算函数。对于 Test Agent 而言，利用 `tiktoken` 估算每次交互的用量至关重要。
- 当 `Auto Compact` 自身因为超长而失败时（`prompt_too_long`），需要实现一个硬截断（Drop Head）的兜底逻辑，直接丢弃最老的 `N` 轮对话，确保系统永远不会死锁。
