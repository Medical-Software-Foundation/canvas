import { API_BASE } from "./context";
import type { AppointmentPrefill, BookingPayload, Category, Patient, ReferenceData } from "./types";

async function getJSON<T>(path: string): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, { headers: { Accept: "application/json" } });
  if (!res.ok) throw new Error(`GET ${path} failed: ${res.status}`);
  return res.json() as Promise<T>;
}

export function fetchReference(category: Category): Promise<ReferenceData> {
  return getJSON<ReferenceData>(`/reference?category=${category}`);
}

export function searchPatients(query: string): Promise<Patient[]> {
  return getJSON<{ patients: Patient[] }>(`/patients?q=${encodeURIComponent(query)}`).then(
    (d) => d.patients,
  );
}

export function lookupPatient(id: string): Promise<Patient | null> {
  return getJSON<{ patients: Patient[] }>(`/patients?id=${encodeURIComponent(id)}`).then(
    (d) => d.patients[0] ?? null,
  );
}

export function fetchAppointment(id: string): Promise<AppointmentPrefill> {
  return getJSON<AppointmentPrefill>(`/appointment?id=${encodeURIComponent(id)}`);
}

export async function book(payload: BookingPayload): Promise<void> {
  const res = await fetch(`${API_BASE}/book`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  const body = await res.json().catch(() => ({}));
  if (!res.ok || !body.booked) {
    throw new Error(body.error || "Booking failed.");
  }
}
