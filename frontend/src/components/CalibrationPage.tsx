import { useCallback, useEffect, useState } from "react";
import { getJson, postJson, settle } from "../api";
import { fmtInt, fmtNum } from "../format";
import type { CalibrationInfo, Capture, Snapshot, Solved } from "../types";

const CELLS = ["TL", "TR", "BR", "BL"] as const;
const CORNER_TEXT = ["top-left", "top-right", "bottom-right", "bottom-left"];
// A capture averages the last 2 s; waiting this long first means it contains only
// readings taken after the weight was placed.
const SETTLE_MS = 2300;

type Busy = null | "capture" | "save";

export function CalibrationPage({ snapshot }: { snapshot: Snapshot }) {
  const [info, setInfo] = useState<CalibrationInfo | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      setInfo(await getJson<CalibrationInfo>("/api/calibration"));
    } catch (e) {
      setError((e as Error).message);
    }
  }, []);
  useEffect(() => {
    void refresh();
  }, [refresh]);

  const onSaved = async (message: string) => {
    setNotice(message);
    setError(null);
    await refresh();
  };

  return (
    <div className="stack">
      {info && <DefaultsPanel info={info} onSaved={onSaved} onError={setError} />}
      {info && <ActiveProfile info={info} />}
      {error && <p className="error" role="alert">{error}</p>}
      {notice && <p className="notice" role="status">{notice}</p>}
      <ManualCalibration snapshot={snapshot} info={info} onSaved={onSaved} onError={setError} />
      <FourCornerWizard snapshot={snapshot} onSaved={onSaved} onError={setError} />
    </div>
  );
}

function DefaultsPanel({ info, onSaved, onError }: {
  info: CalibrationInfo;
  onSaved: (message: string) => Promise<void>;
  onError: (message: string | null) => void;
}) {
  const d = info.defaults;
  const useDefaults = async () => {
    try {
      await postJson("/api/calibration/use-defaults");
      await onSaved("Default coefficients are now used for every calculation.");
    } catch (e) {
      onError((e as Error).message);
    }
  };
  const fromActive = async () => {
    if (!info.active) return;
    try {
      await postJson("/api/calibration/defaults", {
        zeros: info.active.zeros, counts_per_kg: info.active.counts_per_kg, note: `From ${info.active.method}`,
      });
      await onSaved("The coefficients in use were saved as the defaults.");
    } catch (e) {
      onError((e as Error).message);
    }
  };

  return (
    <section className={`panel ${d.present ? "" : "attention"}`}>
      <div className="panel-head">
        <h2>Default coefficients</h2>
        {info.in_use === "defaults" && <span className="badge badge-ok">In use</span>}
      </div>
      {!d.present ? (
        <>
          <p><strong>Default values not present.</strong> <span className="muted">Looked for {d.path}</span></p>
          <p className="hint">
            Set them from the coefficients in use, or enter values below and choose
            "Save these values as defaults".
          </p>
          <button className="btn primary" onClick={fromActive} disabled={!info.active}>
            Set the coefficients in use as defaults
          </button>
        </>
      ) : (
        <>
          <table className="coeffs">
            <thead><tr><th /> {CELLS.map((c) => <th key={c}>{c}</th>)}</tr></thead>
            <tbody>
              <tr><th>Zero</th>{(d.zeros ?? []).map((z, i) => <td key={i}>{fmtInt(z)}</td>)}</tr>
              <tr><th>Counts/kg</th>{(d.counts_per_kg ?? []).map((c, i) => <td key={i}>{fmtNum(c, 2)}</td>)}</tr>
            </tbody>
          </table>
          <p className="hint">
            Read from {d.path} at every start{d.saved_at ? `; saved ${d.saved_at.replace("T", " ").slice(0, 16)} UTC` : ""}
            {d.firmware_bcd ? `, firmware ${d.firmware_bcd}` : ""}.{d.note ? ` ${d.note}.` : ""}
          </p>
          <div className="actions">
            <button className="btn primary" onClick={useDefaults} disabled={info.in_use === "defaults"}>
              {info.in_use === "defaults" ? "Default coefficients in use" : "Use default coefficients"}
            </button>
            {info.active && info.in_use !== "defaults" && (
              <button className="btn" onClick={fromActive}>Replace defaults with the coefficients in use</button>
            )}
          </div>
        </>
      )}
    </section>
  );
}

function ActiveProfile({ info }: { info: CalibrationInfo }) {
  const p = info.active;
  return (
    <section className="panel">
      <h2>Coefficients in use{" "}
        <span className="muted">
          · {info.in_use === "defaults" ? "the defaults" : info.in_use === "custom" ? "custom values" : "none"}
        </span>
      </h2>
      <p className="hint">Every weight, load, chart and gait value in the software is calculated with these.</p>
      {info.status === "firmware_mismatch" && <p className="error">{info.message}</p>}
      {!p ? (
        <p className="muted">None saved. Weight is not shown until a calibration is saved.</p>
      ) : (
        <>
          <p className="muted">
            {p.method.replaceAll("_", " ")} · saved {p.created_at.replace("T", " ").slice(0, 16)} UTC
            {p.firmware_bcd ? ` · firmware ${p.firmware_bcd}` : ""}
            {p.known_weight_kg ? ` · reference ${p.known_weight_kg} kg` : ""}
          </p>
          <table className="coeffs">
            <thead>
              <tr><th /> {CELLS.map((c) => <th key={c}>{c}</th>)}</tr>
            </thead>
            <tbody>
              <tr><th>Zero</th>{p.zeros.map((z, i) => <td key={i}>{fmtInt(z)}</td>)}</tr>
              <tr><th>Counts/kg</th>{p.counts_per_kg.map((c, i) => <td key={i}>{fmtNum(c, 2)}</td>)}</tr>
            </tbody>
          </table>
        </>
      )}
    </section>
  );
}

interface FormProps {
  snapshot: Snapshot;
  onSaved: (message: string) => Promise<void>;
  onError: (message: string | null) => void;
}

function ManualCalibration({ snapshot, info, onSaved, onError }: FormProps & { info: CalibrationInfo | null }) {
  const [zeros, setZeros] = useState<string[]>(["", "", "", ""]);
  const [coeffs, setCoeffs] = useState<string[]>(["", "", "", ""]);
  const [method, setMethod] = useState("manual");
  const [knownKg, setKnownKg] = useState("20");
  const [busy, setBusy] = useState<Busy>(null);
  const [lastCapture, setLastCapture] = useState<Capture | null>(null);

  // Start from the active profile, so a tare-only refresh keeps its coefficients.
  useEffect(() => {
    if (info?.active && zeros.every((z) => z === "")) {
      setZeros(info.active.zeros.map((z) => String(Math.round(z))));
      setCoeffs(info.active.counts_per_kg.map((c) => String(c)));
    }
  }, [info, zeros]);

  const capture = async (): Promise<Capture | null> => {
    setBusy("capture");
    onError(null);
    try {
      await settle(SETTLE_MS);
      const result = await postJson<Capture>("/api/calibration/capture");
      setLastCapture(result);
      return result;
    } catch (e) {
      onError((e as Error).message);
      return null;
    } finally {
      setBusy(null);
    }
  };

  const loadDefaults = () => {
    const d = info?.defaults;
    if (!d?.present || !d.zeros || !d.counts_per_kg) return;
    setZeros(d.zeros.map((z) => String(z)));
    setCoeffs(d.counts_per_kg.map((c) => String(c)));
    setMethod("manual");
  };

  const saveAsDefaults = async () => {
    setBusy("save");
    try {
      await postJson("/api/calibration/defaults", { zeros: zeros.map(Number), counts_per_kg: coeffs.map(Number) });
      await onSaved("Saved as the default coefficients. Choose \"Use default coefficients\" to use them.");
    } catch (e) {
      onError((e as Error).message);
    } finally {
      setBusy(null);
    }
  };

  const captureTare = async () => {
    const c = await capture();
    if (c) setZeros(c.means.map((m) => String(Math.round(m))));
  };

  const calculate = async () => {
    const zeroValues = zeros.map(Number);
    if (zeroValues.some((z, i) => zeros[i] === "" || !Number.isFinite(z))) {
      onError("Capture the empty-deck tare first.");
      return;
    }
    const kg = Number(knownKg);
    if (!(kg > 0)) {
      onError("Enter the known weight in kilograms.");
      return;
    }
    const c = await capture();
    if (!c) return;
    try {
      const solved = await postJson<Solved>("/api/calibration/solve", {
        known_weight_kg: kg,
        zeros: zeroValues,
        loaded: [c.means],
      });
      setCoeffs(solved.counts_per_kg.map((v) => String(v)));
      setMethod(solved.method);
    } catch (e) {
      onError((e as Error).message);
    }
  };

  const save = async () => {
    setBusy("save");
    try {
      await postJson("/api/calibration", {
        zeros: zeros.map(Number),
        counts_per_kg: coeffs.map(Number),
        method,
        known_weight_kg: method === "one_capture" ? Number(knownKg) : null,
      });
      await onSaved("These coefficients are now used for every calculation.");
    } catch (e) {
      onError((e as Error).message);
    } finally {
      setBusy(null);
    }
  };

  const preview = CELLS.map((_, i) => {
    const raw = snapshot.channels[i]?.mean;
    const z = Number(zeros[i]);
    const c = Number(coeffs[i]);
    return raw != null && zeros[i] !== "" && coeffs[i] !== "" && c !== 0 ? (raw - z) / c : null;
  });
  const previewTotal = preview.every((p) => p !== null) ? preview.reduce((a, b) => a! + b!, 0) : null;
  const ready = snapshot.capture_ready && busy === null;

  return (
    <section className="panel">
      <h2>Other coefficients: calibrate or enter values</h2>
      <p className="hint">
        Weight per cell = (current raw − zero) ÷ counts per kg. Counts per kg is negative on this deck: the raw
        value falls under load.
      </p>
      <div className="actions">
        <button className="btn" onClick={loadDefaults} disabled={!info?.defaults.present}>Load default values</button>
        <button className="btn" onClick={captureTare} disabled={!ready}>
          {busy === "capture" ? "Capturing…" : "Capture empty-deck tare"}
        </button>
      </div>

      <div className="known-weight">
        <label>
          Known weight (kg)
          <input inputMode="decimal" value={knownKg} onChange={(e) => setKnownKg(e.target.value)} />
        </label>
        <button className="btn primary" onClick={calculate} disabled={!ready}>
          {busy === "capture" ? "Capturing…" : "Put the weight on the deck, then calculate"}
        </button>
      </div>
      <p className="hint">
        The known weight can stand anywhere: this uses the change in the sum of all four cells. It gives one
        shared coefficient; the four-corner calibration below gives each cell its own.
      </p>

      <table className="coeffs editable">
        <thead>
          <tr><th /> {CELLS.map((c) => <th key={c}>{c}</th>)}</tr>
        </thead>
        <tbody>
          <tr>
            <th>Zero</th>
            {zeros.map((z, i) => (
              <td key={i}>
                <input aria-label={`${CELLS[i]} zero`} inputMode="decimal" value={z}
                  onChange={(e) => { setZeros(zeros.map((v, j) => (j === i ? e.target.value : v))); }} />
              </td>
            ))}
          </tr>
          <tr>
            <th>Counts/kg</th>
            {coeffs.map((c, i) => (
              <td key={i}>
                <input aria-label={`${CELLS[i]} counts per kg`} inputMode="decimal" value={c}
                  onChange={(e) => {
                    setCoeffs(coeffs.map((v, j) => (j === i ? e.target.value : v)));
                    setMethod("manual");
                  }} />
              </td>
            ))}
          </tr>
          <tr>
            <th>Now</th>
            {preview.map((p, i) => <td key={i} className="muted">{p === null ? "—" : `${fmtNum(p, 2)} kg`}</td>)}
          </tr>
        </tbody>
      </table>
      <p className="hint">
        Preview total: <strong>{previewTotal === null ? "—" : `${fmtNum(previewTotal, 2)} kg`}</strong>
        {lastCapture && !lastCapture.stable && " · the last capture was fluctuating; consider repeating it"}
      </p>
      <div className="actions">
        <button className="btn primary" onClick={save} disabled={busy !== null}>
          {busy === "save" ? "Saving…" : "Use these coefficients"}
        </button>
        <button className="btn" onClick={saveAsDefaults} disabled={busy !== null}>Save these values as defaults</button>
      </div>
    </section>
  );
}

function FourCornerWizard({ snapshot, onSaved, onError }: FormProps) {
  const [knownKg, setKnownKg] = useState("20");
  const [zeros, setZeros] = useState<number[] | null>(null);
  const [rows, setRows] = useState<number[][]>([]);
  const [result, setResult] = useState<Solved | null>(null);
  const [busy, setBusy] = useState<Busy>(null);

  const step = zeros === null ? 0 : rows.length + 1; // 0 tare, 1-4 corners, 5 done
  const reset = () => {
    setZeros(null);
    setRows([]);
    setResult(null);
  };

  const captureStep = async () => {
    const kg = Number(knownKg);
    if (!(kg > 0)) {
      onError("Enter the known weight in kilograms.");
      return;
    }
    setBusy("capture");
    onError(null);
    try {
      await settle(SETTLE_MS);
      const c = await postJson<Capture>("/api/calibration/capture");
      if (zeros === null) {
        setZeros(c.means);
        return;
      }
      const next = [...rows, c.means];
      setRows(next);
      if (next.length === 4) {
        setResult(await postJson<Solved>("/api/calibration/solve", { known_weight_kg: kg, zeros, loaded: next }));
      }
    } catch (e) {
      onError((e as Error).message);
    } finally {
      setBusy(null);
    }
  };

  const save = async () => {
    if (!result || !zeros) return;
    setBusy("save");
    try {
      await postJson("/api/calibration", {
        zeros, counts_per_kg: result.counts_per_kg, method: result.method, known_weight_kg: Number(knownKg),
      });
      await onSaved("Four-corner calibration saved.");
      reset();
    } catch (e) {
      onError((e as Error).message);
    } finally {
      setBusy(null);
    }
  };

  const instruction =
    step === 0
      ? "Step 1 of 5: remove everything from the deck, then capture the tare."
      : step <= 4
        ? `Step ${step + 1} of 5: place the ${knownKg} kg weight directly over the ${CORNER_TEXT[step - 1]} cell, then capture.`
        : "All four corners captured.";

  return (
    <section className="panel">
      <div className="panel-head">
        <h2>Four-corner calibration</h2>
        {step > 0 && <button className="btn ghost" onClick={reset}>Start over</button>}
      </div>
      <p className="hint">
        Gives each cell its own coefficient. All four cells are read at every position — the other three carry
        part of the weight too — and the four positions are solved together.
      </p>
      <label className="inline">
        Known weight (kg)
        <input inputMode="decimal" value={knownKg} disabled={step > 0}
          onChange={(e) => setKnownKg(e.target.value)} />
      </label>
      <ol className="steps">
        {["Empty deck", ...CORNER_TEXT.map((c) => `Weight over ${c}`)].map((label, i) => (
          <li key={label} className={i < step ? "done" : i === step ? "current" : ""}>{label}</li>
        ))}
      </ol>
      <p className="instruction">{instruction}</p>
      {step <= 4 && (
        <button className="btn primary" onClick={captureStep} disabled={!snapshot.capture_ready || busy !== null}>
          {busy === "capture" ? "Capturing… hold still" : step === 0 ? "Capture tare" : `Capture ${CELLS[step - 1]}`}
        </button>
      )}
      {result && (
        <div className="result">
          <p>
            {result.kind === "per_cell"
              ? "Each cell solved separately:"
              : "The four positions were too alike to separate the cells, so one shared coefficient is used:"}
          </p>
          <table className="coeffs">
            <thead><tr>{CELLS.map((c) => <th key={c}>{c}</th>)}</tr></thead>
            <tbody><tr>{result.counts_per_kg.map((c, i) => <td key={i}>{fmtNum(c, 2)}</td>)}</tr></tbody>
          </table>
          <button className="btn primary" onClick={save} disabled={busy !== null}>Use these coefficients</button>
        </div>
      )}
    </section>
  );
}
