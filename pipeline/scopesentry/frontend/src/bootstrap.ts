import { createApp, type App as VueApp } from 'vue'

import '@/plugins/unocss'
import '@/plugins/svgIcon'
import '@/styles/index.less'
import '@/plugins/animate.css'

import { setupI18n } from '@/plugins/vueI18n'
import { setupStore } from '@/store'
import { setupGlobCom } from '@/components'
import { setupElementPlus } from '@/plugins/elementPlus'
import { setupRouter, router } from '@/router'
import { setupPermission as setupPermissionDirective } from '@/directives'
import { setupPermission as setupPermissionGuard } from '@/permission'
import App from './App.vue'
import {
  configureScopeSentryRuntime,
  getScopeSentryRuntime,
  setScopeSentryActive,
  getScopeSentryTheme,
  isScopeSentryEmbedded,
  normalizeScopeSentryPath,
  setScopeSentryPath,
  setScopeSentryStyleRoot,
  setScopeSentryTheme,
  type ScopeSentryRuntimeOptions,
  type ScopeSentryTheme
} from './runtime'
import { createScopeSentryPortalBoundary } from './portalBoundary'

export interface ScopeSentryMountOptions extends ScopeSentryRuntimeOptions {
  container: Element | string
}

export interface ScopeSentryMountHandle {
  setTheme(theme: ScopeSentryTheme): void
  setPath(path: string): void
  setActive?(active: boolean): void
  dispose(): void
}

const resolveContainer = (container: Element | string): Element => {
  if (typeof container !== 'string') return container
  const element = document.querySelector(container)
  if (!element) throw new Error(`ScopeSentry mount container not found: ${container}`)
  return element
}

const mountNativeApp = async (
  container: Element,
  options: ScopeSentryMountOptions
): Promise<ScopeSentryMountHandle> => {
  configureScopeSentryRuntime(options)
  setScopeSentryStyleRoot(container as HTMLElement)
  setScopeSentryTheme(getScopeSentryTheme())
  const portalBoundary = createScopeSentryPortalBoundary(
    options.active ?? true,
    options.embedded ? (container as HTMLElement) : undefined
  )

  const app: VueApp<Element> = createApp(App)
  await setupI18n(app)
  setupStore(app)
  setupGlobCom(app)
  setupElementPlus(app)
  setupRouter(app)
  setupPermissionDirective(app)
  const removePermissionHooks = setupPermissionGuard(router)

  let syncingHostPath = false
  const initialPath = normalizeScopeSentryPath(options.path || getScopeSentryRuntime().path)
  setScopeSentryPath(initialPath)

  if (isScopeSentryEmbedded()) {
    await router.replace(initialPath)
  }

  const removeNavigationHook = router.afterEach((to) => {
    setScopeSentryPath(to.fullPath)
    if (isScopeSentryEmbedded() && !syncingHostPath && getScopeSentryRuntime().onNavigate) {
      getScopeSentryRuntime().onNavigate(to.fullPath, false)
    }
    syncingHostPath = false
  })

  app.mount(container)

  const setActive = (active: boolean) => {
    setScopeSentryActive(active)
    portalBoundary.setActive(active)
    const appStoreRoot = container.querySelector<HTMLElement>('.scope-sentry-root')
    appStoreRoot?.setAttribute('data-scopesentry-active', active ? 'true' : 'false')
  }
  setActive(options.active ?? getScopeSentryRuntime().active)

  return {
    setTheme(theme: ScopeSentryTheme) {
      setScopeSentryTheme(theme)
      const appStoreRoot = container.querySelector<HTMLElement>('.scope-sentry-root') || container
      appStoreRoot.dataset.scopesentryTheme = theme
    },
    setPath(path: string) {
      const nextPath = normalizeScopeSentryPath(path)
      setScopeSentryPath(nextPath)
      if (!isScopeSentryEmbedded() || router.currentRoute.value.fullPath === nextPath) return
      syncingHostPath = true
      void router.replace(nextPath).catch(() => {
        syncingHostPath = false
      })
    },
    setActive,
    dispose() {
      removeNavigationHook()
      removePermissionHooks()
      app.unmount()
      portalBoundary.dispose()
      setScopeSentryStyleRoot(null)
    }
  }
}

export const mountScopeSentry = async (
  container: Element | string,
  options: Omit<ScopeSentryMountOptions, 'container'> = {}
): Promise<ScopeSentryMountHandle> => {
  const element = resolveContainer(container)
  return mountNativeApp(element, { ...options, container: element })
}

export const createStandaloneScopeSentry = (container: Element | string = '#app') => {
  return mountScopeSentry(container, { embedded: false })
}
