import type { ResolvedThemeMode } from "@/lib/preferences/theme";

export const QWEN_THEME_TOKENS: Record<ResolvedThemeMode, Record<string, string>> = {
  light: {
    "--qwen-background": "#ffffff",
    "--qwen-foreground": "#0a0a0b",
    "--qwen-accent": "#0033ff",
  },
  dark: {
    "--qwen-background": "#0d0d0d",
    "--qwen-foreground": "#fafafa",
    "--qwen-accent": "#6785ff",
  },
};

export function applyUnifiedTheme(mode: ResolvedThemeMode): void {
  const root = document.documentElement;
  root.dataset.unifiedTheme = mode;

  for (const [name, value] of Object.entries(QWEN_THEME_TOKENS[mode])) {
    root.style.setProperty(name, value);
  }
}
