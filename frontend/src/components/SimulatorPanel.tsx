import { useState } from "react";
import { postJson } from "../api";

const SPOTS: Record<string, [number, number]> = {
  Centre: [0.5, 0.5],
  TL: [0.1, 0.1],
  TR: [0.9, 0.1],
  BR: [0.9, 0.9],
  BL: [0.1, 0.9],
};

/** Shown only when the backend runs the simulator: stands in for putting weights on a real deck. */
export function SimulatorPanel({ mode }: { mode: string }) {
  const [kg, setKg] = useState("20");
  const [error, setError] = useState<string | null>(null);

  const send = async (body: object) => {
    setError(null);
    try {
      await postJson("/api/simulator/load", body);
    } catch (e) {
      setError((e as Error).message);
    }
  };

  return (
    <section className="panel sim">
      <h2>Simulator <span className="muted">· now: {mode}</span></h2>
      <div className="actions">
        <button className="btn" onClick={() => send({ mode: "empty" })}>Empty deck</button>
        <button className="btn" onClick={() => send({ mode: "walking" })}>Walker</button>
      </div>
      <div className="actions">
        <label className="inline">
          Weight (kg)
          <input inputMode="decimal" value={kg} onChange={(e) => setKg(e.target.value)} />
        </label>
        {Object.entries(SPOTS).map(([name, [x, y]]) => (
          <button key={name} className="btn" onClick={() => send({ mode: "static", kg: Number(kg), x, y })}>
            {name}
          </button>
        ))}
      </div>
      {error && <p className="error">{error}</p>}
    </section>
  );
}
