<!--
  ============================================================
  ChatView.vue —— 聊天主界面（§4.2 完整实现）
  - 左侧栏：品牌 / 新对话 / 能力清单 / 后端实时健康状态
  - 右主区：免责声明横幅 + 消息流（空状态 / 气泡）+ 输入栏
  - 集成 POST /api/consult，渲染 Markdown / 标签 / 急症警告 / 免责声明 / 耗时
  ============================================================
-->
<script setup>
import { ref, nextTick, onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import ChatMessage from '@/components/ChatMessage.vue'
import DisclaimerBanner from '@/components/DisclaimerBanner.vue'
import {
  consult, consultStream, health,
  listConversations, getConversation, deleteConversation
} from '@/api/index.js'

// localStorage 键：记住"当前看哪个对话"（数据唯一来源是后端）
const SESSION_KEY = 'smc_session_id'

// ---------- 状态 ----------
const messages = ref([])
const input = ref('')
const loading = ref(false)
const sidebarOpen = ref(false)
const chatArea = ref(null)

// 会话 ID（一次会话一个，新对话时重置）
const newId = () =>
  typeof crypto !== 'undefined' && crypto.randomUUID
    ? crypto.randomUUID()
    : 'sess-' + Date.now() + '-' + Math.random().toString(36).slice(2)
const sessionId = ref(localStorage.getItem(SESSION_KEY) || newId())

// 对话历史列表（后端已倒序；前端只存元数据，内容点开才加载）
const conversations = ref([])

// 示例问题
const sampleQuestions = [
  '我最近头痛、头晕，应该挂什么科？',
  '高血压吃什么药好？',
  '什么是糖尿病？',
  '我胸痛、呼吸困难怎么办？'
]

// 能力清单
const capabilities = [
  { icon: 'OfficeBuilding', title: '看病挂号', desc: '按症状推荐就诊科室' },
  { icon: 'FirstAidKit', title: '用药建议', desc: '药物 / 副作用 / 禁忌' },
  { icon: 'Reading', title: '医学知识', desc: '疾病科普与解读' },
  { icon: 'WarningFilled', title: '急症识别', desc: '危险信号即时预警' }
]

// 后端健康状态
const healthState = ref({ checked: false, neo4j: false, vector: false, agent: false })

async function loadHealth() {
  try {
    const { data } = await health()
    healthState.value = {
      checked: true,
      neo4j: !!data.neo4j_connected,
      vector: !!data.vector_index_loaded,
      agent: !!data.agent_system_ready
    }
  } catch {
    healthState.value = { checked: true, neo4j: false, vector: false, agent: false }
  }
}

const healthRows = () => [
  { label: 'Neo4j 图谱', ok: healthState.value.neo4j },
  { label: '向量索引', ok: healthState.value.vector },
  { label: 'Agent 系统', ok: healthState.value.agent }
]

// ---------- 滚动 ----------
function scrollBottom() {
  nextTick(() => {
    const el = chatArea.value
    if (el) el.scrollTo({ top: el.scrollHeight, behavior: 'smooth' })
  })
}

// ---------- 发送（默认走 SSE 流式，失败自动降级为非流式 /consult） ----------
async function send(text) {
  const query = (text ?? input.value).trim()
  if (!query || loading.value) return

  // 用户消息
  messages.value.push({ role: 'user', content: query })
  // 占位 AI 消息（思考中 + 流式进度）
  // 注意：必须从数组取回响应式代理；若直接改动 push 前的原始对象引用，Vue 不会触发更新
  messages.value.push({ role: 'assistant', pending: true, progressSteps: [] })
  const aiMsg = messages.value[messages.value.length - 1]
  input.value = ''
  loading.value = true
  sidebarOpen.value = false
  scrollBottom()

  try {
    await consultStream(query, sessionId.value, {
      onProgress: (p) => {
        // 每个 Agent 节点完成 → 追加进度标签（整体替换数组触发响应式更新）
        aiMsg.progressSteps = [...(aiMsg.progressSteps || []), p]
        scrollBottom()
      },
      onAnswer: (data) => applyAnswer(aiMsg, data),
      onError: (e) => {
        aiMsg.pending = false
        aiMsg.error = e?.message || '流式响应出错'
        ElMessage.error(aiMsg.error)
      }
    })
    // 流正常结束但一帧 answer 都没收到 → 走非流式兜底
    if (aiMsg.pending) await fallbackConsult(query, aiMsg)
  } catch (err) {
    // SSE 连接本身失败（网络异常 / 503 / 旧后端无此端点）→ 自动降级
    if (aiMsg.pending) {
      aiMsg.progressSteps = []
      await fallbackConsult(query, aiMsg, err)
    }
  } finally {
    loading.value = false
    scrollBottom()
    loadConversations()  // 每轮结束后刷新历史列表的顺序与标题
  }
}

// 把终答帧/非流式响应写入消息（两个路径共用字段口径）
function applyAnswer(aiMsg, data) {
  Object.assign(aiMsg, {
    pending: false,
    content: data.answer || '',
    intent: data.intent || '',
    symptoms: data.symptoms || [],
    departments: data.departments || [],
    medications: data.medications || [],
    disclaimers: data.disclaimers || [],
    warnings: data.warnings || [],
    linked_entities: data.linked_entities || [],
    duration_ms: data.duration_ms || 0
  })
}

// 非流式降级路径（保留原有 /consult）
async function fallbackConsult(query, aiMsg, prevErr) {
  try {
    const { data } = await consult(query, sessionId.value)
    applyAnswer(aiMsg, data)
  } catch (err) {
    aiMsg.pending = false
    aiMsg.error = friendlyError(prevErr || err)
    ElMessage.error(aiMsg.error)
  }
}

// 区分超时 / 网络 / 服务不可用
function friendlyError(err) {
  const status = err?.response?.status
  if (err?.code === 'ECONNABORTED' || /timeout/i.test(err?.message || ''))
    return '请求超时，模型可能繁忙，请稍后重试。'
  if (status === 504) return '后端处理超时，请简化问题后重试。'
  if (status === 503) return '服务暂不可用，请稍后再试。'
  if (!err?.response) return '无法连接后端，请确认已启动 FastAPI（:8000）。'
  return `请求失败（${status}），请稍后重试。`
}

function newConversation() {
  if (loading.value) return
  messages.value = []
  sessionId.value = newId()
  localStorage.setItem(SESSION_KEY, sessionId.value)
  sidebarOpen.value = false
}

// ---------- 对话历史（后端 Redis+MySQL，前端只认 §6.2 契约） ----------
async function loadConversations() {
  try {
    const { data } = await listConversations()
    conversations.value = data.conversations || []
  } catch {
    conversations.value = []  // 后端历史服务不可用时不影响主聊天链路
  }
}

// 把后端消息映射为 ChatMessage 可渲染的消息对象（缺省字段由组件 v-if 兜底）
const toMsg = (m) => ({ role: m.role, content: m.content, intent: m.intent || '' })

async function openConversation(id) {
  if (loading.value || id === sessionId.value) return
  try {
    const { data } = await getConversation(id)
    messages.value = (data.messages || []).map(toMsg)
    sessionId.value = id
    localStorage.setItem(SESSION_KEY, id)
    sidebarOpen.value = false
    scrollBottom()
  } catch {
    ElMessage.warning('恢复对话失败，该对话可能已被删除')
    await loadConversations()
  }
}

async function removeConversation(id) {
  try {
    await ElMessageBox.confirm('删除后无法恢复，确定删除该对话？', '删除对话', {
      confirmButtonText: '删除',
      cancelButtonText: '取消',
      type: 'warning'
    })
  } catch {
    return  // 取消删除
  }
  try {
    await deleteConversation(id)
    if (id === sessionId.value) {  // 删的是当前对话 → 回欢迎页并发新 id
      messages.value = []
      sessionId.value = newId()
      localStorage.setItem(SESSION_KEY, sessionId.value)
    }
    await loadConversations()
    ElMessage.success('已删除对话')
  } catch {
    ElMessage.error('删除失败，请稍后重试')
  }
}

// 刷新页面后恢复当前对话；列表为空或 id 失效则回欢迎页
async function restoreSession() {
  const saved = localStorage.getItem(SESSION_KEY)
  if (!saved) return
  try {
    const { data } = await getConversation(saved)
    if ((data.messages || []).length) {
      messages.value = data.messages.map(toMsg)
      sessionId.value = saved
      scrollBottom()
    }
  } catch {
    sessionId.value = newId()
    localStorage.setItem(SESSION_KEY, sessionId.value)
  }
}

onMounted(async () => {
  loadHealth()
  await loadConversations()
  await restoreSession()
})
</script>

<template>
  <div class="app-shell">
    <!-- 环境氛围层 -->
    <div class="ambient" aria-hidden="true">
      <span class="glow glow-a"></span>
      <span class="glow glow-b"></span>
      <span class="cross-pattern"></span>
    </div>

    <!-- 移动端遮罩 -->
    <div v-if="sidebarOpen" class="backdrop" @click="sidebarOpen = false"></div>

    <div class="layout">
      <!-- ===================== 左侧栏 ===================== -->
      <aside class="sidebar" :class="{ open: sidebarOpen }">
        <button class="side-close" @click="sidebarOpen = false">✕</button>

        <div class="brand">
          <span class="brand-mark"><el-icon :size="24"><FirstAidKit /></el-icon></span>
          <div>
            <h1 class="brand-name">智慧问诊Agent系统</h1>
            <p class="brand-sub">智能医疗 · 知识图谱驱动</p>
          </div>
        </div>

        <button class="new-conv" @click="newConversation">
          <el-icon><EditPen /></el-icon>
          开启新对话
        </button>

        <div class="hist-block">
          <div class="block-title">对话历史</div>
          <div v-if="conversations.length === 0" class="hist-empty">暂无历史对话</div>
          <div v-else class="hist-list">
            <div
              v-for="c in conversations"
              :key="c.id"
              class="hist-item"
              :class="{ active: c.id === sessionId }"
              :title="c.title"
              @click="openConversation(c.id)"
            >
              <el-icon class="hist-ico"><ChatLineRound /></el-icon>
              <span class="hist-title">{{ c.title }}</span>
              <button class="hist-del" title="删除该对话" @click.stop="removeConversation(c.id)">
                <el-icon><Delete /></el-icon>
              </button>
            </div>
          </div>
        </div>

        <div class="cap-block">
          <div class="block-title">我能帮您</div>
          <div v-for="c in capabilities" :key="c.title" class="cap-item">
            <span class="cap-icon"><el-icon><component :is="c.icon" /></el-icon></span>
            <div>
              <div class="cap-name">{{ c.title }}</div>
              <div class="cap-desc">{{ c.desc }}</div>
            </div>
          </div>
        </div>

        <div class="health-card">
          <div class="health-head">
            <span class="block-title" style="margin: 0">系统状态</span>
            <button class="refresh-btn" title="刷新" @click="loadHealth">
              <el-icon><Refresh /></el-icon>
            </button>
          </div>
          <div v-if="!healthState.checked" class="health-row">
            <span class="dot dot-pending"></span>检测中…
          </div>
          <template v-else>
            <div v-for="r in healthRows()" :key="r.label" class="health-row">
              <span class="dot" :class="r.ok ? 'dot-ok' : 'dot-off'"></span>
              {{ r.label }}
              <span class="health-tag" :class="r.ok ? 'ok' : 'off'">{{ r.ok ? '正常' : '离线' }}</span>
            </div>
          </template>
        </div>

        <div class="side-foot">v1.0.0 · 仅供参考，请遵医嘱</div>
      </aside>

      <!-- ===================== 右主区 ===================== -->
      <section class="main">
        <div class="main-top">
          <button class="menu-btn" @click="sidebarOpen = true">☰</button>
          <span class="top-title">智慧问诊Agent系统</span>
        </div>

        <DisclaimerBanner />

        <div class="chat-area" ref="chatArea">
          <!-- 空状态 -->
          <div v-if="messages.length === 0" class="empty-state">
            <div class="empty-pulse" aria-hidden="true">
              <el-icon :size="40"><Service /></el-icon>
            </div>
            <h2 class="empty-title">有什么可以帮您？</h2>
            <p class="empty-desc">
              描述您的症状，或询问用药、医学知识，我会为您分析并给出就医建议。
            </p>
            <div class="samples">
              <button
                v-for="q in sampleQuestions"
                :key="q"
                class="sample-chip"
                @click="send(q)"
              >
                <el-icon><ChatDotRound /></el-icon>
                {{ q }}
              </button>
            </div>
          </div>

          <!-- 消息流 -->
          <div v-else class="messages">
            <ChatMessage v-for="(m, i) in messages" :key="i" :msg="m" />
          </div>
        </div>

        <footer class="input-bar">
          <el-input
            v-model="input"
            class="chat-input"
            size="large"
            :disabled="loading"
            placeholder="请描述您的症状或健康问题，回车发送…"
            @keyup.enter="send()"
          >
            <template #prefix><el-icon><EditPen /></el-icon></template>
          </el-input>
          <el-button
            class="send-btn"
            type="primary"
            size="large"
            :loading="loading"
            @click="send()"
          >
            <el-icon v-if="!loading"><Promotion /></el-icon>
            <span>{{ loading ? '思考中' : '发送' }}</span>
          </el-button>
        </footer>
      </section>
    </div>
  </div>
</template>

<style scoped>
.app-shell { position: relative; height: 100%; overflow: hidden; }

/* 环境氛围 */
.ambient { position: absolute; inset: 0; pointer-events: none; overflow: hidden; }
.glow { position: absolute; border-radius: 50%; filter: blur(90px); opacity: 0.5; }
.glow-a { width: 520px; height: 520px; top: -180px; left: -140px;
  background: radial-gradient(circle, rgba(20, 184, 166, 0.32), transparent 70%);
  animation: drift 18s ease-in-out infinite alternate; }
.glow-b { width: 460px; height: 460px; bottom: -160px; right: -120px;
  background: radial-gradient(circle, rgba(232, 137, 107, 0.26), transparent 70%);
  animation: drift 22s ease-in-out infinite alternate-reverse; }
.cross-pattern { position: absolute; inset: 0;
  background-image: linear-gradient(rgba(15,118,110,.05) 2px, transparent 2px),
    linear-gradient(90deg, rgba(15,118,110,.05) 2px, transparent 2px);
  background-size: 44px 44px;
  mask-image: radial-gradient(ellipse at 50% 0%, black 0%, transparent 80%); }
@keyframes drift { from { transform: translate(0,0) scale(1); } to { transform: translate(60px,40px) scale(1.12); } }

.layout {
  position: relative; z-index: 1; height: 100%;
  max-width: 1240px; margin: 0 auto; display: flex; gap: 18px; padding: 18px;
}

/* ---------- 侧边栏 ---------- */
.sidebar {
  width: 288px; flex: none; display: flex; flex-direction: column; gap: 16px;
  padding: 20px 18px; border-radius: 20px;
  background: rgba(255, 255, 255, 0.82); backdrop-filter: blur(10px);
  border: 1px solid rgba(15, 118, 110, 0.12);
  box-shadow: 0 12px 36px rgba(11, 61, 58, 0.08);
}
.side-close { display: none; }

.brand { display: flex; align-items: center; gap: 12px; }
.brand-mark { display: grid; place-items: center; width: 48px; height: 48px;
  border-radius: 14px; color: #fff;
  background: linear-gradient(145deg, var(--teal-600), var(--teal-900));
  box-shadow: 0 6px 16px rgba(11, 61, 58, 0.28);
  animation: heartbeat 2.6s ease-in-out infinite; }
@keyframes heartbeat { 0%,100%{transform:scale(1)} 14%{transform:scale(1.08)} 28%{transform:scale(1)} 42%{transform:scale(1.06)} 56%{transform:scale(1)} }
.brand-name { font-family: var(--font-display); font-size: 19px; font-weight: 900; color: var(--teal-900); }
.brand-sub { font-size: 11px; color: #5c8480; letter-spacing: 0.06em; margin-top: 2px; }

.new-conv {
  display: flex; align-items: center; justify-content: center; gap: 8px;
  width: 100%; padding: 12px; border: none; border-radius: 14px; cursor: pointer;
  color: #fff; font-size: 14px; font-weight: 700; font-family: inherit;
  background: linear-gradient(145deg, var(--teal-500), var(--teal-700));
  box-shadow: 0 6px 18px rgba(15, 118, 110, 0.3);
  transition: transform 0.15s, box-shadow 0.15s;
}
.new-conv:hover { transform: translateY(-2px); box-shadow: 0 9px 22px rgba(15, 118, 110, 0.4); }

.block-title { font-size: 12px; font-weight: 700; letter-spacing: 0.1em; color: #6b918d;
  text-transform: uppercase; margin-bottom: 10px; }

/* ---------- 对话历史栏（DeepSeek 式布局，沿用绿色医疗风格） ---------- */
.hist-block { display: flex; flex-direction: column; min-height: 0; }
.hist-empty { font-size: 12px; color: #8aa6a2; padding: 4px 8px; }
.hist-list { display: flex; flex-direction: column; gap: 2px;
  overflow-y: auto; max-height: 240px; margin: -4px; padding: 4px; }
.hist-item { position: relative; display: flex; align-items: center; gap: 8px;
  padding: 8px 10px; border-radius: 10px; cursor: pointer;
  color: #46605c; font-size: 13px; transition: background 0.15s; }
.hist-item:hover { background: rgba(217, 242, 236, 0.6); }
.hist-item.active { background: var(--mint); color: #0b3d3a; font-weight: 600; }
.hist-ico { flex: none; color: #7a9894; }
.hist-item.active .hist-ico { color: var(--teal-700); }
.hist-title { flex: 1; min-width: 0; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.hist-del { display: none; flex: none; border: none; background: transparent; cursor: pointer;
  color: #8aa6a2; padding: 2px; border-radius: 6px; }
.hist-del:hover { color: #b91c1c; background: rgba(185, 28, 28, 0.08); }
.hist-item:hover .hist-del { display: grid; place-items: center; }

.cap-block { display: flex; flex-direction: column; }
.cap-item { display: flex; gap: 11px; padding: 9px 8px; border-radius: 12px;
  transition: background 0.18s; }
.cap-item:hover { background: rgba(217, 242, 236, 0.6); }
.cap-icon { flex: none; display: grid; place-items: center; width: 34px; height: 34px;
  border-radius: 10px; color: var(--teal-700); background: var(--mint); }
.cap-name { font-size: 14px; font-weight: 600; color: var(--ink); }
.cap-desc { font-size: 12px; color: #7a9894; margin-top: 1px; }

.health-card { margin-top: auto; padding: 14px; border-radius: 14px;
  background: rgba(217, 242, 236, 0.45); border: 1px solid rgba(15,118,110,.12); }
.health-head { display: flex; align-items: center; justify-content: space-between; margin-bottom: 8px; }
.refresh-btn { border: none; background: transparent; color: #6b918d; cursor: pointer;
  display: grid; place-items: center; border-radius: 8px; padding: 4px; transition: background 0.15s, color 0.15s; }
.refresh-btn:hover { background: rgba(15,118,110,.12); color: var(--teal-700); }
.health-row { display: flex; align-items: center; gap: 8px; font-size: 13px; color: #46605c; padding: 3px 0; }
.dot { width: 8px; height: 8px; border-radius: 50%; flex: none; }
.dot-ok { background: #2f9e44; box-shadow: 0 0 0 0 rgba(47,158,68,.5); animation: ping 1.8s infinite; }
.dot-off { background: #c0c4c2; }
.dot-pending { background: #e0a020; animation: ping 1s infinite; }
@keyframes ping { 0%{box-shadow:0 0 0 0 rgba(47,158,68,.4)} 70%{box-shadow:0 0 0 6px rgba(47,158,68,0)} 100%{box-shadow:0 0 0 0 rgba(47,158,68,0)} }
.health-tag { margin-left: auto; font-size: 11px; font-weight: 600; padding: 1px 8px; border-radius: 999px; }
.health-tag.ok { color: #2f9e44; background: rgba(47,158,68,.12); }
.health-tag.off { color: #b08900; background: rgba(224,160,32,.16); }

.side-foot { font-size: 11px; color: #8aa6a2; text-align: center; }

/* ---------- 主区 ---------- */
.main { flex: 1; min-width: 0; display: flex; flex-direction: column; gap: 12px;
  padding: 16px 18px; border-radius: 20px;
  background: rgba(255, 255, 255, 0.72); backdrop-filter: blur(8px);
  border: 1px solid rgba(15, 118, 110, 0.12); box-shadow: 0 12px 36px rgba(11, 61, 58, 0.08); }
.main-top { display: none; align-items: center; gap: 10px; }
.menu-btn { border: 1px solid rgba(15,118,110,.2); background: #fff; border-radius: 10px;
  width: 38px; height: 38px; font-size: 18px; cursor: pointer; color: var(--teal-700); }
.top-title { font-family: var(--font-display); font-weight: 900; font-size: 17px; color: var(--teal-900); }

.chat-area { flex: 1; min-height: 0; overflow-y: auto; padding: 6px 6px 6px 2px; scroll-behavior: smooth; }
.messages { padding: 6px 4px; }

/* 空状态 */
.empty-state { height: 100%; display: flex; flex-direction: column; align-items: center;
  justify-content: center; text-align: center; padding: 30px 20px; gap: 8px;
  animation: rise 0.6s ease both; }
@keyframes rise { from { opacity: 0; transform: translateY(16px); } to { opacity: 1; transform: none; } }
.empty-pulse { display: grid; place-items: center; width: 84px; height: 84px; border-radius: 50%;
  color: var(--teal-600); background: var(--mint); position: relative; margin-bottom: 6px; }
.empty-pulse::after { content: ''; position: absolute; inset: 0; border-radius: 50%;
  border: 2px solid rgba(20,184,166,.5); animation: ripple 2.4s ease-out infinite; }
@keyframes ripple { from { transform: scale(1); opacity: 0.8; } to { transform: scale(1.65); opacity: 0; } }
.empty-title { font-family: var(--font-display); font-size: 30px; font-weight: 900; color: var(--teal-900); }
.empty-desc { max-width: 440px; font-size: 14px; line-height: 1.7; color: #5c8480; }
.samples { display: flex; flex-wrap: wrap; justify-content: center; gap: 10px; margin-top: 18px; max-width: 580px; }
.sample-chip { display: inline-flex; align-items: center; gap: 6px; padding: 9px 16px; border-radius: 999px;
  border: 1px solid rgba(15,118,110,.28); background: #fff; color: var(--teal-700);
  font-size: 13px; font-family: inherit; cursor: pointer;
  transition: transform 0.18s, box-shadow 0.18s, background 0.18s; }
.sample-chip:hover { transform: translateY(-2px); background: var(--mint); box-shadow: 0 6px 16px rgba(15,118,110,.16); }

/* 输入栏 */
.input-bar { display: flex; gap: 12px; }
.chat-input { flex: 1; }
.chat-input :deep(.el-input__wrapper) { border-radius: 14px; box-shadow: 0 4px 16px rgba(11,61,58,.08); padding: 4px 14px; }
.send-btn { border-radius: 14px; padding: 0 26px; height: auto;
  background: linear-gradient(145deg, var(--teal-500), var(--teal-700)); border: none;
  box-shadow: 0 6px 18px rgba(15,118,110,.3); transition: transform 0.15s, box-shadow 0.15s; }
.send-btn:hover { transform: translateY(-1px); box-shadow: 0 8px 22px rgba(15,118,110,.4); }

.backdrop { display: none; }

/* ---------- 响应式 ---------- */
@media (max-width: 900px) {
  .layout { padding: 0; gap: 0; }
  .main { border-radius: 0; border: none; box-shadow: none; padding: 14px; }
  .main-top { display: flex; }
  .backdrop { display: block; position: fixed; inset: 0; background: rgba(8, 30, 28, 0.4); z-index: 25; }
  .sidebar { position: fixed; left: 0; top: 0; height: 100%; z-index: 30; width: 82%; max-width: 300px;
    border-radius: 0 20px 20px 0; transform: translateX(-105%); transition: transform 0.3s ease; }
  .sidebar.open { transform: translateX(0); }
  .side-close { display: grid; place-items: center; position: absolute; top: 14px; right: 14px;
    width: 30px; height: 30px; border: none; background: rgba(15,118,110,.1); border-radius: 8px;
    color: var(--teal-700); cursor: pointer; font-size: 14px; }
  .empty-title { font-size: 24px; }
}
</style>
