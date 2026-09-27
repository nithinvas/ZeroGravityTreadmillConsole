import { useCallback, useState } from "react";
import type { LogEntry } from "../types";
import { useSocket } from "../useSocket";

const LEVELS = ["debug", "info", "warning", "error"] as const;
const RANK: Record<string, number> = { debug: 0, info: 1, warning: 2, error: 3 };
const KEEP = 400;

export function LogPanel() {
  const [entries, setEntries] = useState<LogEntry[]>([]);
  const [level, setLevel] = useState<(typeof LEVELS)[number]>("info");
  const [component, setComponent] = useState("all");
  const [paused, setPaused] = useState(false);

  const onMessage = useCallback(
    (entry: LogEntry) => {
      if (paused) return;
      setEntries((prev) => [...prev.slice(-(KEEP - 1)), entry]);
    },
    [paused],
  );
  const status = useSocket<LogEntry>("/ws/logs", onMessage);

  const components = ["all", ...Array.from(new Set(entries.map((e) => e.component))).sort()];
  const shown = entries
    .filter((e) => RANK[e.level] >= RANK[level] && (component === "all" || e.component === component))
    .slice(-150)
    .reverse();

  return (
    <section className="panel logs">
      <div className="panel-head">
        <h2>Live log {status !== "open" && <span className="muted">({status})</span>}</h2>
        <div className="actions">
          <select value={level} onChange={(e) => setLevel(e.target.value as (typeof LEVELS)[number])} aria-label="Level">
            {LEVELS.map((l) => <option key={l} value={l}>{l}+</option>)}
          </select>
          <select value={component} onChange={(e) => setComponent(e.target.value)} aria-label="Component">
            {components.map((c) => <option key={c} value={c}>{c}</option>)}
          </select>
          <button className="btn ghost" onClick={() => setPaused((p) => !p)}>{paused ? "Resume" : "Pause"}</button>
        </div>
      </div>
      <ol className="log-lines">
        {shown.map((e, i) => (
          <li key={`${e.ts}-${i}`} className={`log-${e.level}`}>
            <span className="mono muted">{e.ts.slice(11, 23)}</span>{" "}
            <span className="log-level">{e.level}</span>{" "}
            <span className="mono">{e.event}</span>{" "}
            <span>{e.msg}</span>
          </li>
        ))}
      </ol>
    </section>
  );
}
