import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import App from "./App";
import "./styles.css";

// Uncaught UI errors reach the backend log as component "ui", so they show up in
// `treadmill logs` and the journal rather than vanishing inside the kiosk.
function report(message: string) {
  void fetch("/api/client-log", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ level: "error", event: "ui.error", message: message.slice(0, 2000) }),
  }).catch(() => undefined);
}
window.addEventListener("error", (e) => report(`${e.message} at ${e.filename}:${e.lineno}`));
window.addEventListener("unhandledrejection", (e) => report(`Unhandled rejection: ${String(e.reason)}`));

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
