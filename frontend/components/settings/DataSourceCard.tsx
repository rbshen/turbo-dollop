import { formatRelativeTime } from "@/lib/relativeTime";
import type { DataSourceStatusOut } from "@/lib/api/types";
import { cn } from "@/lib/utils";

const STATUS_BADGE: Record<DataSourceStatusOut["status"], string> = {
  healthy: "bg-positive/16 text-positive border-positive/40",
  disabled_or_failing: "bg-negative/16 text-negative border-negative/40",
  stale: "bg-warn/16 text-warn border-warn/40",
};

const STATUS_DOT: Record<DataSourceStatusOut["status"], string> = {
  healthy: "bg-positive",
  disabled_or_failing: "bg-negative",
  stale: "bg-warn",
};

const STATUS_LABEL: Record<DataSourceStatusOut["status"], string> = {
  healthy: "Healthy",
  disabled_or_failing: "Disabled or failing",
  stale: "Serving stale data",
};

interface Props {
  title: string;
  /** e.g. an env flag name -- shown next to the title. Yahoo has
   * no kill-switch flag at all (see clients/yahoo_client.py's own
   * docstring), so this is omitted for that card. */
  flagLabel?: string;
  status: DataSourceStatusOut | undefined;
  /** Which parts of the app this source feeds -- static, given by the
   * product spec rather than derived from anything live. */
  powers: string[];
}

/** One Data Sources card (FMP or Yahoo Finance) in the Settings "Status"
 * section -- health dot + badge computed purely from `status` (never a
 * live reachability ping, see core/data_source_status.py), a "last
 * successful fetch" relative timestamp, the static Powers tag list, and a
 * cached-data note shown only while genuinely disabled/failing. Renders a
 * loading-shaped placeholder badge while `status` is undefined (the
 * fetch hasn't resolved yet), same "show the shape, not a blank" idea as
 * the rest of this app's SWR-backed cards. */
export function DataSourceCard({ title, flagLabel, status, powers }: Props) {
  const lastSuccess = status?.last_success_at ? formatRelativeTime(status.last_success_at) : "never";

  return (
    <div className="flex-1 space-y-4 rounded-lg border border-zinc-800 bg-zinc-900/40 p-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="flex items-center gap-2">
          <span className={cn("size-2 shrink-0 rounded-full", status ? STATUS_DOT[status.status] : "bg-zinc-600")} />
          <h3 className="text-sm font-semibold text-zinc-100">{title}</h3>
          {flagLabel && <span className="font-mono text-[10px] uppercase tracking-wide text-zinc-500">{flagLabel}</span>}
        </div>
        {status && (
          <span
            className={cn(
              "shrink-0 rounded-full border px-2.5 py-0.5 text-xs font-semibold",
              STATUS_BADGE[status.status]
            )}
          >
            {STATUS_LABEL[status.status]}
          </span>
        )}
      </div>

      <p className="text-sm text-zinc-400">
        Last successful fetch <span className="font-medium text-zinc-200">{lastSuccess}</span>.
      </p>

      <div className="space-y-1.5">
        <p className="text-xs font-medium uppercase tracking-wide text-zinc-500">Powers</p>
        <div className="flex flex-wrap gap-1.5">
          {powers.map((power) => (
            <span key={power} className="rounded-md bg-zinc-800/60 px-2 py-0.5 text-xs text-zinc-300">
              {power}
            </span>
          ))}
        </div>
      </div>

      {status?.status === "disabled_or_failing" && (
        <p className="rounded-md border border-warn/40 bg-warn/10 p-3 text-xs text-warn">
          Serving cached data. {powers.join(" / ")} may be stale.
        </p>
      )}
    </div>
  );
}
