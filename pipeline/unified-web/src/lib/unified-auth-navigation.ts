export const ARTEX_AUTH_REQUIRED_EVENT = "project-malaria:artex-auth-required";

export function requestArtexLogin(): void {
  if (typeof window === "undefined") return;
  window.dispatchEvent(new Event(ARTEX_AUTH_REQUIRED_EVENT));
}
