import { cp, mkdir, readdir, readFile, stat, writeFile } from 'node:fs/promises'
import { dirname, join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import postcss from 'postcss'
import selectorParser from 'postcss-selector-parser'

const scriptDirectory = dirname(fileURLToPath(import.meta.url))
const repositoryRoot = resolve(scriptDirectory, '../../../..')
const nativeStaticRoot = resolve(repositoryRoot, 'pipeline/scopesentry/cmd/main/static')
const modulePublicRoot = resolve(
  repositoryRoot,
  'pipeline/unified-web/public/_modules/scopesentry/native-map'
)

// The map's generated JS imports stay under js/ and ../assets/, with its entry CSS under css/.
// lib/, draco/, png/, and root logo assets are copied because generated map chunks can
// address them relatively. Runtime plugin/data URLs are deliberately not copied: the
// lexical adapter below keeps them backend-owned under /scopesentry-api.
const LOCAL_MAP_DIRECTORIES = ['js', 'assets', 'css', 'lib', 'draco', 'png']
const LOCAL_MAP_FILES = ['logo.png']
const ROOT_NAMESPACE_RE = /(["'`])\/(api|images|plugins)(?=\/|["'`])/g
const MAP_SCOPE_SELECTOR = '[data-scopesentry-map]'
const ROOT_ELEMENT_NAMES = new Set(['html', 'body'])

const isRootNode = (node) =>
  (node.type === 'tag' && ROOT_ELEMENT_NAMES.has(node.value || '')) ||
  (node.type === 'pseudo' && node.value === ':root')

const isKeyframesRule = (rule) => {
  let parent = rule.parent
  while (parent) {
    if (parent.type === 'atrule' && parent.name && /keyframes$/i.test(parent.name)) return true
    parent = parent.parent
  }
  return false
}

const scopeMapStylesheet = (source) => {
  const root = postcss.parse(source)
  root.walkRules((rule) => {
    if (isKeyframesRule(rule)) return
    const scopedSelectors = []
    selectorParser((selectors) => {
      selectors.each((selector) => {
        const firstMeaningfulNode = () =>
          selector.nodes.find((node) => node.type !== 'comment' && node.type !== 'combinator')
        let replacedRoot = false
        let rootRelation
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
          scopedSelectors.push(MAP_SCOPE_SELECTOR)
          return
        }

        const scoped = selectorParser.selector()
        scoped.append(selectorParser().astSync(MAP_SCOPE_SELECTOR).nodes[0].clone())
        if (replacedRoot) {
          if (rootRelation !== undefined) {
            scoped.append(selectorParser.combinator({ value: rootRelation }))
          }
        } else {
          scoped.append(selectorParser.combinator({ value: ' ' }))
        }
        selector.nodes.forEach((node) => scoped.append(node.clone()))
        scopedSelectors.push(scoped.toString())
      })
    }).processSync(rule.selector)
    rule.selector = scopedSelectors.join(', ')
  })
  return root.toString()
}

const adaptGeneratedMapJavaScript = (source, relativePath) => {
  if (
    !relativePath.endsWith('.js') ||
    (!relativePath.startsWith('js/') && !relativePath.startsWith('assets/'))
  ) {
    return source
  }
  return source.replace(ROOT_NAMESPACE_RE, '$1/scopesentry-api/$2')
}

const copyPreparedFile = async (sourcePath, targetPath, relativePath) => {
  await mkdir(dirname(targetPath), { recursive: true })
  if (relativePath.endsWith('.css')) {
    const source = await readFile(sourcePath, 'utf8')
    await writeFile(targetPath, scopeMapStylesheet(source))
    return
  }
  if (relativePath.endsWith('.js')) {
    const source = await readFile(sourcePath, 'utf8')
    const adapted = adaptGeneratedMapJavaScript(source, relativePath)
    await writeFile(targetPath, adapted)
    return
  }
  await cp(sourcePath, targetPath)
}

const copyTree = async (sourceDirectory, targetDirectory, prefix = '') => {
  const entries = await readdir(sourceDirectory, { withFileTypes: true })
  for (const entry of entries) {
    const sourcePath = join(sourceDirectory, entry.name)
    const relativePath = prefix ? `${prefix}/${entry.name}` : entry.name
    const targetPath = join(targetDirectory, entry.name)
    if (entry.isDirectory()) {
      await copyTree(sourcePath, targetPath, relativePath)
    } else if (entry.isFile()) {
      await copyPreparedFile(sourcePath, targetPath, relativePath)
    }
  }
}

const main = async () => {
  await mkdir(modulePublicRoot, { recursive: true })
  for (const directory of LOCAL_MAP_DIRECTORIES) {
    const sourceDirectory = join(nativeStaticRoot, directory)
    const targetDirectory = join(modulePublicRoot, directory)
    await copyTree(sourceDirectory, targetDirectory, directory)
  }
  for (const file of LOCAL_MAP_FILES) {
    const sourcePath = join(nativeStaticRoot, file)
    const targetPath = join(modulePublicRoot, file)
    const sourceStat = await stat(sourcePath)
    if (sourceStat.isFile()) await copyPreparedFile(sourcePath, targetPath, file)
  }
}

main().catch((error) => {
  console.error('[ScopeSentry] native Map asset preparation failed', error)
  process.exitCode = 1
})
