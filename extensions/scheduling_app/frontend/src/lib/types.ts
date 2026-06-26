// Shapes returned by / sent to the plugin's data endpoints (handlers/scheduling_web_app.py
// and booking.py).

export interface Provider {
  id: string;
  name: string;
}

export interface Location {
  id: string;
  name: string;
}

export interface VisitType {
  id: string;
  name: string;
  isTelehealth: boolean;
  isDefault: boolean;
  allowCustomTitle: boolean;
  isPatientRequired: boolean;
}

export interface ReasonForVisit {
  // External id of the coding — sent as the structured RFV command's coding.
  id: string;
  code: string;
  display: string;
  durations: number[];
}

export interface LabelOption {
  id: string;
  name: string;
  color: string;
}

export interface ReferenceData {
  providers: Provider[];
  locations: Location[];
  visitTypes: VisitType[];
  reasonsForVisit: ReasonForVisit[];
  defaultDurations: number[];
  labels: LabelOption[];
  // Mirrors the instance's STRUCTURED_REASON_FOR_VISIT_ENABLED flag: when true the
  // UI shows the coded reason dropdown, when false a free-text reason field.
  structuredReasonForVisit: boolean;
}

export interface Patient {
  id: string;
  name: string;
  // Demographics shown on the selected-patient card (mirrors the EHR header):
  // birth date "YYYY-MM-DD", sex-at-birth code ("F"/"M"/…), and primary phone.
  birthDate?: string | null;
  sex?: string | null;
  phone?: string | null;
}

export interface AppointmentPrefill {
  id: string;
  providerId: string | null;
  locationId: string | null;
  visitTypeId: string | null;
  startTime: string | null;
  durationMinutes: number | null;
  patientId: string | null;
  // Reschedule fidelity: the appointment's existing labels (read-only on the
  // form — home-app carries them over) and its current reason for visit.
  labels?: string[];
  rfvCode?: string | null;
  rfvText?: string | null;
  comment?: string | null;
}

export type Category = "appointment" | "schedule_event";
export type Mode = "schedule" | "reschedule";
export type Grouping = "concurrent" | "sequential";
export type Frequency = "daily" | "weekly" | "monthly";

// Recurrence rule sent to /book (appointments only). `count` is the TOTAL
// occurrences including the first; `until` is an inclusive end date — exactly one.
export interface Recurrence {
  frequency: Frequency;
  interval: number;
  count?: number;
  until?: string;
}

// Recurrence form state in the modal (converted to `Recurrence` at submit).
export interface RecurrenceForm {
  enabled: boolean;
  frequency: Frequency;
  interval: number;
  end: "count" | "until";
  count: number;
  until: string;
}

// Per-visit form state.
export interface Visit {
  providers: string[];
  locationId: string;
  visitTypeId: string;
  durationMinutes: string;
  rfvCode: string;
  rfvText: string;
  comment: string;
  labels: string[];
  description: string;
  meetingLink: string;
  time: string;
}

// Launch context parsed from the modal URL.
export interface LaunchContext {
  mode: Mode;
  origin: string | null;
  patientId: string | null;
  providerId: string | null;
  locationId: string | null;
  appointmentId: string | null;
  start: string | null;
  duration: string | null;
}

// Payload POSTed to /book (mirrors booking.build_booking_effects).
export interface BookingPayload {
  mode: Mode;
  category: Category;
  patient_id: string | null;
  appointment_id: string | null;
  grouping: Grouping;
  visits: {
    providers: string[];
    location_id: string;
    visit_type_id: string;
    duration_minutes: number;
    start_time: string;
    labels: string[];
    description: string;
    meeting_link?: string;
    // Reason for visit (appointments only): free text, or a coded id +
    // optional comment when the instance uses structured RFV.
    reason_for_visit?: string;
    reason_for_visit_coding?: string;
    reason_for_visit_comment?: string;
  }[];
  // Optional recurrence (appointments only): each booked appointment becomes a
  // series parent that the APPOINTMENT_CREATED handler expands.
  recurrence?: Recurrence;
}
