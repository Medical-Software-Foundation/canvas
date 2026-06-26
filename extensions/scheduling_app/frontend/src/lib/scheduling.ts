import type {
  BookingPayload,
  Category,
  Grouping,
  Mode,
  Patient,
  Recurrence,
  RecurrenceForm,
  ReferenceData,
  Visit,
} from "./types";

const FALLBACK_DURATIONS = [15, 20, 30, 45, 60];

/** Default (disabled) recurrence form state. */
export function defaultRecurrenceForm(): RecurrenceForm {
  return { enabled: false, frequency: "weekly", interval: 1, end: "count", count: 4, until: "" };
}

/**
 * Convert the recurrence form to the `/book` rule, or null when it shouldn't
 * recur (disabled, or no valid end condition — a count < 2 means no children).
 */
export function toRecurrencePayload(form: RecurrenceForm): Recurrence | null {
  if (!form.enabled) return null;
  const interval = Math.max(1, Math.floor(form.interval) || 1);
  if (form.end === "until") {
    return form.until ? { frequency: form.frequency, interval, until: form.until } : null;
  }
  const count = Math.floor(form.count);
  return count >= 2 ? { frequency: form.frequency, interval, count } : null;
}

/** A blank visit, pre-filled with sensible defaults from reference data if present. */
export function defaultVisit(reference?: ReferenceData): Visit {
  const defaultType = reference?.visitTypes.find((type) => type.isDefault) ?? reference?.visitTypes[0];
  const durations = reference?.defaultDurations.length
    ? reference.defaultDurations
    : FALLBACK_DURATIONS;
  const duration = durations.includes(30) ? 30 : durations[0];
  return {
    providers: [],
    locationId: reference?.locations.length === 1 ? reference.locations[0].id : "",
    visitTypeId: defaultType?.id ?? "",
    durationMinutes: duration != null ? String(duration) : "",
    rfvCode: "",
    rfvText: "",
    comment: "",
    labels: [],
    description: "",
    meetingLink: "",
    time: "09:00",
  };
}

/** Fill only the still-empty defaultable fields once reference data arrives. */
export function withDefaults(visit: Visit, reference: ReferenceData): Visit {
  const base = defaultVisit(reference);
  return {
    ...visit,
    locationId: visit.locationId || base.locationId,
    visitTypeId: visit.visitTypeId || base.visitTypeId,
    durationMinutes: visit.durationMinutes || base.durationMinutes,
  };
}

/**
 * Validate the form. Returns an error message to show (and block submit), or
 * null when the form is ready to book.
 */
export function validateForm(
  reference: ReferenceData | undefined,
  category: Category,
  visits: Visit[],
  patient: Patient | null,
): string | null {
  if (!reference) return "Loading…";
  const isAppointment = category === "appointment";
  const patientRequired =
    isAppointment ||
    visits.some(
      (visit) => reference.visitTypes.find((t) => t.id === visit.visitTypeId)?.isPatientRequired,
    );
  if (patientRequired && !patient) return "Select a patient.";
  for (const visit of visits) {
    if (!visit.providers.length) return "Each visit needs at least one provider.";
    if (!visit.locationId) return "Select a location.";
    if (!visit.visitTypeId) return "Select a type.";
    if (!visit.durationMinutes) return "Select a duration.";
    if (!visit.time) return "Select a time.";
    // Reason for visit is required on appointments (free-text or coded).
    if (isAppointment && !visit.rfvText && !visit.rfvCode) return "Enter a reason for visit.";
  }
  return null;
}

interface BuildBookingPayloadArgs {
  mode: Mode;
  category: Category;
  patient: Patient | null;
  appointmentId: string | null;
  grouping: Grouping;
  date: string;
  visits: Visit[];
  recurrence?: Recurrence | null;
}

/** Map the form state to the payload POSTed to /book (mirrors booking.py). */
export function buildBookingPayload(args: BuildBookingPayloadArgs): BookingPayload {
  const { mode, category, patient, appointmentId, grouping, date, visits, recurrence } = args;
  const isAppointment = category === "appointment";
  return {
    mode,
    category,
    patient_id: patient?.id ?? null,
    appointment_id: appointmentId ?? null,
    grouping,
    // Recurrence is appointment-only (omitted for schedule events).
    ...(isAppointment && recurrence ? { recurrence } : {}),
    visits: visits.map((visit) => ({
      providers: visit.providers,
      location_id: visit.locationId,
      visit_type_id: visit.visitTypeId,
      duration_minutes: Number(visit.durationMinutes),
      // Send a timezone-aware instant: the form's date+time is a local wall-clock
      // value, so convert it to UTC here. home-app parses start_time with
      // arrow.get(), which assumes UTC for a *naive* string — sending the naive
      // wall-clock stored the wrong instant (off by the viewer's UTC offset).
      start_time: new Date(`${date}T${visit.time}:00`).toISOString(),
      labels: visit.labels,
      description: visit.description,
      ...(visit.meetingLink ? { meeting_link: visit.meetingLink } : {}),
      // Reason for visit is appointment-only; send free text or a coded id +
      // optional comment (empties omitted so booking.py skips the command).
      ...(isAppointment && visit.rfvText ? { reason_for_visit: visit.rfvText } : {}),
      ...(isAppointment && visit.rfvCode ? { reason_for_visit_coding: visit.rfvCode } : {}),
      ...(isAppointment && visit.rfvCode && visit.comment
        ? { reason_for_visit_comment: visit.comment }
        : {}),
    })),
  };
}
