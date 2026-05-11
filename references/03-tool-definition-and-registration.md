# Claude Code Tool 定义与注册机制深度分析

> **分析目标**：解构 Claude Code 的 Tool 系统架构，为 Test Agent 的 LangGraph Tool 基类设计提供参考。
> **核心源文件**：`src/Tool.ts`, `src/tools.ts`, `src/tools/*/`, `src/services/tools/toolExecution.ts`, `src/utils/toolResultStorage.ts`

---

## 一、Tool 元数据的定义方式

### 1.1 核心设计：TypeScript 对象字面量 + Zod Schema + `buildTool` 工厂函数

Claude Code **不使用类继承，不使用装饰器**，而是采用 **"类型约束的对象字面量 + 工厂函数"** 模式。每个 Tool 是一个满足 `ToolDef` 类型约束的**普通
TypeScript 对象**，通过 `buildTool()` 工厂函数补全默认值后导出。

**选择这种方式的原因**：

- **零抽象开销**：对象字面量是 JS 中最轻量的结构，没有 class 的原型链开销
- **组合优于继承**：Tool 之间没有公共行为需要继承，每个 Tool 的 `call()`, `checkPermissions()`, `mapToolResultToToolResultBlockParam()` 逻辑完全不同
- **类型安全的泛型**：通过 `Tool<Input, Output, Progress>` 三个泛型参数，在编译期保证输入/输出/进度类型的一致性
- **Fail-closed 默认值**：`buildTool()` 提供安全的默认值（如 `isReadOnly: false`, `isConcurrencySafe: false`），新 Tool 忘记设置某个属性时，系统会采取最保守的行为

### 1.2 `Tool` 类型完整接口（关键字段解析）

```typescript
// src/Tool.ts (简化)
export type Tool<Input, Output, P> = {
  // ═══════════ 标识与发现 ═══════════
  readonly name: string                    // 工具唯一标识符
  aliases?: string[]                       // 向后兼容的旧名称
  searchHint?: string                      // ToolSearch 关键词匹配短语

  // ═══════════ Schema 定义 ═══════════
  readonly inputSchema: Input              // Zod v4 输入验证 schema
  readonly inputJSONSchema?: ToolInputJSONSchema  // MCP 工具的 JSON Schema
  outputSchema?: z.ZodType<unknown>        // 输出类型验证

  // ═══════════ 核心生命周期 ═══════════
  call(args, context, canUseTool, parentMessage, onProgress): Promise<ToolResult<Output>>
  validateInput?(input, context): Promise<ValidationResult>
  checkPermissions(input, context): Promise<PermissionResult>

  // ═══════════ 行为标记 ═══════════
  isEnabled(): boolean                     // 运行时启用/禁用
  isReadOnly(input): boolean               // 是否为只读操作
  isDestructive?(input): boolean           // 是否为不可逆操作
  isConcurrencySafe(input): boolean        // 是否可并发执行
  interruptBehavior?(): 'cancel' | 'block' // 用户中断时的行为

  // ═══════════ LLM 交互 ═══════════
  description(input, options): Promise<string>   // 发送给 LLM 的描述
  prompt(options): Promise<string>               // 发送给 LLM 的详细提示词

  // ═══════════ 输出格式化 ═══════════
  mapToolResultToToolResultBlockParam(content, toolUseID): ToolResultBlockParam
  maxResultSizeChars: number               // 超过此值则持久化到磁盘

  // ═══════════ UI 渲染（React/Ink）═══════════
  renderToolUseMessage(input, options): React.ReactNode
  renderToolResultMessage?(content, progressMessages, options): React.ReactNode
  userFacingName(input): string
  getActivityDescription?(input): string | null
}
```

### 1.3 `buildTool` 工厂函数：Fail-Closed 默认值

```typescript
// src/Tool.ts:757-792
const TOOL_DEFAULTS = {
  isEnabled: () => true,
  isConcurrencySafe: (_input?) => false,    // 假设不安全
  isReadOnly: (_input?) => false,           // 假设会写入
  isDestructive: (_input?) => false,
  checkPermissions: (input, _ctx?) =>       // 默认放行，交给通用权限系统
    Promise.resolve({ behavior: 'allow', updatedInput: input }),
  toAutoClassifierInput: (_input?) => '',   // 默认不参与安全分类
  userFacingName: (_input?) => '',
}

export function buildTool<D extends AnyToolDef>(def: D): BuiltTool<D> {
  return {
    ...TOOL_DEFAULTS,
    userFacingName: () => def.name,  // 默认用 name 作为显示名
    ...def,                          // 用户定义覆盖默认值
  } as BuiltTool<D>
}
```

**关键设计决策**：

- `isConcurrencySafe` 默认 `false` → 新 Tool 默认串行执行，避免竞态
- `isReadOnly` 默认 `false` → 新 Tool 默认需要权限检查
- `checkPermissions` 默认 `allow` → 但这不意味着跳过权限，因为通用权限系统（`PermissionContext`）会在外层再做一次检查

### 1.4 具体 Tool 定义示例

**只读工具 — GrepTool（简单）**：

```typescript
// src/tools/GrepTool/GrepTool.ts
export const GrepTool = buildTool({
  name: GREP_TOOL_NAME,
  searchHint: 'search file contents with regex (ripgrep)',
  maxResultSizeChars: 20_000,
  strict: true,

  // Zod v4 Schema（延迟求值避免模块加载时开销）
  get inputSchema() { return inputSchema() },
  get outputSchema() { return outputSchema() },

  // 行为标记
  isConcurrencySafe() { return true },     // grep 可以并发
  isReadOnly() { return true },            // 不修改文件
  isSearchOrReadCommand() { return { isSearch: true, isRead: false } },

  // 权限检查 → 委托给文件系统读权限检查器
  async checkPermissions(input, context) {
    return checkReadPermissionForTool(GrepTool, input, context...)
  },

  // 输出格式化 → 纯文本
  mapToolResultToToolResultBlockParam({ numFiles, filenames, content }, toolUseID) {
    return {
      tool_use_id: toolUseID,
      type: 'tool_result',
      content: `Found ${numFiles} files\n${filenames.join('\n')}`,
    }
  },

  async call({ pattern, path, ... }, context) {
    const results = await ripGrep(args, absolutePath, signal)
    return { data: { filenames: ..., numFiles: ..., content: ... } }
  },
} satisfies ToolDef<InputSchema, Output>)
```

**危险工具 — BashTool（复杂）**：

```typescript
// src/tools/BashTool/BashTool.tsx（简化关键差异）
export const BashTool = buildTool({
  name: BASH_TOOL_NAME,
  maxResultSizeChars: 30_000,
  strict: true,

  // 并发安全取决于命令是否只读
  isConcurrencySafe(input) {
    return this.isReadOnly?.(input) ?? false
  },
  // 通过静态分析判断命令是否只读
  isReadOnly(input) {
    const result = checkReadOnlyConstraints(input, commandHasAnyCd(input.command))
    return result.behavior === 'allow'
  },

  // 专用权限检查（98KB 的 bashPermissions.ts）
  async checkPermissions(input, context) {
    return bashToolHasPermission(input, context)
  },

  // 输入验证：阻止危险的 sleep 模式
  async validateInput(input) {
    const sleepPattern = detectBlockedSleepPattern(input.command)
    if (sleepPattern) return { result: false, message: `Blocked: ${sleepPattern}...` }
    return { result: true }
  },

  // 输出：支持图片、后台任务、大文件持久化
  mapToolResultToToolResultBlockParam(
    { stdout, stderr, isImage, backgroundTaskId, persistedOutputPath }, id
  ) {
    if (isImage) return buildImageToolResult(stdout, id)
    if (persistedOutputPath) {
      stdout = buildLargeToolResultMessage({ filepath: persistedOutputPath, ... })
    }
    return {
      tool_use_id: id, type: 'tool_result',
      content: [stdout, stderr].filter(Boolean).join('\n')
    }
  },
})
```

---

## 二、Tool 的注册与发现机制

### 2.1 注册方式：**手动注册 + 条件编译**

Claude Code 采用 **显式导入 + 中央注册表** 的模式，没有自动扫描。所有工具在 `src/tools.ts` 中集中注册。

```typescript
// src/tools.ts — 中央注册表
export function getAllBaseTools(): Tools {
  return [
    AgentTool,
    TaskOutputTool,
    BashTool,
    // 条件包含：嵌入式搜索工具可用时不注册 Glob/Grep
    ...(hasEmbeddedSearchTools() ? [] : [GlobTool, GrepTool]),
    FileReadTool,
    FileEditTool,
    FileWriteTool,
    // Feature Flag 控制
    ...(isTodoV2Enabled() ? [TaskCreateTool, TaskGetTool, ...] : []),
    // 环境变量控制
    ...(isEnvTruthy(process.env.ENABLE_LSP_TOOL) ? [LSPTool] : []),
    // 用户类型控制
    ...(process.env.USER_TYPE === 'ant' ? [ConfigTool, TungstenTool] : []),
    // Bun 编译期 feature flag（死代码消除）
    ...(SleepTool ? [SleepTool] : []),      // feature('PROACTIVE')
    ...(WebBrowserTool ? [WebBrowserTool] : []),  // feature('WEB_BROWSER_TOOL')
    // 测试专用
    ...(process.env.NODE_ENV === 'test' ? [TestingPermissionTool] : []),
    // 动态工具发现
    ...(isToolSearchEnabledOptimistic() ? [ToolSearchTool] : []),
  ]
}
```

### 2.2 三层过滤机制

工具从注册到最终呈现给 LLM，经过三层过滤：

```
getAllBaseTools()          ← 第1层：全量注册（含条件编译）
    ↓
getTools(permCtx)         ← 第2层：权限过滤 + 启用检查
    ↓
assembleToolPool(permCtx, mcpTools)  ← 第3层：合并 MCP 工具 + 去重 + 排序
```

**第2层 `getTools` 的过滤逻辑**：

```typescript
export const getTools = (permissionContext: ToolPermissionContext): Tools => {
  // 简单模式：只保留 Bash + Read + Edit
  if (isEnvTruthy(process.env.CLAUDE_CODE_SIMPLE)) {
    return filterToolsByDenyRules(
      [BashTool, FileReadTool, FileEditTool], permissionContext
    )
  }

  // 过滤掉被 deny 规则封禁的工具
  let allowedTools = filterToolsByDenyRules(tools, permissionContext)

  // REPL 模式：隐藏被 REPL 封装的原始工具
  if (isReplModeEnabled()) {
    allowedTools = allowedTools.filter(t => !REPL_ONLY_TOOLS.has(t.name))
  }

  // 最终 isEnabled() 检查
  return allowedTools.filter(tool => tool.isEnabled())
}
```

**第3层 `assembleToolPool` 的排序策略**：

```typescript
export function assembleToolPool(permissionContext, mcpTools): Tools {
  const builtInTools = getTools(permissionContext)
  const allowedMcpTools = filterToolsByDenyRules(mcpTools, permissionContext)
  // 内置工具按名称排序作为连续前缀（保护 prompt cache）
  // MCP 工具排在后面，同样按名称排序
  // uniqBy 保证内置工具在名称冲突时优先
  return uniqBy(
    [...builtInTools].sort(byName).concat(allowedMcpTools.sort(byName)),
    'name',
  )
}
```

### 2.3 新增一个工具需要改哪些文件

| 步骤 | 文件                           | 操作                               |
|----|------------------------------|----------------------------------|
| 1  | `src/tools/MyTool/MyTool.ts` | 创建工具定义，使用 `buildTool()`          |
| 2  | `src/tools/MyTool/prompt.ts` | 定义工具名称常量和 prompt 模板              |
| 3  | `src/tools/MyTool/UI.tsx`    | 实现 UI 渲染函数                       |
| 4  | `src/tools.ts`               | 在 `getAllBaseTools()` 数组中添加导入和引用 |
| 5  | （可选）`src/constants/tools.ts` | 如需限制子代理使用，添加到禁用列表                |

> **关键点**：没有自动扫描，必须手动在 `tools.ts` 注册。这是 **故意的设计选择** — 保持注册顺序的确定性，因为工具顺序直接影响 prompt cache 的命中率。

---

## 三、Tool 输出格式规范

### 3.1 输出流转管道

Tool 的执行结果经过以下管道最终送达 LLM：

```
tool.call()
  ↓ 返回 ToolResult<Output>（强类型的内部数据结构）
tool.mapToolResultToToolResultBlockParam(data, toolUseID)
  ↓ 转换为 Anthropic API 的 ToolResultBlockParam（纯文本 / 图片 / 结构化内容）
processToolResultBlock(tool, result, toolUseID)
  ↓ 检查大小，超阈值则持久化到磁盘
enforceToolResultBudget(messages, state)
  ↓ 单条消息的聚合预算检查
最终注入 messages[] 发送给 LLM API
```

### 3.2 `ToolResult<T>` — 内部强类型结构

```typescript
// src/Tool.ts:321-336
export type ToolResult<T> = {
  data: T                    // 强类型的输出数据
  newMessages?: Message[]    // 可选：附加到对话的额外消息
  contextModifier?: (ctx: ToolUseContext) => ToolUseContext  // 可选：修改后续上下文
  mcpMeta?: {                // 可选：MCP 协议元数据
    _meta?: Record<string, unknown>
    structuredContent?: Record<string, unknown>
  }
}
```

**设计要点**：`data` 的类型由每个 Tool 的 `OutputSchema` 泛型参数决定。例如：

- `FileReadTool` → `data` 是 discriminated union：`{type: 'text', file: {content, numLines, ...}}` | `{type: 'image', file: {base64, ...}}`
- `BashTool` → `data` 是 `{stdout, stderr, interrupted, isImage?, backgroundTaskId?, persistedOutputPath?}`
- `FileWriteTool` → `data` 是 `{type: 'create'|'update', filePath, content, structuredPatch}`

### 3.3 `mapToolResultToToolResultBlockParam` — 面向 LLM 的序列化

每个 Tool **必须实现**此方法，将内部类型数据转换为 Anthropic API 能理解的格式。输出格式是**纯文本为主**，只在特定场景使用图片/文档块：

| Tool                 | 输出格式               | 示例                                                        |
|----------------------|--------------------|-----------------------------------------------------------|
| FileReadTool (text)  | 带行号的纯文本 + 安全提醒     | `1: import foo\n2: const bar = ...` + `<system-reminder>` |
| FileReadTool (image) | Base64 图片块         | `{type: 'image', source: {type: 'base64', data: ...}}`    |
| FileWriteTool        | 简洁确认消息             | `"File created successfully at: /path/to/file"`           |
| BashTool             | stdout + stderr 拼接 | `"output lines...\nExit code 1"`                          |
| GrepTool             | 文件列表或匹配内容          | `"Found 3 files\nfoo.ts\nbar.ts\nbaz.ts"`                 |

**关键原则**：发送给 LLM 的信息要**精简**。例如 FileWriteTool 只返回 `"File created successfully at: path"`，不返回文件内容——因为 LLM
已经知道内容是什么（它是发起写操作的一方）。

### 3.4 大型输出的截断/持久化机制

这是 Claude Code 最精巧的机制之一。它**不是简单截断**，而是采用**持久化到磁盘 + 发送预览**的策略。

#### 3.4.1 每工具阈值 (`maxResultSizeChars`)

每个 Tool 声明自己的最大输出字符数：

```typescript
// 各工具的阈值声明
FileReadTool:   maxResultSizeChars = Infinity    // 自行通过 maxTokens 限制，不持久化
BashTool:       maxResultSizeChars = 30_000      // 30K
FileWriteTool:  maxResultSizeChars = 100_000     // 100K
GrepTool:       maxResultSizeChars = 20_000      // 20K
MCPTool:        maxResultSizeChars = 100_000     // 100K

// 系统全局上限（无论工具声明多少，不超过此值）
DEFAULT_MAX_RESULT_SIZE_CHARS = 50_000           // 50K
```

#### 3.4.2 持久化流程

```typescript
// src/utils/toolResultStorage.ts:272-334
async function maybePersistLargeToolResult(toolResultBlock, toolName, threshold) {
  const content = toolResultBlock.content
  
  // 空内容 → 注入标记（避免模型误以为是终止信号）
  if (isToolResultContentEmpty(content)) {
    return { ...toolResultBlock, content: `(${toolName} completed with no output)` }
  }
  
  // 图片块不持久化
  if (hasImageBlock(content)) return toolResultBlock
  
  // 未超阈值 → 原样返回
  if (contentSize(content) <= threshold) return toolResultBlock
  
  // ✅ 超阈值 → 写入磁盘 + 生成预览
  const result = await persistToolResult(content, toolUseId)
  // 文件路径：~/.claude/projects/{project}/{session}/tool-results/{toolUseId}.txt
  
  const message = buildLargeToolResultMessage(result)
  // 生成的消息格式：
  // <persisted-output>
  // Output too large (150KB). Full output saved to: /path/to/file.txt
  //
  // Preview (first 2KB):
  // [前2000字节的内容]
  // ...
  // </persisted-output>
  
  return { ...toolResultBlock, content: message }
}
```

#### 3.4.3 每消息聚合预算

防止 N 个并行 Tool 各自在阈值内但合计超标：

```typescript
// 常量定义
MAX_TOOL_RESULTS_PER_MESSAGE_CHARS = 200_000  // 单条消息最大 200K

// 当单条 user message 中所有 tool_result 块合计超过 200K 时
// 按大小倒序选择最大的块进行持久化，直到总量降到预算内
```

#### 3.4.4 FileReadTool 的特殊处理

FileReadTool 设置 `maxResultSizeChars = Infinity`，因为将其持久化到文件再让模型用 Read 读取会造成**循环依赖**。它通过自己的 `maxTokens` 限制来控制输出大小：

```typescript
// src/tools/FileReadTool/FileReadTool.ts:755-772
async function validateContentTokens(content, ext, maxTokens?) {
  const effectiveMaxTokens = maxTokens ?? getDefaultFileReadingLimits().maxTokens
  const tokenEstimate = roughTokenCountEstimationForFileType(content, ext)
  if (!tokenEstimate || tokenEstimate <= effectiveMaxTokens / 4) return
  
  const tokenCount = await countTokensWithAPI(content)
  if (effectiveCount > effectiveMaxTokens) {
    throw new MaxFileReadTokenExceededError(effectiveCount, effectiveMaxTokens)
    // 模型会收到错误消息，建议使用 offset/limit 参数读取特定部分
  }
}
```

#### 3.4.5 重复读取去重

FileReadTool 还有一个去重机制——如果同一文件的同一范围已被读取且未修改，返回桩消息而非完整内容：

```typescript
// 去重逻辑
if (existingState && rangeMatch && mtimeMs === existingState.timestamp) {
  return { data: { type: 'file_unchanged', file: { filePath } } }
}
// 模型收到的内容：
// "[File content unchanged since your last read — see the earlier Read result in this conversation]"
```

---

## 四、Tool 的权限/危险性标记机制

### 4.1 权限体系概览

Claude Code 的权限系统是一个**多层防御**体系，不是简单的"安全/危险"二元标记：

```
                    ┌──────────────────────────────────┐
                    │     toolExecution.ts 总调度器      │
                    └───────────┬──────────────────────┘
                                │
        ┌───────────────────────┼───────────────────────────┐
        ▼                       ▼                           ▼
  1. Zod Schema 验证      2. validateInput()        3. PreToolUse Hooks
  （类型正确性）           （业务规则检查）           （用户自定义拦截）
        │                       │                           │
        ▼                       ▼                           ▼
  4. checkPermissions()   5. canUseTool()           6. PermissionContext
  （工具特定权限）         （通用权限决策）           （模式/规则/分类器）
        │                       │                           │
        └───────────────────────┼───────────────────────────┘
                                ▼
                    ┌──────────────────────┐
                    │   allow / ask / deny  │
                    └──────────────────────┘
```

### 4.2 工具自身的安全性标记

每个 Tool 通过以下方法声明自身的安全特征：

```typescript
interface Tool {
  isReadOnly(input): boolean        // 此调用是否只读
  isDestructive?(input): boolean    // 此调用是否不可逆（删除/覆盖/发送）
  isConcurrencySafe(input): boolean // 此调用是否可并发
  isOpenWorld?(input): boolean      // 是否访问外部系统
  
  // 将输入转换为安全分类器可理解的格式
  toAutoClassifierInput(input): unknown
  
  // 工具特定的权限检查（在通用检查之前执行）
  checkPermissions(input, context): Promise<PermissionResult>
}
```

**关键**：这些标记**不是静态的** — 它们依赖于 `input` 参数。例如 BashTool：

- `ls -la` → `isReadOnly: true`, `isConcurrencySafe: true`
- `rm -rf /` → `isReadOnly: false`, `isConcurrencySafe: false`, `isDestructive: true`

### 4.3 权限决策的三种结果

```typescript
// src/types/permissions.ts
type PermissionResult =
  | { behavior: 'allow'; updatedInput?: Input }      // 放行（可能修改输入）
  | { behavior: 'ask'; message: string }             // 询问用户
  | { behavior: 'deny'; message: string }            // 拒绝
  | { behavior: 'passthrough'; message: string }     // 交给通用权限系统
```

### 4.4 五种权限模式

```typescript
type PermissionMode = 
  | 'default'           // 默认：危险操作询问用户
  | 'plan'              // 计划模式：所有写操作都询问
  | 'acceptEdits'       // 接受编辑：文件修改自动允许，其他危险操作询问
  | 'bypassPermissions' // 绕过权限：一切自动允许（需要明确启用）
  | 'auto'              // 自动模式：使用 AI 分类器判断安全性
```

### 4.5 `checkPermissions` 的工具级实现对比

**FileReadTool — 简单委托**：

```typescript
async checkPermissions(input, context) {
  return checkReadPermissionForTool(FileReadTool, input, appState.toolPermissionContext)
  // 内部检查：路径是否在允许的目录内、是否匹配 deny 规则
}
```

**BashTool — 98KB 的权限逻辑**（`bashPermissions.ts`）：

```typescript
async function bashToolHasPermission(input, context) {
  // 1. 解析命令 AST
  const parsed = await parseForSecurity(input.command)
  
  // 2. 检查只读约束
  const readOnlyResult = checkReadOnlyConstraints(input, ...)
  
  // 3. 检查命令级别的 allow/deny 规则
  //    例如：Bash(git *) → allow, Bash(rm -rf *) → deny
  
  // 4. 路径验证（43KB 的 pathValidation.ts）
  //    检查命令访问的文件路径是否在允许范围内
  
  // 5. sed 编辑验证（21KB 的 sedValidation.ts）
  //    sed 命令的特殊处理，预览编辑结果
  
  // 6. 安全性分析（102KB 的 bashSecurity.ts）
  //    静态分析命令的危险性
  
  // 返回 allow / ask / deny
}
```

### 4.6 权限检查在执行流中的位置

```typescript
// src/services/tools/toolExecution.ts:599-680（简化）
async function checkPermissionsAndCallTool(tool, toolUseID, input, context, ...) {
  // Step 1: Zod Schema 验证
  const parsedInput = tool.inputSchema.safeParse(input)
  if (!parsedInput.success) return [errorMessage]
  
  // Step 2: 工具自身的输入验证
  const isValidCall = await tool.validateInput?.(parsedInput.data, context)
  if (isValidCall?.result === false) return [errorMessage]
  
  // Step 3: 预启动安全分类器（BashTool 专用，异步并行）
  startSpeculativeClassifierCheck(...)
  
  // Step 4: 运行 PreToolUse Hooks（用户自定义脚本）
  for await (const result of runPreToolUseHooks(...)) { ... }
  
  // Step 5: 工具特定的权限检查
  const permResult = await tool.checkPermissions(input, context)
  
  // Step 6: 通用权限决策（canUseTool）
  //   - 检查权限模式（default/plan/auto/...）
  //   - 匹配 allow/deny/ask 规则
  //   - auto 模式下调用 AI 分类器
  //   - 如有必要，显示权限对话框等待用户确认
  const decision = await canUseTool(tool, input, permResult, ...)
  
  // Step 7: 执行
  if (decision.behavior === 'allow') {
    const result = await tool.call(decision.updatedInput, context, ...)
    // Step 8: PostToolUse Hooks
    await runPostToolUseHooks(...)
    return [toolResultMessage]
  }
}
```

### 4.7 权限规则的配置来源

```typescript
type PermissionRuleSource =
  | 'userSettings'      // ~/.claude/settings.json
  | 'projectSettings'   // .claude/settings.json
  | 'localSettings'     // .claude/settings.local.json
  | 'flagSettings'      // GrowthBook feature flags
  | 'policySettings'    // 组织级策略
  | 'cliArg'            // CLI 参数 --allowedTools
  | 'command'           // 命令行指定
  | 'session'           // 会话内临时授权（用户点击"允许一次"）
```

规则格式示例：

```json
{
  "permissions": {
    "allow": ["Bash(git *)", "Bash(npm test)", "Read(/src/**)"],
    "deny": ["Bash(rm -rf *)", "Write(/etc/**)"],
    "ask": ["Bash(curl *)"]
  }
}
```

---

## 五、设计总结与 Test Agent 迁移建议

### 5.1 Claude Code Tool 系统的核心设计原则

| 原则                  | 实现方式                                         | 好处                      |
|---------------------|----------------------------------------------|-------------------------|
| **Fail-Closed 默认值** | `buildTool()` 工厂函数填充保守默认值                    | 新工具忘记配置时自动采取最安全行为       |
| **组合优于继承**          | 对象字面量 + 类型约束，不用 class                        | 每个 Tool 可以自由组合方法，无抽象泄漏  |
| **输入依赖的行为标记**       | `isReadOnly(input)` 而非 `isReadOnly: boolean` | 同一工具的不同调用有不同安全级别        |
| **两级输出格式化**         | 内部强类型 → API 纯文本，分离关注点                        | 内部可以传递丰富数据，发给 LLM 的信息精简 |
| **持久化而非截断**         | 大输出写磁盘 + 发预览 + 文件路径                          | LLM 可通过 FileRead 按需读取全文 |
| **确定性注册**           | 手动注册 + 固定排序                                  | prompt cache 命中率最大化     |
| **多层权限防御**          | Schema验证 → 业务验证 → Hooks → 权限检查 → 分类器         | 纵深防御，任一层失败即拦截           |

### 5.2 对 Test Agent LangGraph Tool 基类的设计建议

基于 Claude Code 的实践，为 Test Agent 的 Python/LangGraph 实现提出以下建议：

#### 5.2.1 Tool 基类设计（Python 版本）

```python
from pydantic import BaseModel
from typing import Any, Optional
from enum import Enum

class ToolSafety(str, Enum):
    READ_ONLY = "read_only"       # 只读操作，可并发
    WRITE = "write"               # 写操作，需确认
    DESTRUCTIVE = "destructive"   # 不可逆操作，强制确认
    EXTERNAL = "external"         # 外部系统交互

class ToolResult(BaseModel):
    """Tool 执行结果的统一包装"""
    data: Any                     # 强类型的输出数据
    summary: str                  # 发送给 LLM 的精简摘要
    full_output: Optional[str]    # 完整输出（可能被截断/持久化）
    error: Optional[str] = None

class BaseTool(BaseModel):
    """Tool 基类 — 借鉴 Claude Code 的对象字面量模式"""
    name: str
    description: str              # 发送给 LLM 的描述
    
    # Schema（LangGraph 通常用 Pydantic 模型）
    input_schema: type[BaseModel]
    
    # 安全标记 — 借鉴 Claude Code 的 Fail-Closed 默认值
    default_safety: ToolSafety = ToolSafety.WRITE  # 默认假设写操作
    max_output_chars: int = 30_000                  # 默认 30K 截断阈值
    
    def get_safety(self, input: BaseModel) -> ToolSafety:
        """输入依赖的安全级别（可被子类覆盖）"""
        return self.default_safety
    
    def validate_input(self, input: BaseModel) -> Optional[str]:
        """业务规则验证，返回错误消息或 None"""
        return None
    
    async def execute(self, input: BaseModel, context: "AgentContext") -> ToolResult:
        """核心执行逻辑"""
        raise NotImplementedError
    
    def format_for_llm(self, result: ToolResult) -> str:
        """将结果格式化为 LLM 可理解的文本"""
        if result.error:
            return f"<tool_error>{result.error}</tool_error>"
        if len(result.summary) > self.max_output_chars:
            # 借鉴 Claude Code：持久化 + 预览
            return self._persist_and_preview(result)
        return result.summary
```

#### 5.2.2 注册机制建议

```python
# 借鉴 Claude Code 的中央注册表模式
# 不要用自动扫描 — 保持确定性

class ToolRegistry:
    def __init__(self):
        self._tools: dict[str, BaseTool] = {}
    
    def register(self, tool: BaseTool) -> None:
        self._tools[tool.name] = tool
    
    def get_tools(self, context: "AgentContext") -> list[BaseTool]:
        """带过滤的工具列表（借鉴三层过滤）"""
        return [
            t for t in self._tools.values()
            if t.is_enabled(context)
            and t.name not in context.denied_tools
        ]

# 显式注册
registry = ToolRegistry()
registry.register(SSHCommandTool(...))
registry.register(ShowConfigTool(...))
registry.register(PingTool(...))
```

#### 5.2.3 关键迁移要点

1. **不要使用类继承层次** — 用组合（Mixin/Protocol）代替。Claude Code 60+ 个工具没有一个使用继承。

2. **安全标记必须依赖输入** — `get_safety(input)` 而非静态属性。网络 Agent 的 `ssh_command` 工具，`show version` 是只读的，`config terminal` 是危险的。

3. **输出两级格式化** — 内部用结构化数据（方便前端展示），发给 LLM 用精简文本（节省 token）。

4. **大输出持久化而非截断** — 网络设备的 `show running-config` 可能很长，截断会丢失关键信息。持久化到文件让 LLM 可以按需读取。

5. **空输出注入标记** — Claude Code 发现空 `tool_result` 会导致某些模型误判为对话终止。始终返回有意义的内容。

