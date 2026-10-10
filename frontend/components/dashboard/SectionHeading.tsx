import type { ReactNode } from "react";

/** A Dashboard section's heading: the title, and a small neutral tag saying whether the section is scored. */
export function SectionHeading({ title, tag, note }: { title: string; tag: string; note?: ReactNode }) {
  return (
    <div className="mb-3">
      <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
        <h2 className="text-sm font-semibold text-text-primary">{title}</h2>
        <span className="text-xs text-text-tertiary">{tag}</span>
      </div>
      {note && <p className="mt-1 max-w-3xl text-xs text-text-tertiary">{note}</p>}
    </div>
  );
}
