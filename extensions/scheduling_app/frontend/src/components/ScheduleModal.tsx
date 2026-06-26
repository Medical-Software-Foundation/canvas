import { useEffect, useMemo, useRef, useState } from "react";

import { useMutation, useQuery } from "@tanstack/react-query";
import { Plus } from "lucide-react";

import { PatientField } from "@/components/PatientField";
import {
  PreviousAppointmentSummary,
  previousScheduleParts,
} from "@/components/PreviousAppointmentSummary";
import { VisitCard } from "@/components/VisitCard";
import { WhenPane } from "@/components/WhenPane";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { RadioGroup, RadioGroupItem } from "@/components/ui/radio-group";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { book, fetchAppointment, fetchReference, lookupPatient } from "@/lib/api";
import { parseContext } from "@/lib/context";
import { splitISO, todayStr } from "@/lib/datetime";
import { closeModal } from "@/lib/iframe";
import {
  buildBookingPayload,
  defaultRecurrenceForm,
  defaultVisit,
  toRecurrencePayload,
  validateForm,
  withDefaults,
} from "@/lib/scheduling";
import type { Category, Grouping, Patient, RecurrenceForm, Visit } from "@/lib/types";

// The built-in modal caps a single booking at 5 visits; mirror that.
const MAX_VISITS = 5;

export function ScheduleModal() {
  const ctx = useMemo(parseContext, []);
  const isReschedule = ctx.mode === "reschedule";

  const [category, setCategory] = useState<Category>("appointment");
  const [patient, setPatient] = useState<Patient | null>(null);
  const [lookupId, setLookupId] = useState<string | null>(ctx.patientId);
  const [grouping, setGrouping] = useState<Grouping>("concurrent");
  const [recurrence, setRecurrence] = useState<RecurrenceForm>(defaultRecurrenceForm);
  const patchRecurrence = (patch: Partial<RecurrenceForm>) =>
    setRecurrence((prev) => ({ ...prev, ...patch }));
  const [date, setDate] = useState<string>(() =>
    ctx.start ? splitISO(ctx.start).date : todayStr(),
  );
  const [visits, setVisits] = useState<Visit[]>(() => {
    const visit = defaultVisit();
    if (ctx.providerId) visit.providers = [ctx.providerId];
    if (ctx.locationId) visit.locationId = ctx.locationId;
    if (ctx.duration) visit.durationMinutes = ctx.duration;
    if (ctx.start) {
      // A day-view launch carries the day at local midnight; treat that as
      // "no specific time" and keep the sensible default rather than 00:00.
      const time = splitISO(ctx.start).time;
      visit.time = time === "00:00" ? "09:00" : time;
    }
    return [visit];
  });

  const referenceQuery = useQuery({
    queryKey: ["reference", category],
    queryFn: () => fetchReference(category),
  });
  const reference = referenceQuery.data;

  // Look up the context / appointment patient to show their name.
  const patientLookup = useQuery({
    queryKey: ["patient-lookup", lookupId],
    queryFn: () => lookupPatient(lookupId as string),
    enabled: !!lookupId,
  });
  useEffect(() => {
    if (patientLookup.data) setPatient(patientLookup.data);
  }, [patientLookup.data]);

  // Reschedule: prefill the single visit from the existing appointment.
  const appointmentQuery = useQuery({
    queryKey: ["appointment", ctx.appointmentId],
    queryFn: () => fetchAppointment(ctx.appointmentId as string),
    enabled: isReschedule && !!ctx.appointmentId,
  });
  const apptSeeded = useRef(false);
  useEffect(() => {
    const appointment = appointmentQuery.data;
    if (!appointment || apptSeeded.current) return;
    apptSeeded.current = true;
    const when = appointment.startTime ? splitISO(appointment.startTime) : { date, time: "09:00" };
    setDate(when.date);
    setVisits([
      {
        ...defaultVisit(reference),
        providers: appointment.providerId ? [appointment.providerId] : [],
        locationId: appointment.locationId ?? "",
        visitTypeId: appointment.visitTypeId ?? "",
        durationMinutes: appointment.durationMinutes ? String(appointment.durationMinutes) : "",
        time: when.time,
        // Prefill the existing labels (read-only) and reason for visit.
        labels: appointment.labels ?? [],
        rfvCode: appointment.rfvCode ?? "",
        rfvText: appointment.rfvText ?? "",
        comment: appointment.comment ?? "",
      },
    ]);
    if (appointment.patientId) setLookupId(appointment.patientId);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [appointmentQuery.data]);

  // Fill empty defaults once reference data is available.
  const refSeeded = useRef(false);
  useEffect(() => {
    if (!reference || refSeeded.current) return;
    refSeeded.current = true;
    setVisits((prev) => prev.map((visit) => withDefaults(visit, reference)));
  }, [reference]);

  const mutation = useMutation({
    mutationFn: book,
    onSuccess: () => closeModal(),
  });

  // Collapsed state per visit index (parallel to `visits`). Adding a visit
  // collapses the existing ones to a summary, mirroring the built-in modal.
  const [collapsed, setCollapsed] = useState<boolean[]>([]);

  const patchVisit = (index: number, patch: Partial<Visit>) => {
    setVisits((prev) => prev.map((visit, i) => (i === index ? { ...visit, ...patch } : visit)));
  };
  const toggleCollapse = (index: number) =>
    setCollapsed((prev) => {
      const next = [...prev];
      next[index] = !next[index];
      return next;
    });
  const addVisit = () => {
    if (visits.length >= MAX_VISITS) return;
    setCollapsed(visits.map(() => true)); // collapse existing; the new visit stays expanded
    setVisits((prev) => [...prev, defaultVisit(reference)]);
  };
  const removeVisit = (index: number) => {
    setVisits((prev) => (prev.length > 1 ? prev.filter((_, i) => i !== index) : prev));
    setCollapsed((prev) => prev.filter((_, i) => i !== index));
  };

  const switchCategory = (next: Category) => {
    if (next === category) return;
    setCategory(next);
    setGrouping("concurrent");
    refSeeded.current = false;
    // Carry the selected providers + location across the tab switch (like the
    // built-in modal); category-specific fields (visit type, RFV, labels, …)
    // reset and re-seed from the new category's reference data.
    setVisits((prev) => {
      const carried = prev[0];
      return [
        {
          ...defaultVisit(),
          providers: carried?.providers ?? [],
          locationId: carried?.locationId ?? "",
        },
      ];
    });
    setCollapsed([]);
  };

  const isAppointment = category === "appointment";
  const previousParts =
    isReschedule && appointmentQuery.data ? previousScheduleParts(appointmentQuery.data) : null;

  const validationError = useMemo<string | null>(
    () => validateForm(reference, category, visits, patient),
    [reference, category, visits, patient],
  );

  const firstStart = visits[0] ? new Date(`${date}T${visits[0].time}:00`) : null;
  const isPast = firstStart ? firstStart.getTime() < Date.now() : false;

  const submit = () => {
    if (validationError) return;
    mutation.mutate(
      buildBookingPayload({
        mode: ctx.mode,
        category,
        patient,
        appointmentId: ctx.appointmentId,
        grouping,
        date,
        visits,
        recurrence: toRecurrencePayload(recurrence),
      }),
    );
  };

  return (
    <div data-test="schedule-modal" className="mx-auto flex max-w-3xl flex-col gap-5 p-6 text-foreground">
      <header className="space-y-3">
        <h1 className="text-lg font-semibold">
          {isReschedule ? "Reschedule appointment" : "Schedule"}
        </h1>
        <Tabs value={category} onValueChange={(value) => switchCategory(value as Category)}>
          <TabsList>
            <TabsTrigger data-test="tab-appointment" value="appointment">
              Appointment
            </TabsTrigger>
            <TabsTrigger
              data-test="tab-schedule-event"
              value="schedule_event"
              disabled={isReschedule}
            >
              Other event
            </TabsTrigger>
          </TabsList>
        </Tabs>
      </header>

      {referenceQuery.isLoading || !reference ? (
        <p className="py-10 text-center text-sm text-muted-foreground">Loading…</p>
      ) : referenceQuery.isError ? (
        <p className="py-10 text-center text-sm text-destructive">Failed to load scheduling data.</p>
      ) : (
        <div className="grid grid-cols-1 gap-6 md:grid-cols-[1fr_280px]">
          <div className="space-y-5">
            <div className="space-y-2">
              <Label>{isAppointment ? "Patient" : "Patient (optional)"}</Label>
              <PatientField patient={patient} onSelect={setPatient} readOnly={isReschedule} />
              {isReschedule && appointmentQuery.data && (
                <PreviousAppointmentSummary appointment={appointmentQuery.data} reference={reference} />
              )}
            </div>

            {visits.map((visit, index) => (
              <VisitCard
                key={index}
                visit={visit}
                index={index}
                total={visits.length}
                category={category}
                reference={reference}
                collapsed={collapsed[index] ?? false}
                onToggleCollapse={() => toggleCollapse(index)}
                onChange={(patch) => patchVisit(index, patch)}
                onRemove={visits.length > 1 ? () => removeVisit(index) : undefined}
              />
            ))}

            {!isReschedule && (
              <div className="space-y-4">
                <Button
                  data-test="add-visit-button"
                  variant="outline"
                  onClick={addVisit}
                  disabled={visits.length >= MAX_VISITS}
                  className="gap-2"
                >
                  <Plus className="h-4 w-4" />
                  Add visit
                </Button>

                {visits.length > 1 && (
                  <div className="space-y-2">
                    <Label>Scheduling</Label>
                    <RadioGroup
                      value={grouping}
                      onValueChange={(value) => setGrouping(value as Grouping)}
                    >
                      <label className="flex cursor-pointer items-center gap-2 text-sm">
                        <RadioGroupItem data-test="grouping-concurrent" value="concurrent" />
                        Concurrent (same time)
                      </label>
                      <label className="flex cursor-pointer items-center gap-2 text-sm">
                        <RadioGroupItem data-test="grouping-sequential" value="sequential" />
                        Sequential (back to back)
                      </label>
                    </RadioGroup>
                  </div>
                )}
              </div>
            )}
          </div>

          <aside className="md:border-l md:border-border md:pl-6">
            <WhenPane
              date={date}
              onDateChange={setDate}
              visits={visits}
              grouping={grouping}
              onVisitTimeChange={(index, time) => patchVisit(index, { time })}
              recurrence={isAppointment && !isReschedule ? recurrence : undefined}
              onRecurrenceChange={isAppointment && !isReschedule ? patchRecurrence : undefined}
            />
            {previousParts && (
              <p data-test="reschedule-previous-time" className="mt-3 text-xs text-muted-foreground">
                Previously scheduled for {previousParts.longDate} at {previousParts.start} –{" "}
                {previousParts.end}
              </p>
            )}
            {isPast && (
              <p data-test="past-time-warning" className="mt-3 text-xs text-destructive">
                This time is in the past.
              </p>
            )}
          </aside>
        </div>
      )}

      <footer className="flex items-center justify-end gap-3 border-t border-border pt-4">
        {mutation.isError && (
          <span className="mr-auto text-sm text-destructive">
            {(mutation.error as Error).message}
          </span>
        )}
        {validationError && !mutation.isError && reference && (
          <span data-test="validation-message" className="mr-auto text-sm text-muted-foreground">
            {validationError}
          </span>
        )}
        <Button
          data-test="modal-cancel-button"
          variant="outline"
          onClick={closeModal}
          disabled={mutation.isPending}
        >
          Cancel
        </Button>
        {/* Wrap in a span so the tooltip shows on hover even while the button is
            disabled: a disabled button has pointer-events:none, so the hover
            registers on the span. `title` is the specific validation reason
            (e.g. "Enter a reason for visit."), so the provider knows what's missing. */}
        <span title={validationError ?? undefined} className="inline-flex">
          <Button
            data-test="modal-submit-button"
            onClick={submit}
            disabled={!!validationError || mutation.isPending}
          >
            {mutation.isPending ? "Saving…" : isReschedule ? "Reschedule" : "Book"}
          </Button>
        </span>
      </footer>
    </div>
  );
}
