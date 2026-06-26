// Maps the backend `ColorEnum` label colors (canvas_sdk.v1.data.common.ColorEnum)
// to hex values approximating the EHR's palette, so label chips render in the
// same colors as the built-in modal. White text reads on all of them.

const LABEL_COLORS: Record<string, string> = {
  red: "#db2828",
  orange: "#f2711c",
  yellow: "#fbbd08",
  olive: "#b5cc18",
  green: "#21ba45",
  teal: "#00b5ad",
  blue: "#2185d0",
  violet: "#6435c9",
  purple: "#a333c8",
  pink: "#e03997",
  brown: "#a5673f",
  grey: "#767676",
  black: "#1b1c1d",
};

/** Hex color for a backend ColorEnum value, or undefined when unset/unknown. */
export function labelColor(color?: string | null): string | undefined {
  return color ? LABEL_COLORS[color] : undefined;
}
