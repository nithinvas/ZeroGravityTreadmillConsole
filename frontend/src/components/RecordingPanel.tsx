import { useCallback, useEffect, useState } from "react";
import { fmtDuration, fmtInt } from "../format";
import type { RecordingMeta, RecordingStatus } from "../types";

export function RecordingPanel({ active }: { active: RecordingStatus | null }) {
  const [label, setLabel] = useState("");
  const [past, setPast] = useState<RecordingMeta[]>([]);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      const res = await fetch("/api/recordings");
      if (res.ok) setPast(await res.json());
    } catch {
      // The live view shows the connection problem; nothing to add here.
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh, active?.id]);

  const call = async (path: string, body?: unknown) => {
    setError(null);
    const res = await fetch(path, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: body === undefined ? undefined : JSON.stringify(body),
    });
    if (!res.ok) setError((await res.json().catch(() => ({}))).detail ?? `Failed (${res.status})`);
    await refresh();
  };

  return (
    <section className="panel">
      <h2>Recording</h2>
      {active ? (
        <div className="recording-live">
          <span className="rec-dot" aria-hidden="true" /> Recording <strong>{active.label || active.id}</strong>
          <span className="muted"> · {fmtDuration(active.elapsed_s)} · {fmtInt(active.transfers)} packets</span>
          <button className="btn danger" onClick={() => call("/api/recordings/stop")}>Stop recording</button>
        </div>
      ) : (
        <div className="recording-start">
          <input
            value={label}
            maxLength={80}
            placeholder="Label, e.g. press TL, 20 kg centre"
            onChange={(e) => setLabel(e.target.value)}
          />
          <button className="btn primary" onClick={() => call("/api/recordings/start", { label })}>
            Start recording
          </button>
        </div>
      )}
      {error && <p className="error">{error}</p>}
      {past.length > 0 && (
        <table className="recordings">
          <thead>
            <tr><th>Recording</th><th>Label</th><th>Length</th><th>Packets</th></tr>
          </thead>
          <tbody>
            {past.slice(0, 8).map((r) => (
              <tr key={r.id}>
                <td className="mono">{r.id}</td>
                <td>{r.label || "—"}</td>
                <td>{r.duration_s === null ? "in progress" : fmtDuration(r.duration_s)}</td>
                <td>{fmtInt(r.transfers)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </section>
  );
}
