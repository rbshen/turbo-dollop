"use client";

// Section family -- the borderless, rule-separated list/detail layout that
// replaces boxed Cards for most content: Section (a titled group), Tile (a
// hoverable repeated item, optionally a link), DefinitionRow (a label/value
// line), MetricTile (a headline figure), and SectionGrid (a two-column
// layout for a page of Sections).
import type { AnchorHTMLAttributes, HTMLAttributes, ReactNode } from "react";
import Link from "next/link";
import { cn } from "@/lib/utils";

export interface SectionProps extends Omit<HTMLAttributes<HTMLDivElement>, "title"> {
  title?: ReactNode;
}

export function Section({ title, children, className, ...props }: SectionProps) {
  return (
    <div className={cn("border-t border-border-subtle pt-6 pb-2", className)} {...props}>
      {title && <h2 className="mb-3 text-sm font-semibold text-text-primary">{title}</h2>}
      {children}
    </div>
  );
}

export interface TileProps extends HTMLAttributes<HTMLDivElement> {
  href?: string;
}

// Tile can render as a plain div or, when `href` is given, as a Next Link --
// callers decide whether it opens in a new tab (no target="_blank" here).
export function Tile({ href, children, className, ...props }: TileProps) {
  const tileClass = cn(
    "flex flex-col gap-3 border-t border-border-subtle pt-5 pb-2 hover:bg-surface",
    className,
  );
  if (href) {
    const { onClick, ...linkProps } = props as AnchorHTMLAttributes<HTMLAnchorElement>;
    return (
      <Link href={href} onClick={onClick} className={tileClass} {...linkProps}>
        {children}
      </Link>
    );
  }
  return (
    <div className={tileClass} {...props}>
      {children}
    </div>
  );
}

export interface DefinitionRowProps extends HTMLAttributes<HTMLDivElement> {
  label: ReactNode;
  value: ReactNode;
  tone?: "positive" | "negative";
}

export function DefinitionRow({ label, value, tone, className, ...props }: DefinitionRowProps) {
  return (
    <div
      className={cn("flex h-11 items-center justify-between gap-4 border-t border-border-subtle", className)}
      {...props}
    >
      <span className="text-sm text-text-secondary">{label}</span>
      <span
        className={cn(
          "font-mono text-sm tabular-nums",
          tone === "positive" && "text-positive",
          tone === "negative" && "text-negative",
          !tone && "text-text-primary",
        )}
      >
        {value}
      </span>
    </div>
  );
}

export interface MetricTileProps extends HTMLAttributes<HTMLDivElement> {
  label: ReactNode;
  value: ReactNode;
  note?: ReactNode;
}

export function MetricTile({ label, value, note, className, ...props }: MetricTileProps) {
  return (
    <div className={cn("flex flex-col gap-1", className)} {...props}>
      <span className="text-xs text-text-tertiary">{label}</span>
      <span className="font-mono text-3xl font-semibold tabular-nums text-text-primary">{value}</span>
      {note && <span className="text-xs text-text-tertiary">{note}</span>}
    </div>
  );
}

export function SectionGrid({ children, className, ...props }: HTMLAttributes<HTMLDivElement>) {
  return (
    <div className={cn("grid grid-cols-1 gap-y-10 md:grid-cols-2 md:gap-x-24", className)} {...props}>
      {children}
    </div>
  );
}
