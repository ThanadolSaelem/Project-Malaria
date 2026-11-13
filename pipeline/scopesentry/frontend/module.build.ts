import { resolve } from 'node:path'
import type { UserConfig } from 'vite'
import { scopeSentryCssPlugin } from './build/scope-sentry-css'

const unifiedModuleOutput = resolve(process.cwd(), '../../unified-web/public/_modules/scopesentry')

export const scopeSentryModuleBuild: UserConfig = {
  base: '/_modules/scopesentry/',
  css: {
    postcss: {
      plugins: [scopeSentryCssPlugin()]
    }
  },
  build: {
    outDir: unifiedModuleOutput,
    emptyOutDir: false,
    copyPublicDir: true,
    cssCodeSplit: false,
    assetsInlineLimit: 0,
    sourcemap: false,
    rollupOptions: {
      input: resolve(process.cwd(), 'src/module.ts'),
      preserveEntrySignatures: 'strict',
      output: {
        format: 'es',
        entryFileNames: 'module.js',
        chunkFileNames: 'chunks/[name]-[hash].js',
        assetFileNames: (assetInfo) => {
          if (assetInfo.name?.endsWith('.css')) return 'module.css'
          return 'assets/[name]-[hash][extname]'
        },
        inlineDynamicImports: false
      }
    }
  }
}
