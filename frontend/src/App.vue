<script setup>
import {computed, nextTick, onBeforeUnmount, ref} from 'vue'

const ws = ref(null)
const connected = ref(false)
const running = ref(false)
const input = ref('在 R1 和 R2 之间配置 OSPF 邻居，area 0，验证邻居建立成功')
const messages = ref([])
const events = ref([])
const finalState = ref(null)
const logPane = ref(null)

const wsUrl = computed(() => {
  const proto = window.location.protocol === 'https:' ? 'wss' : 'ws'
  const host = import.meta.env.VITE_API_HOST || '127.0.0.1:8000'
  return `${proto}://${host}/ws/chat`
})

const statusLabel = computed(() => {
  if (running.value) return '执行中'
  if (connected.value) return '已连接'
  return '未连接'
})

function connect() {
  if (ws.value && ws.value.readyState === WebSocket.OPEN) return
  ws.value = new WebSocket(wsUrl.value)
  ws.value.onopen = () => {
    connected.value = true
    appendSystem('WebSocket 已连接')
  }
  ws.value.onclose = () => {
    connected.value = false
    running.value = false
    appendSystem('WebSocket 已断开')
  }
  ws.value.onerror = () => {
    appendSystem('WebSocket 连接异常')
  }
  ws.value.onmessage = (event) => {
    const payload = JSON.parse(event.data)
    handleServerEvent(payload)
  }
}

function send() {
  const content = input.value.trim()
  if (!content || running.value) return
  connect()
  const socket = ws.value
  if (!socket) return
  const submit = () => {
    finalState.value = null
    running.value = true
    messages.value.push({role: 'user', content})
    socket.send(JSON.stringify({
      type: 'user_message',
      data: {content, max_turns: 30}
    }))
    scrollToBottom()
  }
  if (socket.readyState === WebSocket.OPEN) {
    submit()
  } else {
    socket.addEventListener('open', submit, {once: true})
  }
}

function handleServerEvent(payload) {
  if (payload.type === 'agent_text_delta') {
    appendAgent(payload.data.content)
  } else if (payload.type === 'tool_call_start') {
    events.value.push({
      id: payload.data.call_id,
      type: 'tool',
      state: 'running',
      toolName: payload.data.tool_name,
      arguments: payload.data.arguments,
      result: null,
      open: true
    })
  } else if (payload.type === 'tool_call_result') {
    const index = events.value.findIndex((item) => item.id === payload.data.call_id)
    if (index >= 0) {
      events.value[index] = {
        ...events.value[index],
        state: payload.data.error ? 'error' : 'done',
        result: payload.data,
        open: payload.data.error ? true : events.value[index].open
      }
    }
  } else if (payload.type === 'agent_done') {
    running.value = false
    finalState.value = payload.data
  } else if (payload.type === 'error') {
    running.value = false
    events.value.push({
      id: `error-${Date.now()}`,
      type: 'error',
      state: 'error',
      toolName: payload.data.code,
      arguments: {},
      result: payload.data,
      open: true
    })
  }
  scrollToBottom()
}

function appendAgent(content) {
  const last = messages.value[messages.value.length - 1]
  if (last && last.role === 'agent') {
    last.content += content
  } else {
    messages.value.push({role: 'agent', content})
  }
}

function appendSystem(content) {
  events.value.push({
    id: `system-${Date.now()}`,
    type: 'system',
    state: 'info',
    toolName: 'system',
    arguments: {},
    result: {summary: content},
    open: false
  })
}

function toggleEvent(item) {
  item.open = !item.open
}

function formatJson(value) {
  return JSON.stringify(value, null, 2)
}

function reasonLabel(reason) {
  const labels = {
    completed: '完成',
    max_turns: '达到最大步数',
    api_error: '模型错误',
    user_abort: '用户中断',
    context_overflow: '上下文过长'
  }
  return labels[reason] || reason || '未知'
}

async function scrollToBottom() {
  await nextTick()
  if (logPane.value) {
    logPane.value.scrollTop = logPane.value.scrollHeight
  }
}

onBeforeUnmount(() => {
  if (ws.value) ws.value.close()
})
</script>

<template>
  <main class="app-shell">
    <aside class="side-panel">
      <div>
        <p class="eyebrow">Test Agent</p>
        <h1>OSPF P0 控制台</h1>
        <p class="summary">固定拓扑、实时工具输出、Mock/真实设备双轨验证。</p>
      </div>

      <div class="status-block">
        <div class="status-row">
          <span>连接状态</span>
          <strong :class="['pill', connected ? 'pill-ok' : 'pill-muted']">{{ statusLabel }}</strong>
        </div>
        <div class="status-row">
          <span>拓扑</span>
          <strong>R1 / R2 / R3</strong>
        </div>
        <div class="status-row">
          <span>执行上限</span>
          <strong>30 turns</strong>
        </div>
      </div>

      <div class="topology-box">
        <div class="topology-link">R1 GE0/0/1 - R2 GE0/0/1</div>
        <div class="topology-link">R1 GE0/0/2 - R3 GE0/0/1</div>
        <div class="topology-link">R2 GE0/0/2 - R3 GE0/0/2</div>
      </div>
    </aside>

    <section class="workspace">
      <div ref="logPane" class="log-pane">
        <article v-for="(message, index) in messages" :key="index" :class="['message', message.role]">
          <div class="message-role">{{ message.role === 'user' ? '用户' : 'Agent' }}</div>
          <div class="message-content">{{ message.content }}</div>
        </article>

        <article v-for="item in events" :key="item.id" :class="['event-card', item.state]">
          <button class="event-head" type="button" @click="toggleEvent(item)">
            <span class="event-title">{{ item.toolName }}</span>
            <span class="event-state">{{ item.state }}</span>
          </button>
          <div v-if="item.open" class="event-body">
            <label>入参</label>
            <pre>{{ formatJson(item.arguments) }}</pre>
            <label>结果</label>
            <pre>{{ formatJson(item.result) }}</pre>
          </div>
        </article>

        <div v-if="finalState" class="final-state">
          本轮状态：{{ reasonLabel(finalState.reason) }}，执行轮次 {{ finalState.turn_count }}
        </div>
      </div>

      <form class="composer" @submit.prevent="send">
        <textarea
            v-model="input"
            :disabled="running"
            rows="3"
            placeholder="输入测试或配置需求"
        />
        <div class="composer-actions">
          <button type="button" class="secondary" @click="connect">连接</button>
          <button type="submit" class="primary" :disabled="running || !input.trim()">
            {{ running ? '执行中' : '发送' }}
          </button>
        </div>
      </form>
    </section>
  </main>
</template>
