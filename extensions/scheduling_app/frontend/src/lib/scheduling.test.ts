import { describe, expect, it } from "vitest";

import { makeReference, makeVisit } from "@/test/factories";
import type { Patient } from "@/lib/types";

import { buildBookingPayload, validateForm } from "./scheduling";

// These tests run under TZ=Etc/GMT-1 (UTC+1, no DST) — see vitest.config.ts.

const patient: Patient = { id: "p1", name: "Pat Patient" };

function payloadFor(overrides: Parameters<typeof buildBookingPayload>[0]) {
  return buildBookingPayload(overrides);
}

describe("buildBookingPayload start_time (timezone)", () => {
  it("sends the local wall-clock time as a UTC instant (09:00 @ UTC+1 -> 08:00Z)", () => {
    const payload = payloadFor({
      mode: "schedule",
      category: "appointment",
      patient,
      appointmentId: null,
      grouping: "concurrent",
      date: "2026-06-09",
      visits: [makeVisit({ time: "09:00", rfvText: "cough" })],
    });
    expect(payload.visits[0].start_time).toBe("2026-06-09T08:00:00.000Z");
  });

  it("carries the timezone-aware instant on a reschedule too", () => {
    const payload = payloadFor({
      mode: "reschedule",
      category: "appointment",
      patient,
      appointmentId: "appt-1",
      grouping: "concurrent",
      date: "2026-06-17",
      visits: [makeVisit({ time: "20:00", rfvText: "follow up" })],
    });
    expect(payload.visits[0].start_time).toBe("2026-06-17T19:00:00.000Z");
  });
});

describe("validateForm reason for visit (required on appointments)", () => {
  it("requires a reason for visit on an appointment", () => {
    expect(validateForm(makeReference(), "appointment", [makeVisit()], patient)).toBe(
      "Enter a reason for visit.",
    );
  });

  it("accepts a free-text reason", () => {
    expect(
      validateForm(makeReference(), "appointment", [makeVisit({ rfvText: "cough" })], patient),
    ).toBeNull();
  });

  it("accepts a coded reason", () => {
    expect(
      validateForm(makeReference(), "appointment", [makeVisit({ rfvCode: "rfv-1" })], patient),
    ).toBeNull();
  });

  it("does not require a reason for a schedule event", () => {
    expect(validateForm(makeReference(), "schedule_event", [makeVisit()], null)).toBeNull();
  });
});
