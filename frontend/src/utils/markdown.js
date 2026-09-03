import { marked } from 'marked'
import DOMPurify from 'dompurify'

// 换行友好（聊天场景单换行也渲染）+ GitHub 风格表格/列表
marked.setOptions({ breaks: true, gfm: true })

/**
 * 将 Markdown 文本渲染为安全的 HTML
 * LLM 回答经 marked 解析后，再用 DOMPurify 消毒，防止提示注入产生的恶意 HTML
 * @param {string} text
 * @returns {string} 安全的 HTML 字符串
 */
export function renderMarkdown(text) {
  if (!text) return ''
  const raw = marked.parse(text)
  return DOMPurify.sanitize(raw, { ADD_ATTR: ['target'] })
}
