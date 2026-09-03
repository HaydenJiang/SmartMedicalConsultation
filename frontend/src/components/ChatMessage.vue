<!--
  ChatMessage.vue —— 单条消息气泡
  - 用户消息：右侧青绿渐变气泡
  - AI 消息：左侧卡片 + 头像，含 Markdown 正文 / 症状·科室·药物标签 / 急症警告 / 免责声明 / 耗时元信息
  - 思考中：跳动圆点动画
  - 失败：红色错误块 + 重试提示
-->
<script setup>
import { ref, computed } from 'vue'
import { ElMessage } from 'element-plus'
import { renderMarkdown } from '@/utils/markdown.js'

const props = defineProps({
  msg: { type: Object, required: true }
})

const copied = ref(false)

// 流式进度：思考文案跟随最新完成的节点
const thinkingLabel = computed(() => {
  const steps = props.msg.progressSteps || []
  return steps.length ? `正在${steps[steps.length - 1].label}…` : '正在为您分析…'
})

async function copyAnswer() {
  try {
    await navigator.clipboard.writeText(props.msg.content || '')
    copied.value = true
    ElMessage.success('已复制回答')
    setTimeout(() => (copied.value = false), 1600)
  } catch {
    ElMessage.warning('复制失败，请手动选择')
  }
}

// 意图类型 -> 中文标签
const INTENT_LABEL = {
  appointment: '看病挂号',
  medication: '用药建议',
  knowledge: '医学知识',
  emergency: '急症识别',
  general: '通用对话'
}
</script>

<template>
  <!-- ===================== 用户消息 ===================== -->
  <div v-if="msg.role === 'user'" class="row row-user">
    <div class="bubble-user">{{ msg.content }}</div>
  </div>

  <!-- ===================== AI 消息 ===================== -->
  <div v-else class="row row-ai">
    <div class="avatar-ai">
      <el-icon :size="20"><FirstAidKit /></el-icon>
    </div>

    <div class="ai-body">
      <!-- 思考中（流式：节点进度轨迹 + 跳动圆点） -->
      <div v-if="msg.pending" class="thinking-wrap">
        <div class="thinking">
          <span class="dot"></span><span class="dot"></span><span class="dot"></span>
          <span class="thinking-text">{{ thinkingLabel }}</span>
        </div>
        <div v-if="msg.progressSteps && msg.progressSteps.length" class="progress-trail">
          <span v-for="(p, i) in msg.progressSteps" :key="i" class="progress-chip">
            ✓ {{ p.label }}
          </span>
        </div>
      </div>

      <!-- 失败 -->
      <div v-else-if="msg.error" class="bubble-error">
        <el-icon><WarningFilled /></el-icon>
        <span>{{ msg.error }}</span>
      </div>

      <!-- 正常回答 -->
      <template v-else>
        <!-- 急症警告：置顶、醒目、脉冲 -->
        <el-alert
          v-for="(w, i) in msg.warnings"
          :key="'w' + i"
          class="warn-alert"
          type="error"
          :title="w"
          show-icon
          :closable="false"
        />

        <div class="bubble-ai">
          <div class="ai-name">智慧问诊Agent系统</div>

          <!-- Markdown 正文 -->
          <div class="md" v-html="renderMarkdown(msg.content)"></div>

          <!-- 标签区 -->
          <div
            v-if="
              (msg.symptoms && msg.symptoms.length) ||
              (msg.departments && msg.departments.length) ||
              (msg.medications && msg.medications.length) ||
              (msg.linked_entities && msg.linked_entities.length)
            "
            class="tags"
          >
            <div v-if="msg.linked_entities && msg.linked_entities.length" class="tag-group">
              <span class="tag-label">知识定位</span>
              <el-tag
                v-for="lk in msg.linked_entities"
                :key="lk.input_entity + '→' + lk.matched_entity"
                type="primary"
                class="pill"
                size="small"
                :title="`用户表述「${lk.input_entity}」→ 图谱实体「${lk.matched_entity}」，相似度 ${lk.similarity}`"
              >
                {{ lk.matched_entity }}（{{ lk.type }}，{{ Math.round(lk.similarity * 100) }}%）
              </el-tag>
            </div>
            <div v-if="msg.symptoms && msg.symptoms.length" class="tag-group">
              <span class="tag-label">症状</span>
              <el-tag v-for="s in msg.symptoms" :key="s" type="info" class="pill" size="small">
                {{ s }}
              </el-tag>
            </div>
            <div v-if="msg.departments && msg.departments.length" class="tag-group">
              <span class="tag-label">推荐科室</span>
              <el-tag v-for="d in msg.departments" :key="d" type="success" class="pill" size="small">
                {{ d }}
              </el-tag>
            </div>
            <div v-if="msg.medications && msg.medications.length" class="tag-group">
              <span class="tag-label">相关药物</span>
              <el-tag
                v-for="m in msg.medications"
                :key="m.name || m"
                type="warning"
                class="pill"
                size="small"
              >
                {{ m.name || m }}
              </el-tag>
            </div>
          </div>

          <!-- 免责声明：黄色提示块 -->
          <div v-if="msg.disclaimers && msg.disclaimers.length" class="disclaimer-box">
            <el-icon class="disclaimer-icon"><InfoFilled /></el-icon>
            <ul>
              <li v-for="(d, i) in msg.disclaimers" :key="'d' + i">{{ d }}</li>
            </ul>
          </div>
        </div>

        <!-- 元信息：耗时 + 意图 + 复制 -->
        <div class="meta">
          <span v-if="msg.duration_ms" class="meta-item">
            <el-icon><Timer /></el-icon>{{ msg.duration_ms }} ms
          </span>
          <span v-if="msg.intent && INTENT_LABEL[msg.intent]" class="meta-chip">
            {{ INTENT_LABEL[msg.intent] }}
          </span>
          <button class="copy-btn" :class="{ copied }" @click="copyAnswer">
            <el-icon><Check v-if="copied" /><DocumentCopy v-else /></el-icon>
            {{ copied ? '已复制' : '复制' }}
          </button>
        </div>
      </template>
    </div>
  </div>
</template>

<style scoped>
.row {
  display: flex;
  gap: 12px;
  margin-bottom: 20px;
  animation: msg-in 0.35s cubic-bezier(0.2, 0.8, 0.2, 1) both;
}

@keyframes msg-in {
  from { opacity: 0; transform: translateY(12px); }
  to   { opacity: 1; transform: translateY(0); }
}

/* ---------- 用户气泡 ---------- */
.row-user { justify-content: flex-end; }

.bubble-user {
  max-width: 76%;
  padding: 12px 16px;
  border-radius: 18px 18px 6px 18px;
  color: #fff;
  font-size: 15px;
  line-height: 1.65;
  white-space: pre-wrap;
  word-break: break-word;
  background: linear-gradient(145deg, var(--teal-500), var(--teal-700));
  box-shadow: 0 6px 18px rgba(15, 118, 110, 0.28);
}

/* ---------- AI 布局 ---------- */
.row-ai { align-items: flex-start; }

.avatar-ai {
  flex: none;
  display: grid;
  place-items: center;
  width: 38px;
  height: 38px;
  border-radius: 12px;
  color: #fff;
  background: linear-gradient(145deg, var(--teal-600), var(--teal-900));
  box-shadow: 0 4px 12px rgba(11, 61, 58, 0.25);
}

.ai-body { flex: 1; min-width: 0; }

.ai-name {
  margin-bottom: 6px;
  font-size: 12px;
  font-weight: 700;
  letter-spacing: 0.12em;
  color: var(--teal-700);
  text-transform: uppercase;
}

.bubble-ai {
  position: relative;
  padding: 14px 18px;
  border-radius: 4px 18px 18px 18px;
  background: #fff;
  border: 1px solid rgba(15, 118, 110, 0.12);
  border-left: 4px solid var(--teal-500);
  box-shadow: 0 8px 24px rgba(11, 61, 58, 0.07);
}

/* ---------- 思考动画 ---------- */
.thinking-wrap {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

/* 流式进度轨迹：每个完成的 Agent 节点一枚 chip */
.progress-trail {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  padding-left: 2px;
}
.progress-chip {
  padding: 2px 10px;
  border-radius: 999px;
  font-size: 12px;
  color: var(--teal-700);
  background: var(--mint);
  border: 1px solid rgba(15, 118, 110, 0.18);
  animation: msg-in 0.3s ease both;
}

.thinking {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 14px 18px;
  border-radius: 4px 18px 18px 18px;
  background: #fff;
  border: 1px solid rgba(15, 118, 110, 0.12);
  border-left: 4px solid var(--teal-500);
  box-shadow: 0 8px 24px rgba(11, 61, 58, 0.07);
}

.thinking .dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: var(--teal-500);
  animation: bounce 1.2s infinite ease-in-out;
}
.thinking .dot:nth-child(2) { animation-delay: 0.18s; }
.thinking .dot:nth-child(3) { animation-delay: 0.36s; }
.thinking-text {
  margin-left: 6px;
  font-size: 14px;
  color: #5c8480;
}

@keyframes bounce {
  0%, 80%, 100% { transform: translateY(0); opacity: 0.4; }
  40% { transform: translateY(-7px); opacity: 1; }
}

/* ---------- 错误 ---------- */
.bubble-error {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  padding: 12px 16px;
  border-radius: 12px;
  color: #b91c1c;
  background: #fef2f2;
  border: 1px solid #fecaca;
  font-size: 14px;
}

/* ---------- 急症警告 ---------- */
.warn-alert {
  margin-bottom: 10px;
  border-radius: 12px;
  animation: warn-pulse 2s ease-in-out infinite;
}

@keyframes warn-pulse {
  0%, 100% { box-shadow: 0 0 0 0 rgba(220, 38, 38, 0); }
  50%      { box-shadow: 0 0 0 4px rgba(220, 38, 38, 0.12); }
}

/* ---------- 标签区 ---------- */
.tags {
  margin-top: 14px;
  padding-top: 12px;
  border-top: 1px dashed rgba(15, 118, 110, 0.18);
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.tag-group {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 6px;
}

.tag-label {
  font-size: 12px;
  font-weight: 600;
  color: #6b918d;
  margin-right: 2px;
}

.pill {
  border-radius: 999px;
}
.pill::before {
  content: '';
  display: inline-block;
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: currentColor;
  margin-right: 6px;
  vertical-align: middle;
}

/* ---------- 免责声明块 ---------- */
.disclaimer-box {
  display: flex;
  gap: 10px;
  margin-top: 12px;
  padding: 10px 14px;
  border-radius: 12px;
  background: #fff8ec;
  border: 1px solid #f5dca3;
  color: #92630a;
  font-size: 13px;
  line-height: 1.6;
}

.disclaimer-icon {
  flex: none;
  margin-top: 2px;
  font-size: 16px;
  color: #e0a020;
}

.disclaimer-box ul {
  list-style: none;
  margin: 0;
  padding: 0;
}
.disclaimer-box li + li { margin-top: 4px; }

/* ---------- 元信息 ---------- */
.meta {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-top: 8px;
  padding-left: 2px;
  font-size: 12px;
  color: #8aa6a2;
}

.meta-item {
  display: inline-flex;
  align-items: center;
  gap: 3px;
}

.meta-chip {
  padding: 1px 9px;
  border-radius: 999px;
  background: var(--mint);
  color: var(--teal-700);
  font-weight: 600;
}

.copy-btn {
  display: inline-flex;
  align-items: center;
  gap: 3px;
  margin-left: auto;
  padding: 2px 8px;
  border: none;
  border-radius: 8px;
  background: transparent;
  color: #8aa6a2;
  font-size: 12px;
  font-family: inherit;
  cursor: pointer;
  transition: color 0.15s, background 0.15s;
}
.copy-btn:hover { color: var(--teal-700); background: rgba(15, 118, 110, 0.08); }
.copy-btn.copied { color: #2f9e44; }

/* ---------- Markdown 正文样式 ---------- */
.md {
  font-size: 15px;
  line-height: 1.75;
  color: #1f3d3b;
  word-break: break-word;
}
.md :deep(p) { margin: 0 0 10px; }
.md :deep(p:last-child) { margin-bottom: 0; }
.md :deep(h1), .md :deep(h2), .md :deep(h3) {
  font-family: var(--font-display);
  color: var(--teal-900);
  margin: 14px 0 8px;
  line-height: 1.3;
}
.md :deep(h1) { font-size: 20px; }
.md :deep(h2) { font-size: 18px; }
.md :deep(h3) { font-size: 16px; }
.md :deep(ul), .md :deep(ol) { margin: 6px 0 10px; padding-left: 22px; }
.md :deep(li) { margin: 4px 0; }
.md :deep(li::marker) { color: var(--teal-500); }
.md :deep(strong) { color: var(--teal-800, #0b3d3a); font-weight: 700; }
.md :deep(code) {
  background: var(--mint);
  color: var(--teal-900);
  padding: 1px 6px;
  border-radius: 5px;
  font-size: 0.9em;
}
.md :deep(pre) {
  background: #0e2f2c;
  color: #e6f4f1;
  padding: 12px 14px;
  border-radius: 10px;
  overflow-x: auto;
  margin: 10px 0;
}
.md :deep(pre code) { background: transparent; color: inherit; padding: 0; }
.md :deep(blockquote) {
  margin: 10px 0;
  padding: 4px 14px;
  border-left: 3px solid var(--teal-500);
  color: #4a6f6b;
  background: rgba(217, 242, 236, 0.4);
  border-radius: 0 8px 8px 0;
}
.md :deep(table) { border-collapse: collapse; margin: 10px 0; width: 100%; }
.md :deep(th), .md :deep(td) {
  border: 1px solid rgba(15, 118, 110, 0.2);
  padding: 6px 10px;
  text-align: left;
}
.md :deep(th) { background: var(--mint); }
.md :deep(a) { color: var(--teal-600); }
</style>
