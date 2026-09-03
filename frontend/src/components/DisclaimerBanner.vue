<!--
  ============================================================
  DisclaimerBanner.vue —— 全局免责声明横幅
  从 ChatView.vue 抽出的独立组件（与讲义 day05 §3.2 目录结构一致）。
  医疗合规底线：任何页面只要涉及问诊/建议，就必须展示本横幅。
  ============================================================
-->
<script setup>
defineProps({
  // 允许调用方覆盖文案，默认使用标准免责声明
  text: {
    type: String,
    default: '本系统仅供健康咨询与就医指导，不能替代专业医疗诊断。身体不适请及时就医，切勿自行用药。'
  }
})
</script>

<template>
  <el-alert
    class="disclaimer"
    type="warning"
    :closable="false"
    show-icon
    :title="text"
  />
</template>

<style scoped>
.disclaimer { border-radius: 12px; }
</style>
