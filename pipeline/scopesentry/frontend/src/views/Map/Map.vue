<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref } from 'vue'
import { getScopeSentryActive } from '@/runtime'

const MAP_STATIC_BASE = '/_modules/scopesentry/native-map'
const MAP_JS_BASE = `${MAP_STATIC_BASE}/js`

// These filenames remain coupled to the read-only native map.html manifest. The
// preparation adapter copies the matching hashed tree without renaming it.
const MAP_STYLES = [
  `${MAP_STATIC_BASE}/css/@fesjs.C7wRTT0A1764683399638.css`,
  `${MAP_STATIC_BASE}/css/@tresjs.8Vyyz-Qa1764683399638.css`,
  `${MAP_STATIC_BASE}/css/index.D0dvkPRx1764683399638.css`,
  `${MAP_STATIC_BASE}/css/animate.DhA8USjN1764683399638.css`
]
const MAP_SCRIPTS = [
  `${MAP_JS_BASE}/polyfills._De1UJh71764683399638.js`,
  `${MAP_STATIC_BASE}/lib/jweixin-1.6.0.js`,
  `${MAP_STATIC_BASE}/lib/uni.webview.0.1.52.js`,
  `${MAP_JS_BASE}/index.DM693cYN1764683399638.js`
]

type MapMountProps = {
  name: string
  container: Element
  url: string
  onGlobalStateChange: (_callback: (state: unknown, previous: unknown) => void) => void
  setGlobalState: (state: unknown) => void
}

type MapLifecycle = {
  bootstrap: (props?: MapMountProps) => void | Promise<void>
  mount: (props: MapMountProps) => void | Promise<void>
  update: (props?: MapMountProps) => void | Promise<void>
  unmount: (props?: MapMountProps) => void | Promise<void>
}

type MapWindow = Window & {
  __POWERED_BY_QIANKUN__?: boolean
  __INJECTED_PUBLIC_PATH_BY_QIANKUN__?: string
  qiankunName?: string
  moudleQiankunAppLifeCycles?: Record<string, MapLifecycle>
}

type MapStylesheet = HTMLLinkElement | HTMLStyleElement

const mapContainer = ref<HTMLDivElement | null>(null)
const mapError = ref<string | null>(null)
let mapActive = getScopeSentryActive()
let mountedLifecycle: MapLifecycle | null = null
let mountProps: MapMountProps | null = null
let addedScripts: HTMLScriptElement[] = []
let addedStyles: HTMLLinkElement[] = []
let addedDynamicStyles: MapStylesheet[] = []
let dynamicStyleObserver: MutationObserver | null = null
let mountController: AbortController | null = null
let mountOperation: Promise<void> | null = null
let cleanupOperation: Promise<void> | null = null
const originalStyleMedia = new Map<HTMLStyleElement, string>()
let previousGlobals: {
  poweredByQiankun: boolean | undefined
  injectedPublicPath: string | undefined
  qiankunName: string | undefined
  lifecycleRegistry: Record<string, MapLifecycle> | undefined
  lifecycle: MapLifecycle | undefined
} | null = null

const setMapStylesActive = (active: boolean): void => {
  mapActive = active
  for (const style of [...addedStyles, ...addedDynamicStyles]) {
    if (style instanceof HTMLLinkElement) {
      style.disabled = !active
      continue
    }
    if (!originalStyleMedia.has(style)) originalStyleMedia.set(style, style.media)
    style.media = active ? originalStyleMedia.get(style) || 'all' : 'not all'
  }
}

const isNativeMapStylesheet = (element: Element): element is HTMLLinkElement => {
  if (!(element instanceof HTMLLinkElement)) return false
  if (element.rel !== 'stylesheet') return false
  try {
    return new URL(element.href, document.baseURI).pathname.startsWith(`${MAP_STATIC_BASE}/`)
  } catch {
    return false
  }
}

const rememberDynamicStylesheet = (style: MapStylesheet): void => {
  if (addedStyles.includes(style as HTMLLinkElement) || addedDynamicStyles.includes(style)) return
  style.dataset.scopesentryMapAsset = 'true'
  addedDynamicStyles.push(style)
  setMapStylesActive(mapActive)
}

const observeDynamicStyles = (): void => {
  dynamicStyleObserver = new MutationObserver((records) => {
    records.forEach((record) => {
      record.addedNodes.forEach((node) => {
        if (!(node instanceof Element)) return
        if (isNativeMapStylesheet(node)) rememberDynamicStylesheet(node)
        node.querySelectorAll<HTMLLinkElement>('link[rel="stylesheet"]').forEach((link) => {
          if (isNativeMapStylesheet(link)) rememberDynamicStylesheet(link)
        })
        // vue-echarts registers this small style element from a native Map chunk.
        // Keep the detection narrow rather than taking ownership of host styles.
        if (
          node instanceof HTMLStyleElement &&
          node.textContent?.includes('x-vue-echarts')
        ) {
          rememberDynamicStylesheet(node)
        }
      })
    })
  })
  dynamicStyleObserver.observe(document.head, { childList: true, subtree: true })
}

const appendStyles = (): void => {
  for (const href of MAP_STYLES) {
    const link = document.createElement('link')
    link.rel = 'stylesheet'
    link.href = href
    link.dataset.scopesentryMapAsset = 'true'
    document.head.appendChild(link)
    addedStyles.push(link)
  }
  setMapStylesActive(mapActive)
}

const appendScript = (
  src: string,
  type: 'classic' | 'module',
  signal: AbortSignal
): Promise<void> =>
  new Promise((resolve, reject) => {
    const script = document.createElement('script')
    let settled = false
    const finish = (error?: Error) => {
      if (settled) return
      settled = true
      signal.removeEventListener('abort', abort)
      script.removeEventListener('load', handleLoad)
      script.removeEventListener('error', handleError)
      if (error) reject(error)
      else resolve()
    }
    const abort = () => {
      script.remove()
      finish(new DOMException('ScopeSentry Map mount was cancelled.', 'AbortError'))
    }
    const handleLoad = () => finish()
    const handleError = () =>
      finish(new Error(`ScopeSentry Map resource failed to load: ${src}`))
    script.src = src
    script.async = false
    if (type === 'module') script.type = 'module'
    script.dataset.scopesentryMapAsset = 'true'
    script.addEventListener('load', handleLoad, { once: true })
    script.addEventListener('error', handleError, { once: true })
    signal.addEventListener('abort', abort, { once: true })
    if (signal.aborted) {
      abort()
      return
    }
    document.head.appendChild(script)
    addedScripts.push(script)
  })

const installMapGlobals = (): void => {
  const global = window as MapWindow
  const lifecycleRegistry = global.moudleQiankunAppLifeCycles
  previousGlobals = {
    poweredByQiankun: global.__POWERED_BY_QIANKUN__,
    injectedPublicPath: global.__INJECTED_PUBLIC_PATH_BY_QIANKUN__,
    qiankunName: global.qiankunName,
    lifecycleRegistry,
    lifecycle: lifecycleRegistry?.['TvT.js']
  }
  global.__POWERED_BY_QIANKUN__ = true
  // Relative native imports are local module assets. Generated root API/image/
  // plugin literals are prepared separately under the backend namespace.
  global.__INJECTED_PUBLIC_PATH_BY_QIANKUN__ = `${MAP_STATIC_BASE}/`
  global.qiankunName = 'TvT.js'
  if (!global.moudleQiankunAppLifeCycles) global.moudleQiankunAppLifeCycles = {}
}

const restoreMapGlobals = (): void => {
  const global = window as MapWindow
  const previous = previousGlobals
  if (!previous) return
  if (previous.lifecycleRegistry) {
    if (previous.lifecycle) previous.lifecycleRegistry['TvT.js'] = previous.lifecycle
    else delete previous.lifecycleRegistry['TvT.js']
  } else if (global.moudleQiankunAppLifeCycles) {
    delete global.moudleQiankunAppLifeCycles['TvT.js']
    delete global.moudleQiankunAppLifeCycles
  }
  global.__POWERED_BY_QIANKUN__ = previous.poweredByQiankun
  global.__INJECTED_PUBLIC_PATH_BY_QIANKUN__ = previous.injectedPublicPath
  global.qiankunName = previous.qiankunName
  previousGlobals = null
}

const removeMapResources = (): void => {
  addedScripts.forEach((script) => script.remove())
  addedStyles.forEach((style) => style.remove())
  addedDynamicStyles.forEach((style) => style.remove())
  document.head
    .querySelectorAll<HTMLElement>('[data-scopesentry-map-asset="true"]')
    .forEach((asset) => asset.remove())
  addedScripts = []
  addedStyles = []
  addedDynamicStyles = []
  originalStyleMedia.clear()
}

const unmountNativeMap = (): Promise<void> => {
  if (cleanupOperation) return cleanupOperation
  cleanupOperation = (async () => {
    const lifecycle = mountedLifecycle
    const props = mountProps
    mountedLifecycle = null
    mountProps = null
    if (lifecycle && props) {
      try {
        await lifecycle.unmount(props)
      } catch (error) {
        console.error('[ScopeSentry Map] native unmount failed', error)
      }
    }
    removeMapResources()
    restoreMapGlobals()
  })()
  return cleanupOperation
}

const mountNativeMap = async (signal: AbortSignal): Promise<void> => {
  const container = mapContainer.value
  const root = container?.querySelector<HTMLElement>('#tvt-app')
  if (signal.aborted) return
  if (!container || !root) {
    mapError.value = 'ScopeSentry Map mount container is unavailable.'
    return
  }

  try {
    installMapGlobals()
    appendStyles()
    await appendScript(MAP_SCRIPTS[0], 'module', signal)
    if (signal.aborted) return
    await appendScript(MAP_SCRIPTS[1], 'classic', signal)
    if (signal.aborted) return
    await appendScript(MAP_SCRIPTS[2], 'classic', signal)
    if (signal.aborted) return
    await appendScript(MAP_SCRIPTS[3], 'module', signal)
    if (signal.aborted) return

    const global = window as MapWindow
    const lifecycle = global.moudleQiankunAppLifeCycles?.['TvT.js']
    if (!lifecycle) throw new Error('Native ScopeSentry Map lifecycle was not registered.')

    const props: MapMountProps = {
      name: 'TvT.js',
      container,
      // The native app has a root route at /. This URL is internal to the
      // native memory of the embedded app; it does not change host history.
      url: '/',
      onGlobalStateChange: () => undefined,
      setGlobalState: () => undefined
    }
    mountProps = props
    mountedLifecycle = lifecycle
    await lifecycle.bootstrap(props)
    if (signal.aborted) return
    await lifecycle.mount(props)
    if (signal.aborted) return
  } catch (error) {
    if (signal.aborted) return
    mapError.value = error instanceof Error ? error.message : 'ScopeSentry Map failed to mount.'
    await unmountNativeMap()
  }
}

const handleScopeSentryActiveChange = (event: Event): void => {
  const active = (event as CustomEvent<boolean>).detail
  if (typeof active === 'boolean') setMapStylesActive(active)
}

onMounted(() => {
  window.addEventListener('scopesentry:active-change', handleScopeSentryActiveChange)
  observeDynamicStyles()
  mountController = new AbortController()
  mountOperation = mountNativeMap(mountController.signal)
  void mountOperation.catch((error) => {
    mapError.value = error instanceof Error ? error.message : 'ScopeSentry Map failed to mount.'
  })
})

onBeforeUnmount(() => {
  window.removeEventListener('scopesentry:active-change', handleScopeSentryActiveChange)
  mountController?.abort()
  mountController = null
  dynamicStyleObserver?.disconnect()
  dynamicStyleObserver = null
  const pendingMount = mountOperation
  mountOperation = null
  void (async () => {
    if (pendingMount) await pendingMount
    await unmountNativeMap()
  })().catch((error) => {
    console.error('[ScopeSentry Map] cleanup failed', error)
  })
})
</script>

<template>
  <div ref="mapContainer" class="scope-sentry-map-embed" data-scopesentry-map>
    <div id="tvt-app" class="scope-sentry-map-native" aria-label="ScopeSentry Map" />
    <div v-if="mapError" class="scope-sentry-map-error" role="alert">
      {{ mapError }}
    </div>
  </div>
</template>

<style scoped lang="less">
.scope-sentry-map-embed {
  position: relative;
  width: 100%;
  height: 100%;
  min-height: 0;
  overflow: hidden;
  isolation: isolate;
  background: #111;
}

.scope-sentry-map-native {
  width: 100%;
  height: 100%;
  min-height: 0;
}

.scope-sentry-map-error {
  position: absolute;
  inset: 1rem;
  display: grid;
  place-items: center;
  padding: 1rem;
  color: #fca5a5;
  background: rgba(17, 17, 17, 0.92);
  border: 1px solid rgba(248, 113, 113, 0.45);
  border-radius: 0.5rem;
  text-align: center;
}
</style>
