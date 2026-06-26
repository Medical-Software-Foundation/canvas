import type { Grouping, Visit } from "./types";

/** Zero-pad a number to two digits. */
export function pad2(value: number): string {
  return String(value).padStart(2, "0");
}

/** Today's local date as "YYYY-MM-DD". */
export function todayStr(): string {
  const now = new Date();
  return `${now.getFullYear()}-${pad2(now.getMonth() + 1)}-${pad2(now.getDate())}`;
}

/**
 * Split an incoming `start` value into a local date + time.
 *
 * A timezone-aware instant (e.g. "2026-06-08T23:00:00.000Z") must be read in
 * local time, not string-split: the host passes the selected day as a local
 * Date that JSON.stringify serialized to UTC, so naively taking the UTC date
 * lands on the previous/next day. Date-only or naive values are already in the
 * intended local frame, so split them as-is.
 */
export function splitISO(iso: string): { date: string; time: string } {
  const hasTimezone = /[zZ]|[+-]\d\d:?\d\d$/.test(iso);
  const parsed = new Date(iso);
  if (hasTimezone && !Number.isNaN(parsed.getTime())) {
    const date = `${parsed.getFullYear()}-${pad2(parsed.getMonth() + 1)}-${pad2(parsed.getDate())}`;
    return { date, time: `${pad2(parsed.getHours())}:${pad2(parsed.getMinutes())}` };
  }
  const [date, rest = ""] = iso.split("T");
  return { date: date || todayStr(), time: rest.slice(0, 5) || "09:00" };
}

const MONTHS = [
  "January", "February", "March", "April", "May", "June",
  "July", "August", "September", "October", "November", "December",
];

/** Format a "YYYY-MM-DD" date as "June 15, 2026". */
export function formatLongDate(date: string): string {
  const [year, month, day] = date.split("-").map(Number);
  if (!year || !month || !day) return date;
  return `${MONTHS[month - 1]} ${day}, ${year}`;
}

/** Format a "HH:MM" 24h time as a 12h clock time, e.g. "6:00 PM". */
export function formatClockTime(time: string): string {
  const [hours, minutes] = time.split(":").map(Number);
  if (Number.isNaN(hours) || Number.isNaN(minutes)) return time;
  const period = hours < 12 ? "AM" : "PM";
  const hour12 = hours % 12 === 0 ? 12 : hours % 12;
  return `${hour12}:${pad2(minutes)} ${period}`;
}

/** Format a "YYYY-MM-DD" birth date as "M/D/YYYY" (no leading zeros), like the EHR. */
export function formatBirthDate(iso: string): string {
  const [year, month, day] = iso.split("-").map(Number);
  if (!year || !month || !day) return iso;
  return `${month}/${day}/${year}`;
}

/** Whole-years age for a "YYYY-MM-DD" birth date as of `now` (defaults to today). */
export function ageFromBirthDate(iso: string, now: Date = new Date()): number {
  const [year, month, day] = iso.split("-").map(Number);
  let age = now.getFullYear() - year;
  const nowMonth = now.getMonth() + 1;
  if (nowMonth < month || (nowMonth === month && now.getDate() < day)) {
    age -= 1; // birthday hasn't happened yet this year
  }
  return age;
}

/** Shift a "YYYY-MM-DD" string by whole days without crossing timezones. */
export function shiftDate(date: string, days: number): string {
  const [year, month, day] = date.split("-").map(Number);
  const shifted = new Date(year, month - 1, day + days);
  return `${shifted.getFullYear()}-${pad2(shifted.getMonth() + 1)}-${pad2(shifted.getDate())}`;
}

/** Add minutes to a "HH:MM" string (clamped within the day). */
export function addMinutes(time: string, minutes: number): string {
  const [hours, mins] = time.split(":").map(Number);
  const total = Math.min(hours * 60 + mins + minutes, 23 * 60 + 59);
  return `${pad2(Math.floor(total / 60))}:${pad2(total % 60)}`;
}

/** Compute each visit's effective start time given the grouping. */
export function effectiveTimes(visits: Visit[], grouping: Grouping): string[] {
  if (grouping !== "sequential") {
    return visits.map((visit) => visit.time);
  }
  const times: string[] = [];
  let cursor = visits[0]?.time ?? "";
  visits.forEach((visit, index) => {
    if (index === 0) {
      cursor = visit.time;
    }
    times.push(cursor);
    cursor = addMinutes(cursor, Number(visit.durationMinutes) || 0);
  });
  return times;
}
