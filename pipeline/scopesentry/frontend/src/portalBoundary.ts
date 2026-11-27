const OWNED_PORTAL_ATTRIBUTE = 'data-scopesentry-owned-portal'
const PORTAL_ACTIVE_ATTRIBUTE = 'data-scopesentry-portal-active'
const POPUP_LOCK_CLASS = 'el-popup-parent--hidden'

const PORTAL_CLASS_NAMES = [
  'el-overlay',
  'el-message',
  'el-message-box',
  'el-notification',
  'el-image-viewer__wrapper',
  'el-loading-mask',
  'el-dialog',
  'el-drawer',
  'el-popover',
  'el-popper',
  'el-dropdown__popper',
  'el-select__popper',
  'el-select-dropdown',
  'el-picker-panel',
  'el-date-picker',
  'el-time-panel',
  'el-cascader__dropdown',
  'el-autocomplete-suggestion',
  'el-color-picker__panel',
  'el-tree-select__popper',
  'el-tooltip__popper',
  'el-popconfirm',
  'el-menu--popup'
] as const

const PORTAL_SELECTOR = PORTAL_CLASS_NAMES.map((className) => `.${className}`).join(',')

export interface ScopeSentryPortalBoundary {
  setActive(active: boolean): void
  dispose(): void
}

const noopBoundary: ScopeSentryPortalBoundary = {
  setActive: () => undefined,
  dispose: () => undefined
}

export const createScopeSentryPortalBoundary = (
  initialActive = true,
  moduleStyleRoot?: HTMLElement
): ScopeSentryPortalBoundary => {
  if (typeof document === 'undefined' || !document.body) return noopBoundary

  const body = document.body
  const ownedPortals = new Set<HTMLElement>()
  const observedPopperContainers = new Set<HTMLElement>()
  const originalPortalVariables = new Map<HTMLElement, Map<string, { value: string; priority: string }>>()
  const appliedPortalVariables = new Map<HTMLElement, Set<string>>()
  let active = initialActive
  let disposed = false
  let applyingPopupLockChange = false
  let lastPopupLockState = body.classList.contains(POPUP_LOCK_CLASS)
  let scopeOwnsPopupLock = false
  let scopeLockSuppressed = false
  let cachedVariables: Map<string, string> | null = null
  let cachedSource: HTMLElement | null = null
  let cachedScopeRoot: HTMLElement | null = null
  let syncScheduled = false

  const portalStyle = document.createElement('style')
  portalStyle.dataset.scopesentryPortalBoundary = 'true'
  portalStyle.textContent = `
[data-scopesentry-owned-portal="true"][data-scopesentry-portal-active="false"] {
  visibility: hidden !important;
  pointer-events: none !important;
}
[data-scopesentry-owned-portal="true"][data-scopesentry-portal-active="false"] * {
  pointer-events: none !important;
}
`
  document.head.appendChild(portalStyle)

  const restorePortalVariables = (element: HTMLElement) => {
    const original = originalPortalVariables.get(element)
    const applied = appliedPortalVariables.get(element)
    if (!original || !applied) return
    applied.forEach((name) => {
      const value = original.get(name)
      if (value?.value) element.style.setProperty(name, value.value, value.priority)
      else element.style.removeProperty(name)
    })
    originalPortalVariables.delete(element)
    appliedPortalVariables.delete(element)
  }

  const pruneDisconnectedPortals = () => {
    ownedPortals.forEach((element) => {
      if (element.isConnected) return
      ownedPortals.delete(element)
      originalPortalVariables.delete(element)
      appliedPortalVariables.delete(element)
    })
  }

  const resolveStyleSource = (): HTMLElement | null => {
    if (!moduleStyleRoot) return null
    if (!cachedScopeRoot?.isConnected) {
      cachedScopeRoot = moduleStyleRoot.querySelector<HTMLElement>('[data-scopesentry-root]')
    }
    return cachedScopeRoot || moduleStyleRoot
  }

  const getPortalVariables = (): Map<string, string> | null => {
    const source = resolveStyleSource()
    if (!source) return null
    if (cachedVariables && cachedSource === source) return cachedVariables

    const computed = getComputedStyle(source)
    const next = new Map<string, string>()
    for (let index = 0; index < computed.length; index += 1) {
      const name = computed.item(index)
      if (!/^--(?:el-|qwen-|app-|left-menu-|logo-|top-|tags-|transition-|login-)/.test(name)) continue
      const value = computed.getPropertyValue(name).trim()
      if (value) next.set(name, value)
    }
    cachedVariables = next
    cachedSource = source
    return next
  }

  const syncPortalVariables = (element: HTMLElement, next = getPortalVariables()) => {
    if (!next || !element.isConnected) return

    let original = originalPortalVariables.get(element)
    if (!original) {
      original = new Map()
      originalPortalVariables.set(element, original)
    }
    const previous = appliedPortalVariables.get(element) || new Set<string>()
    previous.forEach((name) => {
      if (next.has(name)) return
      const value = original?.get(name)
      if (value?.value) element.style.setProperty(name, value.value, value.priority)
      else element.style.removeProperty(name)
    })
    next.forEach((value, name) => {
      if (!original?.has(name)) {
        original?.set(name, {
          value: element.style.getPropertyValue(name),
          priority: element.style.getPropertyPriority(name)
        })
      }
      element.style.setProperty(name, value)
    })
    appliedPortalVariables.set(element, new Set(next.keys()))
  }

  const schedulePortalVariableSync = () => {
    cachedVariables = null
    if (syncScheduled || disposed || ownedPortals.size === 0) return
    syncScheduled = true
    queueMicrotask(() => {
      syncScheduled = false
      if (disposed) return
      pruneDisconnectedPortals()
      if (ownedPortals.size === 0) return
      const next = getPortalVariables()
      ownedPortals.forEach((element) => syncPortalVariables(element, next))
    })
  }

  const setPortalActivity = (element: HTMLElement) => {
    element.setAttribute(OWNED_PORTAL_ATTRIBUTE, 'true')
    element.setAttribute(PORTAL_ACTIVE_ATTRIBUTE, active ? 'true' : 'false')
    ownedPortals.add(element)
    syncPortalVariables(element)
  }

  const isPopperContainer = (element: HTMLElement) => element.id.startsWith('el-popper-container')

  const popperObserver = new MutationObserver((records) => {
    records.forEach((record) => record.addedNodes.forEach((node) => markPortalRoot(node)))
  })

  const observePopperContainer = (container: HTMLElement) => {
    if (!observedPopperContainers.has(container)) {
      observedPopperContainers.add(container)
      popperObserver.observe(container, { childList: true })
    }
    Array.from(container.children).forEach((child) => markPortalRoot(child))
  }

  function markPortalRoot(node: Node) {
    if (!(node instanceof HTMLElement)) return
    if (moduleStyleRoot && (node === moduleStyleRoot || moduleStyleRoot.contains(node))) return
    if (isPopperContainer(node)) {
      observePopperContainer(node)
      return
    }
    if (!node.matches(PORTAL_SELECTOR)) return
    setPortalActivity(node)
    node.querySelectorAll<HTMLElement>(PORTAL_SELECTOR).forEach(setPortalActivity)
  }

  const portalObserver = new MutationObserver((records) => {
    records.forEach((record) => record.addedNodes.forEach(markPortalRoot))
  })
  // Only observe direct body children + Element Plus popper containers to avoid scanning table/host subtrees.
  portalObserver.observe(body, { childList: true })
  Array.from(body.children).forEach(markPortalRoot)

  const syncPopupLock = () => {
    const hasPopupLock = body.classList.contains(POPUP_LOCK_CLASS)
    if (active && hasPopupLock && !lastPopupLockState && !scopeLockSuppressed) {
      scopeOwnsPopupLock = true
    }

    if (!active && scopeOwnsPopupLock && hasPopupLock) {
      applyingPopupLockChange = true
      body.classList.remove(POPUP_LOCK_CLASS)
      applyingPopupLockChange = false
      scopeOwnsPopupLock = false
      scopeLockSuppressed = true
    }

    if (active && scopeLockSuppressed && !hasPopupLock && ownedPortals.size > 0) {
      applyingPopupLockChange = true
      body.classList.add(POPUP_LOCK_CLASS)
      applyingPopupLockChange = false
      scopeOwnsPopupLock = true
      scopeLockSuppressed = false
    }

    lastPopupLockState = body.classList.contains(POPUP_LOCK_CLASS)
  }

  const bodyClassObserver = new MutationObserver(() => {
    if (!applyingPopupLockChange) syncPopupLock()
  })
  bodyClassObserver.observe(body, { attributes: true, attributeFilter: ['class'] })

  let observedScopeRoot: HTMLElement | null = null
  const themeObserver = moduleStyleRoot
    ? new MutationObserver(() => {
        attachScopeRootObserver()
        schedulePortalVariableSync()
      })
    : null

  function attachScopeRootObserver() {
    if (!moduleStyleRoot || !themeObserver) return
    const nextScopeRoot = moduleStyleRoot.querySelector<HTMLElement>('[data-scopesentry-root]')
    if (nextScopeRoot && nextScopeRoot !== observedScopeRoot) {
      observedScopeRoot = nextScopeRoot
      cachedScopeRoot = nextScopeRoot
      themeObserver.observe(nextScopeRoot, {
        attributes: true,
        attributeFilter: ['class', 'style', 'data-scopesentry-theme']
      })
    }
  }

  if (moduleStyleRoot && themeObserver) {
    themeObserver.observe(moduleStyleRoot, {
      attributes: true,
      attributeFilter: ['class', 'style', 'data-scopesentry-theme'],
      childList: true
    })
    attachScopeRootObserver()
  }

  const setActive = (nextActive: boolean) => {
    if (disposed) return
    active = nextActive
    pruneDisconnectedPortals()
    ownedPortals.forEach((element) => {
      element.setAttribute(PORTAL_ACTIVE_ATTRIBUTE, active ? 'true' : 'false')
    })
    syncPopupLock()
  }

  return {
    setActive,
    dispose() {
      if (disposed) return
      disposed = true
      portalObserver.disconnect()
      popperObserver.disconnect()
      bodyClassObserver.disconnect()
      themeObserver?.disconnect()
      observedPopperContainers.clear()
      if (scopeOwnsPopupLock && body.classList.contains(POPUP_LOCK_CLASS)) {
        body.classList.remove(POPUP_LOCK_CLASS)
      }
      ownedPortals.forEach((element) => {
        restorePortalVariables(element)
        element.removeAttribute(OWNED_PORTAL_ATTRIBUTE)
        element.removeAttribute(PORTAL_ACTIVE_ATTRIBUTE)
      })
      ownedPortals.clear()
      portalStyle.remove()
    }
  }
}
