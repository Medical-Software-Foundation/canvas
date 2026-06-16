import { ClipboardList } from "lucide-react";

import { addMinutes, formatClockTime, formatLongDate, splitISO } from "@/lib/datetime";
import type { AppointmentPrefill, ReferenceData } from "@/lib/types";

/** The original appointment's date and time range, formatted for display. */
export function previousScheduleParts(
  appointment: AppointmentPrefill,
): { longDate: string; start: string; end: string } | null {
  if (!appointment.startTime) return null;
  const { date, time } = splitISO(appointment.startTime);
  return {
    longDate: formatLongDate(date),
    start: formatClockTime(time),
    end: formatClockTime(addMinutes(time, appointment.durationMinutes ?? 0)),
  };
}

interface Props {
  appointment: AppointmentPrefill;
  reference: ReferenceData;
}

/**
 * Read-only summary of the appointment being rescheduled, shown below the patient
 * card — mirrors the built-in modal's "With <provider> at <location> on <when>".
 */
export function PreviousAppointmentSummary({ appointment, reference }: Props) {
  const providerName = reference.providers.find((p) => p.id === appointment.providerId)?.name;
  const locationName = reference.locations.find((l) => l.id === appointment.locationId)?.name;
  const visitTypeName = reference.visitTypes.find((t) => t.id === appointment.visitTypeId)?.name;
  const codedReason = reference.reasonsForVisit.find((r) => r.id === appointment.rfvCode)?.display;
  const title = appointment.rfvText || codedReason || visitTypeName || "Appointment";

  const parts = previousScheduleParts(appointment);
  const context = [
    providerName ? `With ${providerName}` : null,
    locationName ? `at ${locationName}` : null,
    parts ? `on ${parts.longDate}, ${parts.start} – ${parts.end}` : null,
  ]
    .filter(Boolean)
    .join(" ");

  return (
    <div
      data-test="reschedule-summary"
      className="flex items-start gap-2 rounded-md border-l-2 border-primary bg-muted/40 px-3 py-2"
    >
      <ClipboardList className="mt-0.5 h-4 w-4 shrink-0 text-muted-foreground" />
      <div className="min-w-0">
        <div className="truncate text-sm font-semibold text-foreground">{title}</div>
        {context && <div className="text-xs text-muted-foreground">{context}</div>}
      </div>
    </div>
  );
}
