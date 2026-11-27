export interface UnifiedModuleProps {
  active: boolean;
  theme: "light" | "dark";
  path: string;
  onNavigate: (path: string, replace?: boolean) => void;
}
