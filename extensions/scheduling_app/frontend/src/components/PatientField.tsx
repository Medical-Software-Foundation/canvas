import { useEffect, useRef, useState } from "react";

import { useQuery } from "@tanstack/react-query";
import { User, X } from "lucide-react";

import { Input } from "@/components/ui/input";
import { searchPatients } from "@/lib/api";
import { ageFromBirthDate, formatBirthDate } from "@/lib/datetime";
import type { Patient } from "@/lib/types";

/** "5/18/1971 · 55 · F · (784) 555-0199" — empty parts are dropped. */
function demographics(patient: Patient): string {
  return [
    patient.birthDate ? formatBirthDate(patient.birthDate) : null,
    patient.birthDate ? String(ageFromBirthDate(patient.birthDate)) : null,
    patient.sex || null,
    patient.phone || null,
  ]
    .filter(Boolean)
    .join(" · ");
}

interface PatientFieldProps {
  patient: Patient | null;
  onSelect: (patient: Patient | null) => void;
  // On reschedule the patient is fixed: render the card without the clear (X)
  // affordance and never fall back to the search input.
  readOnly?: boolean;
}

export function PatientField({ patient, onSelect, readOnly = false }: PatientFieldProps) {
  const [query, setQuery] = useState("");
  const [open, setOpen] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);

  // Close the results when clicking away.
  useEffect(() => {
    const onClick = (event: MouseEvent) => {
      if (containerRef.current && !containerRef.current.contains(event.target as Node)) {
        setOpen(false);
      }
    };
    document.addEventListener("mousedown", onClick);
    return () => document.removeEventListener("mousedown", onClick);
  }, []);

  const { data: results = [], isFetching } = useQuery({
    queryKey: ["patients", query],
    queryFn: () => searchPatients(query),
    enabled: open && query.trim().length >= 2,
  });

  if (patient) {
    const meta = demographics(patient);
    return (
      <div
        data-test="patient-selected"
        className="flex items-center gap-3 rounded-md border border-input bg-background px-3 py-2"
      >
        <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-muted text-muted-foreground">
          <User className="h-5 w-5" />
        </div>
        <div className="min-w-0 flex-1">
          <div className="truncate text-sm font-semibold text-foreground">{patient.name}</div>
          {meta && (
            <div data-test="patient-meta" className="truncate text-xs text-muted-foreground">
              {meta}
            </div>
          )}
        </div>
        {!readOnly && (
          <button
            type="button"
            data-test="patient-clear-button"
            onClick={() => {
              onSelect(null);
              setQuery("");
            }}
            className="text-muted-foreground hover:text-foreground"
            aria-label="Clear patient"
          >
            <X className="h-4 w-4" />
          </button>
        )}
      </div>
    );
  }

  return (
    <div ref={containerRef} className="relative">
      <Input
        data-test="patient-search-input"
        placeholder="Search by name…"
        value={query}
        onChange={(event) => {
          setQuery(event.target.value);
          setOpen(true);
        }}
        onFocus={() => setOpen(true)}
      />
      {open && query.trim().length >= 2 && (
        <div
          data-test="patient-search-results"
          className="absolute z-20 mt-1 max-h-52 w-full overflow-y-auto rounded-md border border-border bg-popover shadow-md"
        >
          {results.length ? (
            results.map((result) => (
              <button
                key={result.id}
                type="button"
                data-test="patient-result"
                onClick={() => {
                  onSelect(result);
                  setOpen(false);
                }}
                className="block w-full px-3 py-2 text-left text-sm hover:bg-accent"
              >
                {result.name}
              </button>
            ))
          ) : (
            <p className="px-3 py-2 text-sm text-muted-foreground">
              {isFetching ? "Searching…" : "No patients found"}
            </p>
          )}
        </div>
      )}
    </div>
  );
}
