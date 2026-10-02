"""Operator CLI for the FMP data-group toggles (core/data_groups.py) -- the
way to flip the master switch when the API/UI is down.

    uv run python -m pipeline.data_groups pause-all   # master OFF: cache-only everywhere, nothing wiped
    uv run python -m pipeline.data_groups resume      # master ON (per-group settings untouched)
    uv run python -m pipeline.data_groups status      # one line per group
    uv run python -m pipeline.data_groups backfill-last-success  # seed 'last success' from cache fetched_at (idempotent)
    uv run python -m pipeline.data_groups variants    # list restricted request variants (a 402'd period/limit; the group stays live)
    uv run python -m pipeline.data_groups retest      # re-test every restricted variant with its own request; clears only on success
    uv run python -m pipeline.data_groups clear-variant --group fundamentals --key '/income-statement?limit=12&period=quarter'

Takes effect live -- no backend restart (the API/cron processes re-read the
DB within a few seconds). Not a cron job (no cron_heartbeat / CRON_JOB_NAMES
entry): it is manual-only."""

import argparse
import asyncio
import sys

import core.data_groups as dg
from core.db import init_db


def _fmt_dt(value) -> str:
    return value.strftime("%Y-%m-%d %H:%M") if value else "-"


def format_status() -> str:
    snap = dg.get_snapshot()
    lines = [
        f"FMP master switch: {'ON' if snap.master_on else 'OFF (paused: cache-only everywhere)'}",
        f"My FMP plan: {snap.fmp_plan}",
    ]
    if snap.key_problem_at:
        lines.append(f"KEY PROBLEM since {_fmt_dt(snap.key_problem_at)}: {snap.key_problem_detail}")
    lines.append("")
    lines.append(f"{'group':<19} {'state':<22} {'tier':<9} last success")
    for key in dg.GROUPS:
        st = snap.groups[key]
        live, reason = dg.effective_state_from(snap, key)
        state = "live" if live else reason
        if live and st.status == "failing":
            state = "live (failing)"
        wired = "" if dg.GROUPS[key].live else " [not wired yet]"
        lines.append(
            f"{key:<19} {state:<22} {st.required_tier:<9} "
            f"{_fmt_dt(st.last_success_at)}{wired}"
        )
    variants = dg.restricted_variants()
    if variants:
        lines.append("")
        lines.append("Restricted request variants (group stays live):")
        for v in variants:
            probed = f", last re-test {_fmt_dt(v.last_probe_at)}" if v.last_probe_at else ""
            lines.append(f"  {v.group:<14} {v.label}  [{v.variant_key}]  since {_fmt_dt(v.restricted_since)}{probed}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Manage FMP data-group toggles.")
    parser.add_argument("command", choices=["pause-all", "resume", "status", "backfill-last-success", "variants", "retest", "clear-variant"])
    parser.add_argument("--group", default=None, help="clear-variant: the group")
    parser.add_argument("--key", default=None, help="clear-variant: the variant key shown by `variants`")
    args = parser.parse_args(argv)

    init_db()
    if args.command == "pause-all":
        dg.set_master(False)
        print("FMP master switch OFF -- every group is cache-only. Nothing was wiped.")
    elif args.command == "backfill-last-success":
        for group, value in dg.backfill_last_success_from_cache().items():
            print(f"{group:<19} {_fmt_dt(value) if value else 'unchanged / no cache rows'}")
    elif args.command == "retest":
        from clients.fmp_client import fmp_client

        results = asyncio.run(fmp_client.reprobe_restricted_variants())
        print("\n".join(f"{k}: {v}" for k, v in results.items()) or "No restricted variants to re-test (or the master switch is off).")
    elif args.command == "clear-variant":
        if not (args.group and args.key):
            parser.error("clear-variant needs --group and --key")
        print("Cleared." if dg.clear_variant(args.group, args.key, "cleared manually (CLI)") else "No such restricted variant.")
    elif args.command == "resume":
        dg.set_master(True)
        print("FMP master switch ON -- each group follows its own setting again.")
    print(format_status())
    return 0


if __name__ == "__main__":
    sys.exit(main())
