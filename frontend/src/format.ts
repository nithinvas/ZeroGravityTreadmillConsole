export function fmtInt(value: number | null | undefined): string {
  return value === null || value === undefined ? "—" : Math.round(value).toLocaleString("en-US");
}

export function fmtNum(value: number | null | undefined, digits = 1): string {
  return value === null || value === undefined
    ? "—"
    : value.toLocaleString("en-US", { minimumFractionDigits: digits, maximumFractionDigits: digits });
}

export function fmtDuration(seconds: number | null | undefined): string {
  if (seconds === null || seconds === undefined) return "—";
  const s = Math.floor(seconds);
  const m = Math.floor(s / 60);
  return m > 0 ? `${m} min ${String(s % 60).padStart(2, "0")} s` : `${s} s`;
}
