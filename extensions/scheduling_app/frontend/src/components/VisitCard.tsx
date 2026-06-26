import { ChevronDown, ChevronRight, Trash2 } from "lucide-react";

import { MultiSelect } from "@/components/MultiSelect";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { RadioGroup, RadioGroupItem } from "@/components/ui/radio-group";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { labelColor } from "@/lib/colors";
import type { Category, ReferenceData, Visit } from "@/lib/types";

interface VisitCardProps {
  visit: Visit;
  index: number;
  total: number;
  category: Category;
  reference: ReferenceData;
  collapsed?: boolean;
  onToggleCollapse?: () => void;
  onChange: (patch: Partial<Visit>) => void;
  onRemove?: () => void;
}

export function VisitCard({
  visit,
  index,
  total,
  category,
  reference,
  collapsed = false,
  onToggleCollapse,
  onChange,
  onRemove,
}: VisitCardProps) {
  const isAppointment = category === "appointment";
  const visitType = reference.visitTypes.find((type) => type.id === visit.visitTypeId);

  // `visit.rfvCode` holds the coding's external id (what the structured command
  // needs), so match on `id`.
  const selectedRfv = reference.reasonsForVisit.find((rfv) => rfv.id === visit.rfvCode);
  const durations =
    selectedRfv && selectedRfv.durations.length ? selectedRfv.durations : reference.defaultDurations;

  const showCustomTitle = !isAppointment || !!visitType?.allowCustomTitle;
  const showMeetingLink = !!visitType?.isTelehealth;

  // Collapsed summary: providers · visit type · location.
  const providerNames = visit.providers
    .map((id) => reference.providers.find((p) => p.id === id)?.name)
    .filter(Boolean)
    .join(", ");
  const summary =
    [providerNames, visitType?.name, reference.locations.find((l) => l.id === visit.locationId)?.name]
      .filter(Boolean)
      .join(" · ") || "Incomplete visit";

  return (
    <div data-test={`visit-card-${index}`} className="space-y-4 rounded-lg border border-border p-4">
      {total > 1 && (
        <div className="flex items-center justify-between">
          <button
            type="button"
            data-test={`visit-collapse-toggle-${index}`}
            onClick={onToggleCollapse}
            className="flex items-center gap-2 text-sm font-semibold text-foreground"
          >
            {collapsed ? <ChevronRight className="h-4 w-4" /> : <ChevronDown className="h-4 w-4" />}
            Visit {index + 1}
          </button>
          {onRemove && (
            <button
              type="button"
              data-test={`visit-remove-${index}`}
              onClick={onRemove}
              className="text-muted-foreground hover:text-destructive"
              aria-label={`Remove visit ${index + 1}`}
            >
              <Trash2 className="h-4 w-4" />
            </button>
          )}
        </div>
      )}

      {collapsed ? (
        <p data-test={`visit-summary-${index}`} className="text-sm text-muted-foreground">
          {summary}
        </p>
      ) : (
        <div className="space-y-4">
      <div className="space-y-2">
        <Label>Provider{isAppointment ? "(s)" : ""}</Label>
        <MultiSelect
          dataTest="visit-providers"
          options={reference.providers.map((p) => ({ value: p.id, label: p.name }))}
          selected={visit.providers}
          onChange={(providers) => onChange({ providers })}
          placeholder="Select up to 3 providers"
          max={3}
        />
      </div>

      <div className="grid grid-cols-2 gap-4">
        <div className="space-y-2">
          <Label>Location</Label>
          <Select value={visit.locationId} onValueChange={(locationId) => onChange({ locationId })}>
            <SelectTrigger data-test="visit-location-select">
              <SelectValue placeholder="Select location" />
            </SelectTrigger>
            <SelectContent>
              {reference.locations.map((location) => (
                <SelectItem key={location.id} value={location.id}>
                  {location.name}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>

        <div className="space-y-2">
          <Label>{isAppointment ? "Visit type" : "Event type"}</Label>
          <Select value={visit.visitTypeId} onValueChange={(visitTypeId) => onChange({ visitTypeId })}>
            <SelectTrigger data-test="visit-type-select">
              <SelectValue placeholder="Select type" />
            </SelectTrigger>
            <SelectContent>
              {reference.visitTypes.map((type) => (
                <SelectItem key={type.id} value={type.id}>
                  {type.name}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
      </div>

      {showCustomTitle && (
        <div className="space-y-2">
          <Label>{isAppointment ? "Custom title" : "Event title"}</Label>
          <Input
            data-test="visit-custom-title"
            value={visit.description}
            onChange={(event) => onChange({ description: event.target.value })}
            placeholder={isAppointment ? "Optional title" : "e.g. Lunch, Out of office"}
          />
        </div>
      )}

      {showMeetingLink && (
        <div className="space-y-2">
          <Label>Meeting link</Label>
          <Input
            data-test="visit-meeting-link"
            value={visit.meetingLink}
            onChange={(event) => onChange({ meetingLink: event.target.value })}
            placeholder="https://…"
          />
        </div>
      )}

      {isAppointment && (
        <div className="space-y-2">
          <Label>Reason for visit</Label>
          {reference.structuredReasonForVisit ? (
            <div className="space-y-2">
              <Select
                value={visit.rfvCode || "__none__"}
                onValueChange={(value) => onChange({ rfvCode: value === "__none__" ? "" : value })}
              >
                <SelectTrigger data-test="visit-rfv-coded">
                  <SelectValue placeholder="Select a coded reason" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="__none__">No coded reason</SelectItem>
                  {reference.reasonsForVisit.map((rfv) => (
                    <SelectItem key={rfv.id} value={rfv.id}>
                      {rfv.display}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
              {/* Optional free-text comment alongside the coded reason, like the
                  built-in modal's structured-RFV comment field. */}
              <Input
                data-test="visit-rfv-comment"
                value={visit.comment}
                onChange={(event) => onChange({ comment: event.target.value })}
                placeholder="Comment (optional)"
              />
            </div>
          ) : (
            <Input
              data-test="visit-rfv-text"
              value={visit.rfvText}
              onChange={(event) => onChange({ rfvText: event.target.value })}
              placeholder="Reason for visit"
            />
          )}
        </div>
      )}

      <div className="space-y-2">
        <Label>Duration</Label>
        <RadioGroup
          value={visit.durationMinutes}
          onValueChange={(durationMinutes) => onChange({ durationMinutes })}
        >
          {durations.map((minutes) => (
            <label key={minutes} className="flex cursor-pointer items-center gap-2 text-sm">
              <RadioGroupItem data-test={`visit-duration-${minutes}`} value={String(minutes)} />
              {minutes} min
            </label>
          ))}
        </RadioGroup>
      </div>

      {isAppointment && (
        <div className="space-y-2">
          <Label>Labels</Label>
          <MultiSelect
            dataTest="visit-labels"
            options={reference.labels.map((label) => ({
              value: label.name,
              label: label.name,
              color: labelColor(label.color),
            }))}
            selected={visit.labels}
            onChange={(labels) => onChange({ labels })}
            placeholder="Add up to 3 labels"
            max={3}
          />
        </div>
      )}
        </div>
      )}
    </div>
  );
}
