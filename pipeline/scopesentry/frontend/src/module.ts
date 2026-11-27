import {
  configureScopeSentryRuntime,
  setScopeSentryPath,
  setScopeSentryActive,
  setScopeSentryStyleRoot,
  setScopeSentryTheme,
  type ScopeSentryTheme
} from './runtime'

export interface ScopeSentryModuleOptions {
  active?: boolean
  theme: ScopeSentryTheme
  path: string
  onNavigate: (path: string, replace?: boolean) => void
}

export interface ScopeSentryModuleHandle {
  setTheme(theme: ScopeSentryTheme): void
  setPath(path: string): void
  setActive?(active: boolean): void
  dispose(): void
}

export const createScopeSentryModule = (
  container: Element,
  options: ScopeSentryModuleOptions
): ScopeSentryModuleHandle => {
  let disposed = false
  let currentTheme = options.theme
  let currentPath = options.path
  let currentActive = options.active ?? true
  let nativeHandle: ScopeSentryModuleHandle | undefined

  configureScopeSentryRuntime({
    embedded: true,
    active: currentActive,
    theme: currentTheme,
    path: currentPath,
    onNavigate: options.onNavigate,
    apiBasePath: '/scopesentry-api',
    staticBasePath: '/scopesentry-api',
    backendBasePath: '/scopesentry-api'
  })
  setScopeSentryStyleRoot(container)
  setScopeSentryActive(currentActive)
  setScopeSentryTheme(currentTheme)
  setScopeSentryPath(currentPath)

  const nativeMountPromise = import('./bootstrap')
    .then(({ mountScopeSentry }) => {
      if (disposed) return undefined
      return mountScopeSentry(container, {
        embedded: true,
        active: currentActive,
        theme: currentTheme,
        path: currentPath,
        onNavigate: options.onNavigate,
        apiBasePath: '/scopesentry-api',
        staticBasePath: '/scopesentry-api',
        backendBasePath: '/scopesentry-api'
      })
    })
    .then((handle) => {
      if (!handle) return
      if (disposed) {
        handle.dispose()
        return
      }
      nativeHandle = handle
      nativeHandle.setTheme(currentTheme)
      nativeHandle.setPath(currentPath)
      nativeHandle.setActive?.(currentActive)
    })
    .catch((error) => {
      if (!disposed) console.error('[ScopeSentry] native mount failed', error)
    })

  void nativeMountPromise

  return {
    setTheme(theme: ScopeSentryTheme) {
      currentTheme = theme
      setScopeSentryTheme(theme)
      nativeHandle?.setTheme(theme)
    },
    setPath(path: string) {
      currentPath = path
      setScopeSentryPath(path)
      nativeHandle?.setPath(path)
    },
    setActive(active: boolean) {
      currentActive = active
      setScopeSentryActive(active)
      nativeHandle?.setActive?.(active)
    },
    dispose() {
      disposed = true
      nativeHandle?.dispose()
      nativeHandle = undefined
      setScopeSentryStyleRoot(null)
    }
  }
}

export default createScopeSentryModule
