import type { ReferenceData, Visit } from "@/lib/types";

/** A complete, valid visit by default; pass overrides to blank fields out. */
export function makeVisit(overrides: Partial<Visit> = {}): Visit {
  return {
    providers: ["s1"],
    locationId: "l1",
    visitTypeId: "t1",
    durationMinutes: "30",
    rfvCode: "",
    rfvText: "",
    comment: "",
    labels: [],
    description: "",
    meetingLink: "",
    time: "09:00",
    ...overrides,
  };
}

/** Reference data with one default visit type, location, and provider. */
export function makeReference(overrides: Partial<ReferenceData> = {}): ReferenceData {
  return {
    providers: [{ id: "s1", name: "Dr. Ada" }],
    locations: [{ id: "l1", name: "Main Clinic" }],
    visitTypes: [
      {
        id: "t1",
        name: "Office Visit",
        isTelehealth: false,
        isDefault: true,
        allowCustomTitle: false,
        isPatientRequired: false,
      },
    ],
    reasonsForVisit: [],
    defaultDurations: [15, 20, 30, 45, 60],
    labels: [],
    structuredReasonForVisit: false,
    ...overrides,
  };
}
