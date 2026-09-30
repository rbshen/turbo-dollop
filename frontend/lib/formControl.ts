// Shared constants for the form-control family (NumberField, Input, Select,
// FormField, the Settings kit). See "Form controls" in docs/design-system.md.

/** Width tokens. Every control is 36px high (h-9) whatever its width. */
export const FIELD_SIZES = ["short", "medium", "wide", "full"] as const;
export type FieldSize = (typeof FIELD_SIZES)[number];

/** short 96px, medium 176px, wide 320px -- each capped at the container's
 * width; full fills the container. */
export const FIELD_SIZE_CLASS: Record<FieldSize, string> = {
  short: "w-24 max-w-full",
  medium: "w-44 max-w-full",
  wide: "w-80 max-w-full",
  full: "w-full",
};

/** The boxed field shell: 36px high, radius-md, 1px border-control, page
 * fill. Focus is never styled here -- the global 2px :focus-visible outline
 * (globals.css) does it, so nothing in this family sets focus:outline-none. */
export const FIELD_BOX_CLASS =
  "h-9 rounded-md border border-border-control bg-page px-3 text-sm text-text-primary placeholder:text-text-tertiary transition-colors disabled:cursor-not-allowed disabled:opacity-45";

export const FIELD_INVALID_CLASS = "border-negative";

/** Joins ids for an aria-describedby list, dropping empty entries. */
export function joinIds(...ids: (string | false | null | undefined)[]): string | undefined {
  const joined = ids.filter(Boolean).join(" ");
  return joined === "" ? undefined : joined;
}
