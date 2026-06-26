import { Check, ChevronDown } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { cn } from "@/lib/utils";

interface Option {
  value: string;
  label: string;
  /** Optional chip/dot color (hex) — used for colored labels. */
  color?: string;
}

interface MultiSelectProps {
  options: Option[];
  selected: string[];
  onChange: (values: string[]) => void;
  placeholder?: string;
  max?: number;
  /** Base for the e2e selectors: `${dataTest}-trigger`, `-content`, `-option`. */
  dataTest?: string;
}

/**
 * Compute the selection after toggling `value`: removing it if present, adding it
 * if under `max`, or leaving it unchanged once the cap is reached. Returns the
 * SAME array reference when nothing changes (so callers can skip a no-op update).
 */
export function nextSelection(selected: string[], value: string, max?: number): string[] {
  if (selected.includes(value)) return selected.filter((v) => v !== value);
  if (!max || selected.length < max) return [...selected, value];
  return selected;
}

export function MultiSelect({
  options,
  selected,
  onChange,
  placeholder = "Select…",
  max,
  dataTest,
}: MultiSelectProps) {
  const toggle = (value: string) => {
    const next = nextSelection(selected, value, max);
    if (next !== selected) onChange(next);
  };

  const chosen = options.filter((o) => selected.includes(o.value));

  return (
    <Popover>
      <PopoverTrigger asChild>
        <Button
          data-test={dataTest ? `${dataTest}-trigger` : undefined}
          variant="outline"
          className="h-auto min-h-9 w-full justify-between py-1.5 font-normal"
        >
          <span className="flex flex-wrap gap-1">
            {chosen.length ? (
              chosen.map((o) => (
                <Badge
                  key={o.value}
                  style={
                    o.color ? { backgroundColor: o.color, borderColor: o.color, color: "#fff" } : undefined
                  }
                >
                  {o.label}
                </Badge>
              ))
            ) : (
              <span className="text-muted-foreground">{placeholder}</span>
            )}
          </span>
          <ChevronDown className="h-4 w-4 shrink-0 opacity-50" />
        </Button>
      </PopoverTrigger>
      <PopoverContent
        data-test={dataTest ? `${dataTest}-content` : undefined}
        className="max-h-64 overflow-y-auto"
      >
        {options.length ? (
          options.map((o) => {
            const isSelected = selected.includes(o.value);
            const disabled = !isSelected && !!max && selected.length >= max;
            return (
              <button
                key={o.value}
                type="button"
                data-test={dataTest ? `${dataTest}-option` : undefined}
                disabled={disabled}
                onClick={() => toggle(o.value)}
                className={cn(
                  "flex w-full items-center gap-2 rounded-sm px-2 py-1.5 text-left text-sm hover:bg-accent disabled:opacity-40",
                  isSelected && "font-medium",
                )}
              >
                <Check className={cn("h-4 w-4", isSelected ? "opacity-100" : "opacity-0")} />
                {o.color && (
                  <span
                    className="h-2.5 w-2.5 shrink-0 rounded-full"
                    style={{ backgroundColor: o.color }}
                  />
                )}
                {o.label}
              </button>
            );
          })
        ) : (
          <p className="px-2 py-1.5 text-sm text-muted-foreground">No options</p>
        )}
      </PopoverContent>
    </Popover>
  );
}
