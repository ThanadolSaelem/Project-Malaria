import { createStandaloneScopeSentry } from './bootstrap'

// The standalone entry keeps the original #app mount, native hash history,
// Pinia persistence, i18n, global components, Element Plus, UnoCSS, SVG icons,
// animation styles, and permission guards.
void createStandaloneScopeSentry('#app')
