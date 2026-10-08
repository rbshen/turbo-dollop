// The one pill look every Status, Verdict and Badge renders (docs/design-system.md,
// "Pills"): a soft tinted fill, tone-coloured text, no border, in two sizes.
// Not a component of its own -- Status/Verdict/Badge add their own semantics
// (direction glyph, `missing` state) on top of this class list, so a status
// can never look different depending on which of them drew it.
import { cva, type VariantProps } from "class-variance-authority";

export const pillVariants = cva("inline-flex max-w-full items-center whitespace-nowrap rounded-md", {
  variants: {
    tone: {
      strong: "bg-positive-strong/16 text-positive-strong",
      positive: "bg-positive/16 text-positive",
      warn: "bg-warn/16 text-warn",
      caution: "bg-caution/16 text-caution",
      negative: "bg-negative/16 text-negative",
      // "May not pass" (slate): a 14% fill, not 16%, so its text clears 4.5:1 on its own tint on every surface (docs/design-system.md, "Pills").
      "not-pass": "bg-not-pass/14 text-not-pass",
      speculative: "bg-chart-purple/16 text-chart-purple",
      neutral: "bg-surface-2 text-text-secondary",
    },
    size: {
      regular: "gap-1.5 px-2 py-1 text-xs font-semibold",
      // Dense tables (Watchlist, Momentum): quieter type and padding, same tint.
      compact: "gap-1 px-1.5 py-0.5 text-[11px] font-medium",
    },
  },
  defaultVariants: {
    tone: "neutral",
    size: "regular",
  },
});

export type PillTone = NonNullable<VariantProps<typeof pillVariants>["tone"]>;
export type PillSize = NonNullable<VariantProps<typeof pillVariants>["size"]>;
