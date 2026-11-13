"use client";

import { useEffect, useState } from "react";

import type { UnifiedModuleProps } from "../types";

const OBSERVER_POLL_INTERVAL_MS = 5000;

interface ObserverAlert {
  level: "credential" | "critical";
  time: string;
  text: string;
}

interface ObserverTimelineEntry {
  time: string;
  en: string;
}

interface ObserverState {
  updated: string | null;
  en: string;
  th: string;
  alerts: ObserverAlert[];
  timeline: ObserverTimelineEntry[];
  online: boolean;
}

const INITIAL_STATE: ObserverState = {
  updated: null,
  en: "(กำลังเริ่ม…)",
  th: "(กำลังเริ่ม…)",
  alerts: [],
  timeline: [],
  online: false,
};

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

function isObserverAlert(value: unknown): value is ObserverAlert {
  if (!isRecord(value)) return false;

  return (
    (value.level === "credential" || value.level === "critical") &&
    typeof value.time === "string" &&
    typeof value.text === "string"
  );
}

function isObserverTimelineEntry(value: unknown): value is ObserverTimelineEntry {
  return isRecord(value) && typeof value.time === "string" && typeof value.en === "string";
}

function parseObserverState(value: unknown): ObserverState {
  if (!isRecord(value)) throw new Error("Observer state is unavailable");

  const { updated, en, th, alerts, timeline, online } = value;
  if (
    (updated !== null && typeof updated !== "string") ||
    typeof en !== "string" ||
    typeof th !== "string" ||
    !Array.isArray(alerts) ||
    !alerts.every(isObserverAlert) ||
    !Array.isArray(timeline) ||
    !timeline.every(isObserverTimelineEntry) ||
    typeof online !== "boolean"
  ) {
    throw new Error("Observer state is unavailable");
  }

  return { updated, en, th, alerts, timeline, online };
}

export default function ObserverModule({ active, theme }: UnifiedModuleProps) {
  const [state, setState] = useState<ObserverState>(INITIAL_STATE);

  useEffect(() => {
    let disposed = false;

    const tick = async () => {
      try {
        const response = await fetch("/observer-api/state", { cache: "no-store" });
        if (!response.ok) throw new Error(`Observer unavailable (${response.status})`);

        const payload: unknown = await response.json();
        if (!disposed) setState(parseObserverState(payload));
      } catch {
        // Keep the last received state, matching the native dashboard's failure behavior;
        // the status indicator makes the unavailable backend state explicit.
        if (!disposed) setState((current) => ({ ...current, online: false }));
      }
    };

    void tick();
    const interval = window.setInterval(() => void tick(), OBSERVER_POLL_INTERVAL_MS);

    return () => {
      disposed = true;
      window.clearInterval(interval);
    };
  }, []);

  return (
    <main
      className="observer-module"
      data-theme={theme}
      hidden={!active}
      aria-hidden={!active}
      aria-label="Pentest Monitor"
    >
      <style>{`
        .observer-module {
          --observer-bg: #ffffff;
          --observer-card: #f7f7f8;
          --observer-line: #e3e3e5;
          --observer-fg: #0a0a0b;
          --observer-mut: #667085;
          --observer-accent: #0033ff;
          --observer-red: #f85149;
          --observer-amber: #d29922;
          --observer-green: #3fb950;
          --observer-critical-bg: #fff8e7;
          --observer-credential-bg: #fff1f2;
          box-sizing: border-box;
          min-height: 100%;
          width: 100%;
          overflow: visible;
          padding: 16px;
          background: var(--observer-bg);
          color: var(--observer-fg);
          font: 15px/1.6 -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
        }
        .observer-module[data-theme="dark"] {
          --observer-bg: #0d0d0d;
          --observer-card: #151515;
          --observer-line: rgba(255, 255, 255, 0.14);
          --observer-fg: #fafafa;
          --observer-mut: #8b949e;
          --observer-accent: #6785ff;
          --observer-critical-bg: #1c1a10;
          --observer-credential-bg: #2a1215;
        }
        .observer-module *,
        .observer-module *::before,
        .observer-module *::after {
          box-sizing: border-box;
        }
        .observer-header {
          margin: 0 0 16px;
        }
        .observer-title {
          align-items: center;
          display: flex;
          font-size: 18px;
          gap: 6px;
          line-height: 1.35;
          margin: 0 0 4px;
        }
        .observer-title-muted {
          color: var(--observer-mut);
          font-weight: 400;
        }
        .observer-dot {
          background: var(--observer-green);
          border-radius: 999px;
          display: inline-block;
          flex: 0 0 auto;
          height: 9px;
          margin-right: 0;
          width: 9px;
        }
        .observer-dot.is-offline {
          background: var(--observer-red);
        }
        .observer-status {
          color: var(--observer-mut);
          font-size: 12px;
          font-weight: 500;
          letter-spacing: 0.02em;
          margin-left: 2px;
        }
        .observer-subtitle {
          color: var(--observer-mut);
          font-size: 13px;
          margin: 0;
        }
        .observer-grid {
          display: grid;
          gap: 14px;
          grid-template-columns: repeat(2, minmax(0, 1fr));
        }
        .observer-card {
          background: var(--observer-card);
          border: 1px solid var(--observer-line);
          border-radius: 10px;
          min-width: 0;
          padding: 14px;
        }
        .observer-card-heading {
          color: var(--observer-mut);
          font-size: 13px;
          letter-spacing: 0.04em;
          margin: 0 0 8px;
          text-transform: uppercase;
        }
        .observer-body {
          white-space: pre-wrap;
          overflow-wrap: anywhere;
        }
        .observer-alerts {
          margin: 14px 0;
        }
        .observer-alert {
          background: var(--observer-critical-bg);
          border-left: 3px solid var(--observer-amber);
          border-radius: 6px;
          margin-bottom: 8px;
          padding: 8px 12px;
          overflow-wrap: anywhere;
        }
        .observer-alert:last-child {
          margin-bottom: 0;
        }
        .observer-alert.credential {
          background: var(--observer-credential-bg);
          border-color: var(--observer-red);
        }
        .observer-alert-tag {
          font-weight: 700;
          margin-right: 8px;
        }
        .observer-alert.credential .observer-alert-tag {
          color: var(--observer-red);
        }
        .observer-alert.critical .observer-alert-tag {
          color: var(--observer-amber);
        }
        .observer-alert-time,
        .observer-timeline-time {
          color: var(--observer-mut);
          font-size: 12px;
        }
        .observer-timeline {
          margin-top: 14px;
        }
        .observer-timeline-row {
          border-top: 1px solid var(--observer-line);
          font-size: 13px;
          padding: 8px 0;
          overflow-wrap: anywhere;
        }
        .observer-empty {
          color: var(--observer-mut);
        }
        @media (max-width: 720px) {
          .observer-grid {
            grid-template-columns: 1fr;
          }
        }
        @media (prefers-reduced-motion: reduce) {
          .observer-module * {
            scroll-behavior: auto !important;
            transition-duration: 0.01ms !important;
          }
        }
      `}</style>

      <header className="observer-header">
        <h1 className="observer-title">
          <span
            className={`observer-dot${state.online ? "" : " is-offline"}`}
            aria-label={state.online ? "Online" : "Unavailable"}
            title={state.online ? "Online" : "Unavailable"}
          />
          <span>Pentest Monitor</span>
          <span className="observer-title-muted">— Tiel</span>
          <span className="observer-status" aria-live="polite">
            {state.online ? "Online" : "Unavailable"}
          </span>
        </h1>
        <p className="observer-subtitle">
          อัปเดตล่าสุด: <span>{state.updated || "—"}</span> · auto-refresh
        </p>
      </header>

      <section className="observer-alerts" aria-label="Alerts">
        {state.alerts.map((alert) => (
          <div className={`observer-alert ${alert.level}`} key={`${alert.level}|${alert.time}|${alert.text}`}>
            <span className="observer-alert-tag">
              {alert.level === "credential" ? "🔑 CREDENTIAL" : "🚨 CRITICAL"}
            </span>
            <span className="observer-alert-time">{alert.time}</span>
            <div>{alert.text}</div>
          </div>
        ))}
      </section>

      <section className="observer-grid" aria-label="Summaries">
        <article className="observer-card">
          <h2 className="observer-card-heading">🇬🇧 Summary (EN)</h2>
          <div className="observer-body">{state.en || "—"}</div>
        </article>
        <article className="observer-card">
          <h2 className="observer-card-heading">🇹🇭 สรุป (ไทย)</h2>
          <div className="observer-body">{state.th || "—"}</div>
        </article>
      </section>

      <section className="observer-card observer-timeline" aria-label="Timeline">
        <h2 className="observer-card-heading">Timeline</h2>
        <div>
          {state.timeline.map((entry) => (
            <div className="observer-timeline-row" key={`${entry.time}|${entry.en}`}>
              <span className="observer-timeline-time">{entry.time}</span>
              <div>{entry.en}</div>
            </div>
          ))}
          {state.timeline.length === 0 && <div className="observer-empty">—</div>}
        </div>
      </section>
    </main>
  );
}
