import type { StreamWarning } from "../types";

export function Warnings({ warnings }: { warnings: StreamWarning[] }) {
  if (warnings.length === 0) return null;
  return (
    <section className="warnings" role="alert">
      {warnings.map((w) => (
        <div key={w.code} className={`warning ${w.code === "channels_identical" || w.code === "no_data" ? "severe" : ""}`}>
          <span className="warning-icon" aria-hidden="true">!</span>
          <span>{w.message}</span>
        </div>
      ))}
    </section>
  );
}
