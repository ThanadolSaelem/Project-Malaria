import type { Ref } from 'vue'

export type ScopeSentryTheme = 'light' | 'dark'

export interface ScopeSentryRuntimeOptions {
  embedded?: boolean
  active?: boolean
  theme?: ScopeSentryTheme
  path?: string
  onNavigate?: (path: string, replace?: boolean) => void
  apiBasePath?: string
  staticBasePath?: string
  backendBasePath?: string
}

interface ScopeSentryRuntimeState {
  embedded: boolean
  active: boolean
  theme: ScopeSentryTheme
  path: string
  onNavigate?: (path: string, replace?: boolean) => void
  apiBasePath: string
  staticBasePath: string
  backendBasePath: string
  styleRoot: HTMLElement | null
}

const envApiBasePath = (import.meta.env.VITE_API_BASE_PATH || '').replace(/\/$/, '')

const runtime: ScopeSentryRuntimeState = {
  embedded: false,
  active: true,
  theme: 'light',
  path: '/dashboard',
  onNavigate: undefined,
  apiBasePath: envApiBasePath,
  staticBasePath: '',
  backendBasePath: '',
  styleRoot: null
}

const withLeadingSlash = (path: string): string => (path.startsWith('/') ? path : `/${path}`)

const joinPath = (basePath: string, path: string): string => {
  if (/^(?:[a-z][a-z\d+.-]*:|\/\/)/i.test(path)) return path
  const normalizedPath = withLeadingSlash(path)
  const normalizedBase = basePath.replace(/\/$/g, '')
  return `${normalizedBase}${normalizedPath}` || '/'
}

export const configureScopeSentryRuntime = (options: ScopeSentryRuntimeOptions = {}) => {
  runtime.embedded = options.embedded ?? runtime.embedded
  runtime.active = options.active ?? runtime.active
  runtime.theme = options.theme ?? runtime.theme
  runtime.path = options.path ? withLeadingSlash(options.path) : runtime.path
  runtime.onNavigate = options.onNavigate ?? runtime.onNavigate
  runtime.apiBasePath = (options.apiBasePath ?? runtime.apiBasePath).replace(/\/$/g, '')
  runtime.staticBasePath = (options.staticBasePath ?? runtime.staticBasePath).replace(/\/$/g, '')
  runtime.backendBasePath = (options.backendBasePath ?? runtime.backendBasePath).replace(/\/$/g, '')
}

export const setScopeSentryStyleRoot = (root: HTMLElement | null) => {
  runtime.styleRoot = root
  if (root) root.dataset.scopesentryActive = runtime.active ? 'true' : 'false'
}

export const getScopeSentryStyleRoot = (): HTMLElement => {
  return runtime.styleRoot || document.documentElement
}

export const isScopeSentryEmbedded = (): boolean => runtime.embedded

export const getScopeSentryTheme = (): ScopeSentryTheme => runtime.theme

export const setScopeSentryTheme = (theme: ScopeSentryTheme) => {
  runtime.theme = theme
  const root = getScopeSentryStyleRoot()
  root.dataset.scopesentryTheme = theme
  root.classList.toggle('scope-sentry-dark', theme === 'dark')
  root.classList.toggle('scope-sentry-light', theme === 'light')

  const dark = theme === 'dark'
  root.style.setProperty('--qwen-background', dark ? '#0d0d0d' : '#ffffff')
  root.style.setProperty('--qwen-foreground', dark ? '#fafafa' : '#0a0a0b')
  root.style.setProperty('--qwen-accent', dark ? '#6785ff' : '#0033ff')
  root.style.setProperty('--el-color-primary', dark ? '#6785ff' : '#0033ff')
  root.style.setProperty('--app-content-bg-color', dark ? '#0d0d0d' : '#f5f7f9')
  root.style.setProperty('--el-bg-color', dark ? '#0d0d0d' : '#ffffff')
  root.style.setProperty('--el-bg-color-page', dark ? '#0d0d0d' : '#f5f7f9')
  root.style.setProperty('--el-text-color-primary', dark ? '#fafafa' : '#0a0a0b')
}

export const getScopeSentryActive = (): boolean => runtime.active

export const setScopeSentryActive = (active: boolean) => {
  runtime.active = active
  const root = getScopeSentryStyleRoot()
  root.dataset.scopesentryActive = active ? 'true' : 'false'
  if (typeof window !== 'undefined') {
    window.dispatchEvent(new CustomEvent('scopesentry:active-change', { detail: active }))
  }
}

export const getScopeSentryApiBasePath = (): string => runtime.apiBasePath

export const scopeSentryApiPath = (path: string): string => joinPath(runtime.apiBasePath, path)

export const scopeSentryStaticPath = (path: string): string => joinPath(runtime.staticBasePath, path)

export const scopeSentryBackendPath = (path: string): string => joinPath(runtime.backendBasePath, path)

export const getScopeSentryPath = (): string => runtime.path

export const normalizeScopeSentryPath = (path: string): string => {
  const value = path || '/dashboard'
  return value.startsWith('/') ? value : `/${value}`
}

export const navigateScopeSentry = (path: string, replace = false) => {
  const normalizedPath = normalizeScopeSentryPath(path)
  runtime.path = normalizedPath
  if (runtime.onNavigate) {
    runtime.onNavigate(normalizedPath, replace)
    return
  }

  window.location.assign(scopeSentryBackendPath(normalizedPath))
}

export const setScopeSentryPath = (path: string) => {
  runtime.path = normalizeScopeSentryPath(path)
}

export const getScopeSentryRuntime = (): Readonly<ScopeSentryRuntimeState> => runtime

export type ScopeSentryRouterPath = Ref<string> | string
