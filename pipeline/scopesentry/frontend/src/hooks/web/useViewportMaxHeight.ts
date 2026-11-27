import { onBeforeUnmount, onMounted, ref } from 'vue'

/**
 * Tracks a responsive viewport-proportional maxHeight with automatic resize listener cleanup.
 */
export const useViewportMaxHeight = (ratio = 0.7) => {
  const maxHeight = ref(0)

  const updateMaxHeight = () => {
    const screenHeight = window.innerHeight || document.documentElement.clientHeight
    maxHeight.value = screenHeight * ratio
  }

  onMounted(() => {
    updateMaxHeight()
    window.addEventListener('resize', updateMaxHeight, { passive: true })
  })

  onBeforeUnmount(() => {
    window.removeEventListener('resize', updateMaxHeight)
  })

  return {
    maxHeight,
    updateMaxHeight
  }
}
