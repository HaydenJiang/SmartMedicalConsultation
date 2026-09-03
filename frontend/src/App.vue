<script setup>
// 根组件：引入聊天主界面
import ChatView from '@/views/ChatView.vue'
</script>

<template>
  <ChatView />
</template>

<style>
/* ============ 全局基础样式 ============ */
:root {
  /* 配色：临床青绿 + 暖色点缀（医疗的信任感与温度） */
  --ink: #123332;
  --teal-900: #0b3d3a;
  --teal-700: #0e5a54;
  --teal-600: #0f766e;
  --teal-500: #14b8a6;
  --mint: #d9f2ec;
  --paper: #f6fbf9;
  --coral: #e8896b;

  /* 字体 */
  --font-display: 'Noto Serif SC', 'Songti SC', 'SimSun', serif;
  --font-body: 'Noto Sans SC', 'PingFang SC', 'Microsoft YaHei', sans-serif;
}

* {
  margin: 0;
  padding: 0;
  box-sizing: border-box;
}

html,
body,
#app {
  height: 100%;
}

body {
  font-family: var(--font-body);
  color: var(--ink);
  background: var(--paper);
  -webkit-font-smoothing: antialiased;
}
</style>
