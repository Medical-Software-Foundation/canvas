import { ChevronLeft, ChevronRight } from "lucide-react";

import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { RadioGroup, RadioGroupItem } from "@/components/ui/radio-group";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { effectiveTimes, shiftDate } from "@/lib/datetime";
import type { Frequency, Grouping, RecurrenceForm, Visit } from "@/lib/types";

interface WhenPaneProps {
  date: string;
  onDateChange: (date: string) => void;
  visits: Visit[];
  grouping: Grouping;
  onVisitTimeChange: (index: number, time: string) => void;
  // Recurrence is rendered only when both are supplied (appointments, not reschedule).
  recurrence?: RecurrenceForm;
  onRecurrenceChange?: (patch: Partial<RecurrenceForm>) => void;
}

export function WhenPane({
  date,
  onDateChange,
  visits,
  grouping,
  onVisitTimeChange,
  recurrence,
  onRecurrenceChange,
}: WhenPaneProps) {
  const times = effectiveTimes(visits, grouping);

  return (
    <div className="space-y-4">
      <div className="space-y-2">
        <Label>Date</Label>
        <div className="flex items-center gap-2">
          <button
            type="button"
            data-test="when-date-prev"
            onClick={() => onDateChange(shiftDate(date, -1))}
            className="rounded-md border border-input p-2 hover:bg-accent"
            aria-label="Previous day"
          >
            <ChevronLeft className="h-4 w-4" />
          </button>
          <Input
            type="date"
            data-test="when-date-input"
            value={date}
            onChange={(event) => onDateChange(event.target.value)}
            className="flex-1"
          />
          <button
            type="button"
            data-test="when-date-next"
            onClick={() => onDateChange(shiftDate(date, 1))}
            className="rounded-md border border-input p-2 hover:bg-accent"
            aria-label="Next day"
          >
            <ChevronRight className="h-4 w-4" />
          </button>
        </div>
      </div>

      <div className="space-y-3">
        {visits.map((_visit, index) => {
          const chained = grouping === "sequential" && index > 0;
          return (
            <div key={index} className="space-y-2">
              <Label>{visits.length > 1 ? `Visit ${index + 1} time` : "Time"}</Label>
              <Input
                type="time"
                data-test={`when-time-${index}`}
                value={times[index]}
                disabled={chained}
                onChange={(event) => onVisitTimeChange(index, event.target.value)}
              />
              {chained && (
                <p className="text-xs text-muted-foreground">Starts after the previous visit ends.</p>
              )}
            </div>
          );
        })}
      </div>

      {recurrence && onRecurrenceChange && (
        <div className="space-y-3 border-t border-border pt-4">
          <label className="flex cursor-pointer items-center gap-2 text-sm font-medium">
            <input
              type="checkbox"
              data-test="recurrence-toggle"
              checked={recurrence.enabled}
              onChange={(event) => onRecurrenceChange({ enabled: event.target.checked })}
            />
            Repeats
          </label>

          {recurrence.enabled && (
            <div className="space-y-3">
              <div className="grid grid-cols-2 gap-2">
                <div className="space-y-1">
                  <Label>Frequency</Label>
                  <Select
                    value={recurrence.frequency}
                    onValueChange={(value) =>
                      onRecurrenceChange({ frequency: value as Frequency })
                    }
                  >
                    <SelectTrigger data-test="recurrence-frequency">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="daily">Daily</SelectItem>
                      <SelectItem value="weekly">Weekly</SelectItem>
                      <SelectItem value="monthly">Monthly</SelectItem>
                    </SelectContent>
                  </Select>
                </div>
                <div className="space-y-1">
                  <Label>Every</Label>
                  <Input
                    type="number"
                    min={1}
                    data-test="recurrence-interval"
                    value={recurrence.interval}
                    onChange={(event) =>
                      onRecurrenceChange({ interval: Number(event.target.value) })
                    }
                  />
                </div>
              </div>

              <div className="space-y-2">
                <Label>Ends</Label>
                <RadioGroup
                  value={recurrence.end}
                  onValueChange={(value) =>
                    onRecurrenceChange({ end: value as "count" | "until" })
                  }
                >
                  <label className="flex items-center gap-2 text-sm">
                    <RadioGroupItem data-test="recurrence-end-count-radio" value="count" />
                    After
                    <Input
                      type="number"
                      min={2}
                      data-test="recurrence-end-count"
                      value={recurrence.count}
                      disabled={recurrence.end !== "count"}
                      onChange={(event) =>
                        onRecurrenceChange({ count: Number(event.target.value) })
                      }
                      className="w-20"
                    />
                    occurrences
                  </label>
                  <label className="flex items-center gap-2 text-sm">
                    <RadioGroupItem data-test="recurrence-end-until-radio" value="until" />
                    On
                    <Input
                      type="date"
                      data-test="recurrence-end-date"
                      value={recurrence.until}
                      disabled={recurrence.end !== "until"}
                      onChange={(event) => onRecurrenceChange({ until: event.target.value })}
                      className="flex-1"
                    />
                  </label>
                </RadioGroup>
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
