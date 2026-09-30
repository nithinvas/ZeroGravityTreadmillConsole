import { useState } from "react";
import { postJson } from "../api";
import { fmtNum } from "../format";
import type { Snapshot } from "../types";
import type { Patient } from "./HomeScreen";
import type { Staff } from "./LockScreen";
import { Steps, TapNumber } from "./parts";

const DIAGNOSES = [
  "Post-op Knee Replacement", "Hip Fracture Recovery", "Ankle Ligament Repair",
  "Neurological Rehab", "Cardiac Rehabilitation", "Lumbar Disc Surgery",
  "Stroke Rehabilitation", "Arthritis Management", "Sports Injury Recovery",
  "Fracture Rehabilitation", "Spinal Cord Injury", "ACL Reconstruction",
];

/**
 * Every item has to be confirmed by a person before a patient is put on a
 * machine that moves. The critical ones are marked, and none of them can be
 * satisfied by the console itself — that is the point: these are the checks
 * software cannot make.
 */
const CHECKS = [
  { id: "zipper", critical: true, title: "Pressure Chamber Zipper Sealed",
    why: "Fully closed and sealed from hip to hip, with no gaps." },
  { id: "harness", critical: true, title: "Safety Harness Locked",
    why: "All buckles clicked in and straps adjusted to the patient." },
  { id: "footwear", critical: false, title: "Appropriate Footwear",
    why: "Proper athletic shoes, laces tied, nothing open-toed." },
  { id: "estop", critical: true, title: "Emergency Stop Accessible",
    why: "Within the patient's reach and confirmed working." },
  { id: "skin", critical: false, title: "No Open Wounds or Skin Breakdown",
    why: "Check for pressure sores or broken skin before loading." },
  { id: "oriented", critical: false, title: "Patient Stable and Oriented",
    why: "Alert, understands instructions, able to communicate during the session." },
  { id: "consent", critical: true, title: "Verbal Consent Obtained",
    why: "The patient has agreed to this session." },
];

const BWS_PRESETS = [
  { pct: 0, label: "Full Weight", note: "No offloading" },
  { pct: 20, label: "Light Support", note: "Early mobilisation" },
  { pct: 40, label: "Moderate", note: "Partial weight bearing" },
  { pct: 50, label: "Standard", note: "Half body weight" },
  { pct: 70, label: "High Support", note: "Significant unloading" },
  { pct: 80, label: "Max Unload", note: "Minimal loading" },
];

export interface WizardResult {
  patient: Patient;
  bwsPercent: number;
  heightMm: number | null;
}

/** The balloon sits at the patient's groin — about 0.47 of standing height. */
export function groinHeightMm(heightCm: number): number {
  return Math.round((heightCm * 10 * 0.47) / 10) * 10;
}

export function Wizard({ snapshot, staff, patient, onCancel, onStart }: {
  snapshot: Snapshot;
  staff: Staff;
  patient: Patient | null;
  onCancel: () => void;
  onStart: (result: WizardResult) => void;
}) {
  const [step, setStep] = useState(1);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const [form, setForm] = useState({
    name: patient?.name ?? "",
    age: patient?.age ? String(patient.age) : "",
    height_cm: patient?.height_cm ? String(patient.height_cm) : "",
    weight_kg: patient?.weight_kg ? String(patient.weight_kg) : "",
    diagnosis: patient?.diagnosis ?? "",
  });
  const [saved, setSaved] = useState<Patient | null>(patient);
  const [ticked, setTicked] = useState<Set<string>>(new Set());
  const [bws, setBws] = useState(0);

  const heightCm = Number(form.height_cm) || 0;
  const targetMm = heightCm ? groinHeightMm(heightCm) : null;
  const criticalDone = CHECKS.filter((c) => c.critical).every((c) => ticked.has(c.id));
  const allDone = ticked.size === CHECKS.length;

  const savePatient = async () => {
    setError(null);
    setBusy(true);
    try {
      const body = {
        name: form.name.trim(),
        age: form.age ? Number(form.age) : null,
        height_cm: form.height_cm ? Number(form.height_cm) : null,
        weight_kg: form.weight_kg ? Number(form.weight_kg) : null,
        diagnosis: form.diagnosis,
        therapist_id: staff.id,
      };
      const result = saved
        ? await postJson<Patient>(`/api/patients/${saved.id}`, body, "PATCH")
        : await postJson<Patient>("/api/patients", body);
      setSaved(result);
      setStep(2);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const head = (title: string, sub: string) => (
    <div className="prod-wizard-head">
      <div style={{ minWidth: 240 }}>
        <h2>{title}</h2>
        <p>{sub}</p>
      </div>
      <Steps current={step} />
      <button className="prod-btn ghost" style={{ marginLeft: "auto" }} onClick={onCancel}>Cancel</button>
    </div>
  );

  // ---- 1. who ------------------------------------------------------------

  if (step === 1) {
    return (
      <>
        {head("Patient Information", saved ? `Editing ${saved.id}` : "New patient record")}
        <div className="prod-wizard-body prod-two">
          <div style={{ display: "grid", gap: 16, alignContent: "start" }}>
            <label className="prod-field">
              <span>Full name</span>
              <input className="prod-input" value={form.name} maxLength={120}
                onChange={(e) => setForm({ ...form, name: e.target.value })} />
            </label>
            <div className="prod-grid-2">
              <TapNumber label="Age (years)" value={form.age} allowDecimal={false}
                onChange={(v) => setForm({ ...form, age: v })} />
              <TapNumber label="Height (cm)" value={form.height_cm}
                onChange={(v) => setForm({ ...form, height_cm: v })} />
            </div>
            <div className="prod-grid-2">
              <TapNumber label="Weight (kg)" value={form.weight_kg}
                onChange={(v) => setForm({ ...form, weight_kg: v })} />
              <label className="prod-field">
                <span>Patient ID</span>
                <div className="prod-input tap" style={{ opacity: .7 }}>
                  {saved?.id ?? "Assigned on save"}
                </div>
              </label>
            </div>
            <p className="muted" style={{ fontSize: 12.5, margin: 0 }}>
              Height sets where the balloon sits{targetMm ? ` — ${targetMm} mm for this patient` : ""}.
              Weight is the reference the offloading works from, so correct it if it has changed.
            </p>
          </div>

          <div style={{ display: "grid", gap: 22, alignContent: "start" }}>
            <div>
              <div className="prod-eyebrow">Diagnosis / indication</div>
              <div className="prod-chips">
                {DIAGNOSES.map((d) => (
                  <button key={d} className={`prod-chip${form.diagnosis === d ? " on" : ""}`}
                    onClick={() => setForm({ ...form, diagnosis: form.diagnosis === d ? "" : d })}>
                    {d}
                  </button>
                ))}
              </div>
            </div>
            <div>
              <div className="prod-eyebrow">Therapist</div>
              <div className="prod-chips"><span className="prod-chip on">{staff.name}</span></div>
            </div>
          </div>
        </div>
        {error && <div className="prod-error" style={{ margin: "0 24px" }} role="alert">{error}</div>}
        <div className="prod-wizard-foot">
          <div className="grow" />
          <button className="prod-btn primary big" disabled={!form.name.trim() || busy}
            onClick={savePatient}>
            {busy ? "Saving…" : "Continue to safety check →"}
          </button>
        </div>
      </>
    );
  }

  // ---- 2. safety ---------------------------------------------------------

  if (step === 2) {
    return (
      <>
        {head("Safety Checklist", "Every critical item must be confirmed before proceeding")}
        <div className="prod-wizard-body">
          <div style={{ display: "flex", alignItems: "center", gap: 16, marginBottom: 14 }}>
            <span className="muted">{ticked.size} of {CHECKS.length} confirmed</span>
            <div className="prod-progress" style={{ flex: 1 }}>
              <span style={{ width: `${(ticked.size / CHECKS.length) * 100}%` }} />
            </div>
            {criticalDone && <span style={{ color: "var(--accent)", fontSize: 13 }}>Ready to continue</span>}
          </div>
          {CHECKS.map((c) => {
            const on = ticked.has(c.id);
            return (
              <button key={c.id} className={`prod-check${on ? " on" : ""}`}
                onClick={() => setTicked((prev) => {
                  const next = new Set(prev);
                  if (!next.delete(c.id)) next.add(c.id);
                  return next;
                })}>
                <div className="box">{on ? "✓" : ""}</div>
                <div>
                  <div className="title">
                    {c.title}
                    {c.critical && <span className="prod-critical">CRITICAL</span>}
                  </div>
                  <div className="why">{c.why}</div>
                </div>
              </button>
            );
          })}
        </div>
        <div className="prod-wizard-foot">
          <button className="prod-btn" onClick={() => setStep(1)}>← Back</button>
          <div className="grow" />
          <button className="prod-btn primary big" disabled={!criticalDone} onClick={() => setStep(3)}>
            {criticalDone
              ? (allDone ? "Proceed to weight →" : "Proceed to weight (non-critical items unchecked) →")
              : "Confirm the critical items first"}
          </button>
        </div>
      </>
    );
  }

  // ---- 3. weight ---------------------------------------------------------

  if (step === 3) {
    const weight = snapshot.weight;
    return (
      <>
        {head("Weight Measurement", "Stand still on the deck")}
        <div className="prod-wizard-body" style={{ textAlign: "center" }}>
          <div className="prod-card" style={{ maxWidth: 540, margin: "20px auto" }}>
            <div className="prod-eyebrow">Measured on the deck</div>
            <div className="mono" style={{ fontSize: 68, fontWeight: 800 }}>
              {weight ? fmtNum(weight.average_kg, 1) : "—"}
              <span style={{ fontSize: 22, color: "var(--muted)" }}> kg</span>
            </div>
            <div className="muted">
              {!weight
                ? snapshot.calibration.status === "missing"
                  ? "No coefficients selected, so the deck cannot weigh anyone."
                  : "Waiting for the board…"
                : weight.stable ? "Stable" : "Settling…"}
            </div>
            {weight && (
              <button className="prod-btn" style={{ marginTop: 16 }}
                onClick={() => setForm({ ...form, weight_kg: weight.average_kg.toFixed(1) })}>
                Use {fmtNum(weight.average_kg, 1)} kg as the record weight
              </button>
            )}
          </div>
          <p className="muted">Recorded weight: {form.weight_kg || "—"} kg</p>
        </div>
        <div className="prod-wizard-foot">
          <button className="prod-btn" onClick={() => setStep(2)}>← Back</button>
          <div className="grow" />
          <button className="prod-btn primary big" onClick={() => setStep(4)}>Continue to balloon →</button>
        </div>
      </>
    );
  }

  // ---- 4. balloon height -------------------------------------------------

  if (step === 4) {
    const h = snapshot.height;
    return (
      <>
        {head("Balloon Height", "Positioned from the patient's height")}
        <div className="prod-wizard-body prod-two">
          <div className="prod-card">
            <div className="prod-eyebrow">Target</div>
            <div className="mono" style={{ fontSize: 52, fontWeight: 800 }}>
              {targetMm ?? "—"}<span style={{ fontSize: 20, color: "var(--muted)" }}> mm</span>
            </div>
            <p className="muted">
              {heightCm
                ? `Groin height for a ${heightCm} cm patient. The console computes this rather than
                   asking for it, so it cannot be mistyped.`
                : "Enter the patient's height on step 1 and this is computed for you."}
            </p>
          </div>
          <div className="prod-card">
            <div className="prod-eyebrow">Actuator</div>
            <dl className="prod-dl">
              <div><dt>State</dt><dd>{!h.available ? "Not fitted" : h.homed ? (h.moving ? "Moving" : "Ready") : "Not homed"}</dd></div>
              <div><dt>Set to</dt><dd>{h.target_mm === null ? "—" : `${h.target_mm} mm`}</dd></div>
              <div><dt>Travel</dt><dd>{h.min_mm}–{h.max_mm} mm</dd></div>
            </dl>
            <div style={{ display: "flex", gap: 10, marginTop: 16 }}>
              <button className="prod-btn" disabled={!h.available || h.moving}
                onClick={() => postJson("/api/height/home").catch((e) => setError(String(e)))}>
                Home
              </button>
              <button className="prod-btn primary" disabled={!h.can_move || !targetMm}
                onClick={() => postJson("/api/height/move", { mm: targetMm }).catch((e) => setError(String(e)))}>
                Move to {targetMm ?? "—"} mm
              </button>
            </div>
            {!h.homed && h.available && (
              <p className="muted" style={{ fontSize: 12.5 }}>
                The deck must find its end stops before an absolute height means anything.
                Nobody should be on it while it homes.
              </p>
            )}
          </div>
        </div>
        {error && <div className="prod-error" style={{ margin: "0 24px" }}>{error}</div>}
        <div className="prod-wizard-foot">
          <button className="prod-btn" onClick={() => setStep(3)}>← Back</button>
          <div className="grow" />
          <button className="prod-btn primary big" onClick={() => setStep(5)}>Continue to offloading →</button>
        </div>
      </>
    );
  }

  // ---- 5. offload (mockup) ----------------------------------------------

  if (step === 5) {
    const bodyWeight = Number(form.weight_kg) || 0;
    return (
      <>
        {head("Body Weight Support", "How much of the patient's weight the balloon carries")}
        <div className="prod-wizard-body">
          <div className="prod-error" style={{ background: "rgba(245,176,65,.08)", borderColor: "rgba(245,176,65,.4)", color: "var(--warn)" }}>
            The air pump, pressure sensor and balloon are still prototype hardware. This screen
            records the setting for the session; nothing is inflated and no weight is taken off
            the patient.
          </div>
          <div className="prod-chips" style={{ gap: 14, marginTop: 20 }}>
            {BWS_PRESETS.map((p) => (
              <button key={p.pct} className={`prod-card${bws === p.pct ? "" : ""}`}
                style={{
                  width: 200, textAlign: "left", cursor: "pointer",
                  borderColor: bws === p.pct ? "var(--accent)" : undefined,
                }}
                onClick={() => setBws(p.pct)}>
                <div className="mono" style={{ fontSize: 30, fontWeight: 800, color: bws === p.pct ? "var(--accent)" : undefined }}>
                  {p.pct}%
                </div>
                <strong>{p.label}</strong>
                <div className="muted" style={{ fontSize: 12.5 }}>{p.note}</div>
              </button>
            ))}
          </div>
          {bodyWeight > 0 && (
            <p className="muted" style={{ marginTop: 18 }}>
              At {bws}% support a {bodyWeight} kg patient would carry{" "}
              <strong style={{ color: "var(--fg)" }}>{fmtNum(bodyWeight * (1 - bws / 100), 1)} kg</strong>.
            </p>
          )}
        </div>
        <div className="prod-wizard-foot">
          <button className="prod-btn" onClick={() => setStep(4)}>← Back</button>
          <div className="grow" />
          <button className="prod-btn primary big" onClick={() => setStep(6)}>Continue to verify →</button>
        </div>
      </>
    );
  }

  // ---- 6. verify and start ----------------------------------------------

  const ready = snapshot.calibration.status !== "missing";
  return (
    <>
      {head("Verify and Start", "Last look before the belt moves")}
      <div className="prod-wizard-body prod-two">
        <div className="prod-card">
          <div className="prod-eyebrow">Patient</div>
          <dl className="prod-dl">
            <div><dt>Name</dt><dd>{form.name}</dd></div>
            <div><dt>ID</dt><dd className="mono">{saved?.id ?? "—"}</dd></div>
            <div><dt>Age</dt><dd>{form.age || "—"}</dd></div>
            <div><dt>Height</dt><dd>{form.height_cm ? `${form.height_cm} cm` : "—"}</dd></div>
            <div><dt>Weight</dt><dd>{form.weight_kg ? `${form.weight_kg} kg` : "—"}</dd></div>
            <div><dt>Diagnosis</dt><dd>{form.diagnosis || "—"}</dd></div>
            <div><dt>Therapist</dt><dd>{staff.name}</dd></div>
          </dl>
        </div>
        <div className="prod-card">
          <div className="prod-eyebrow">Machine</div>
          <dl className="prod-dl">
            <div><dt>Safety checks</dt><dd>{ticked.size} of {CHECKS.length} confirmed</dd></div>
            <div><dt>Balloon height</dt><dd>{targetMm ? `${targetMm} mm` : "—"}</dd></div>
            <div><dt>Offloading</dt><dd>{bws}% (not applied)</dd></div>
            <div><dt>Load cells</dt><dd>{snapshot.link.state}</dd></div>
            <div><dt>Treadmill</dt><dd>{snapshot.treadmill.connected ? "connected" : "not connected"}</dd></div>
            <div><dt>Coefficients</dt><dd>{snapshot.calibration.status === "missing" ? "not selected" : "in use"}</dd></div>
          </dl>
          {!ready && (
            <div className="prod-error" style={{ marginTop: 14 }}>
              No coefficients are selected, so nothing can be weighed or measured. A technician
              chooses them in the service console.
            </div>
          )}
        </div>
      </div>
      {error && <div className="prod-error" style={{ margin: "0 24px" }} role="alert">{error}</div>}
      <div className="prod-wizard-foot">
        <button className="prod-btn" onClick={() => setStep(5)}>← Back</button>
        <div className="grow" />
        <button className="prod-btn primary big" disabled={!saved || !ready || busy}
          onClick={() => {
            if (!saved) return;
            onStart({ patient: saved, bwsPercent: bws, heightMm: targetMm });
          }}>
          Start session →
        </button>
      </div>
    </>
  );
}
