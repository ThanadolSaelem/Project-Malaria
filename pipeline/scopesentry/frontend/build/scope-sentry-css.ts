import selectorParser from 'postcss-selector-parser'
import type { Root } from 'postcss'

const SCOPE_SELECTOR =
  ':where([data-scopesentry-root], [data-scopesentry-owned-portal="true"])'
const ROOT_ELEMENT_NAMES = new Set(['html', 'body'])

type SelectorLike = {
  nodes: Array<{ type?: string; value?: string; clone: () => any }>
  clone: () => SelectorLike
  toString: () => string
}

const isRootNode = (node: { type?: string; value?: string }): boolean =>
  (node.type === 'tag' && ROOT_ELEMENT_NAMES.has(node.value || '')) ||
  (node.type === 'pseudo' && node.value === ':root')

const isPortalRootSelector = (selector: SelectorLike): boolean => {
  for (const node of selector.nodes) {
    if (node.type === 'combinator') return false
    if (node.type === 'class' && (node.value === 'scope-sentry-root' || node.value?.startsWith('el-'))) {
      return true
    }
  }
  return false
}

const makeScopedSelector = (
  source: SelectorLike,
  relation?: string,
  addDescendant = false,
): string => {
  const scoped = selectorParser.selector()
  scoped.append(selectorParser().astSync(SCOPE_SELECTOR).nodes[0].clone())
  if (relation !== undefined) {
    scoped.append(selectorParser.combinator({ value: relation }))
  } else if (addDescendant) {
    scoped.append(selectorParser.combinator({ value: ' ' }))
  }
  source.nodes.forEach((node) => scoped.append(node.clone()))
  return scoped.toString()
}

const scopeSelector = (selectorText: string): string => {
  const scopedSelectors: string[] = []
  selectorParser((selectors) => {
    selectors.each((selector) => {
      const firstMeaningfulNode = () =>
        selector.nodes.find((node) => node.type !== 'comment' && node.type !== 'combinator')

      let replacedRoot = false
      let rootRelation: string | undefined
      while (true) {
        const firstNode = firstMeaningfulNode()
        if (!firstNode || !isRootNode(firstNode)) break
        replacedRoot = true
        const index = selector.nodes.indexOf(firstNode)
        firstNode.remove()
        const followingNode = selector.nodes[index]
        if (followingNode?.type === 'combinator') {
          rootRelation = followingNode.value || ' '
          followingNode.remove()
        }
      }

      if (!firstMeaningfulNode()) {
        scopedSelectors.push(makeScopedSelector(selector))
        return
      }

      const portalRoot = isPortalRootSelector(selector)
      scopedSelectors.push(
        makeScopedSelector(selector, replacedRoot ? rootRelation : undefined, !replacedRoot),
      )
      // Body-mounted Element Plus overlays are marked on their own root node.
      // Keep their own root selectors applicable as well as descendant-scoped.
      if (portalRoot && (!replacedRoot || rootRelation === ' ')) {
        scopedSelectors.push(makeScopedSelector(selector))
      }
    })
  }).processSync(selectorText)
  return scopedSelectors.join(', ')
}

const isKeyframesRule = (rule: { parent?: { type?: string; name?: string } | undefined }): boolean => {
  let parent = rule.parent
  while (parent) {
    if (parent.type === 'atrule' && parent.name && /keyframes$/i.test(parent.name)) return true
    parent = (parent as { parent?: { type?: string; name?: string } }).parent
  }
  return false
}

export const scopeSentryCssPlugin = () => ({
  postcssPlugin: 'scopesentry-owned-root',
  Once(root: Root) {
    root.walkRules((rule) => {
      if (isKeyframesRule(rule)) return
      rule.selector = scopeSelector(rule.selector)
    })
  }
})

;(scopeSentryCssPlugin as typeof scopeSentryCssPlugin & { postcss?: boolean }).postcss = true
