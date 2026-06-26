import type { LaunchContext } from "./types";

// The modal is served at <base>/modal; data endpoints live under <base>.
export const API_BASE = window.location.pathname.replace(/\/modal\/?$/, "");

export function parseContext(search: string = window.location.search): LaunchContext {
  const p = new URLSearchParams(search);
  return {
    mode: p.get("mode") === "reschedule" ? "reschedule" : "schedule",
    origin: p.get("origin"),
    patientId: p.get("patient_id"),
    providerId: p.get("provider_id"),
    locationId: p.get("location_id"),
    appointmentId: p.get("appointment_id"),
    start: p.get("start"),
    duration: p.get("duration"),
  };
}
