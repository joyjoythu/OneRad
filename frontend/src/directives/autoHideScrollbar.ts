import type { Directive } from 'vue'

/** 滚动停止后隐藏滚动条前的延迟（毫秒）。 */
const HIDE_DELAY_MS = 800

type ScrollbarEl = HTMLElement & { __autoHideScrollbarCleanup?: () => void }

/**
 * 隐形滚动条：滚动中为元素加 .is-scrolling 类使滚动条显现，停止后移除。
 * 配套样式见 styles/base.css 的 .auto-hide-scrollbar 规则。
 */
export const vAutoHideScrollbar: Directive<ScrollbarEl> = {
  mounted(el) {
    let timer: ReturnType<typeof setTimeout> | undefined
    const onScroll = (): void => {
      el.classList.add('is-scrolling')
      clearTimeout(timer)
      timer = setTimeout(() => el.classList.remove('is-scrolling'), HIDE_DELAY_MS)
    }
    el.addEventListener('scroll', onScroll, { passive: true })
    el.__autoHideScrollbarCleanup = () => {
      el.removeEventListener('scroll', onScroll)
      clearTimeout(timer)
    }
  },
  unmounted(el) {
    el.__autoHideScrollbarCleanup?.()
  },
}
