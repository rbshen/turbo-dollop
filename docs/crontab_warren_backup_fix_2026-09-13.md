# Crontab Fix: nightly_warren_signal_calculation + backup_db — 2026-09-13

Follow-up to `288a0d3`. Live-crontab fix executed (a config action, not a code change) plus
one investigation-only item, per this task's scope.

## 1-2. Fix applied: reinstalled the live crontab from `backend/crontab.txt`

Before touching anything, re-ran the same diff `288a0d3` used to characterize the drift, to
confirm the fix's exact blast radius first:

```
diff <(crontab -l) backend/crontab.txt
```

Two hunks, exactly as previously found — a pure addition (`nightly_warren_signal_calculation`
at `40 3 * * *`) and a pure replacement (`backup_db`'s old `35 3 * * *` line superseded
entirely by the new `55 3 * * *` line, comment included). Critically, **every line unique to
the live crontab had a direct, superseding replacement in `crontab.txt` — nothing in the live
crontab was orphaned or would be lost by a wholesale reinstall.** `crontab.txt` is already the
correct, version-controlled source of truth for both jobs (per its own in-file comments,
dated 2026-09-12, and confirmed against the file rather than reconstructed from memory), so
the fix is the single action the prior report already identified: reinstall from it rather
than hand-edit two separate lines.

```
crontab /home/shen/fathom/backend/crontab.txt
```

## 3. Proof the fix took: live crontab vs. `crontab.txt`, re-diffed after the change

```
diff <(crontab -l) backend/crontab.txt
```

**Empty diff — byte-identical.** Confirmed directly (not assumed from the install command's
exit status) by re-running the exact same check used in `3cd37b6` to validate
`nightly_trend_calculation`'s own installation. The relevant slice of the now-live schedule:

```
10 3 * * *  pipeline.nightly_trend_calculation
20 3 * * *  pipeline.nightly_entry_signal_calculation
25 3 * * *  pipeline.nightly_liquidity_zone_calculation
40 3 * * *  pipeline.nightly_warren_signal_calculation   <- restored
55 3 * * *  pipeline.backup_db                            <- corrected from 35
```

No collisions: Liquidity Zone (3:25) still precedes Warren's own restored 3:40-3:55 window
cleanly, and backup_db now runs strictly after it, matching the design `crontab.txt`'s own
comments describe.

## 4. Next expected fire — nothing triggered manually, per instructions

System timezone confirmed `Etc/UTC` (`timedatectl`), so `40 3 * * *` means 03:40 UTC daily.
Current time at the point of this fix: **2026-09-13 09:09 UTC** — already well past today's
03:40 slot, so the next natural firing is:

**2026-09-14, 03:40 UTC.**

Check `logs/nightly_warren_signal_calculation_cron.log` and/or
`CronRunLog` (`job_name = "pipeline.nightly_warren_signal_calculation"`) after that time to
confirm it actually fired — a fresh `CronRunLog` row with `started_at` in the
`2026-09-14 03:4x` range (its own timing may run a few minutes past 3:40 depending on real
execution duration, per the ~15-minute window this slot is sized for) is the concrete
confirmation to look for. No manual invocation was run as part of this fix, as instructed.

## 5. `CRON_HEALTH_ENABLED=false` — investigated, not toggled

**This is the documented, intended pairing for this environment, not an oversight.**
`backend/.env.example`'s own comment for this setting states outright:

> Gates only `GET /api/config/cron-health`'s reporting and the frontend `CronHealthBanner`
> -- `CronRunLog` rows keep being written regardless, so history isn't lost while this is
> off. **Useful for muting cron-health surfacing during an extended `FMP_ENABLED=false`
> pause.**

This environment's `.env` has **both** `FMP_ENABLED=false` and `CRON_HEALTH_ENABLED=false`
set together — exactly the paired combination the template describes, not one flag left on
by accident while the other was deliberately flipped. `core/config.py`'s own default for
`cron_health_enabled` is `True` (matching `.env.example`'s own `CRON_HEALTH_ENABLED=true`
default line) — someone explicitly overrode it to `false` here, in the same file where
`FMP_ENABLED` was also explicitly overridden to `false`, consistent with this being a
long-running local/offline dev sandbox (no live FMP calls at all) rather than a
misconfigured production-like environment. `.env` is gitignored (confirmed via `git
check-ignore`), so there's no commit history to check on the file itself — the
`.env.example` template's own comment is the closest thing to a documented rationale, and it
matches this environment's actual configuration exactly.

**Recommendation: leave it as-is.** Flipping it on here, with FMP still paused, would
surface exactly the noisy, false-alarm-shaped banner state the setting exists to mute (per
its own docstring) — not a genuine improvement for a sandbox that's going to keep running
FMP-disabled. This is not being toggled per the task's instructions either way.

**One real, worth-noting tradeoff surfaced by this exact incident, though, not a reason to
flip the flag:** the setting only mutes *reporting*, and `CronRunLog` rows are confirmed
still written underneath regardless (verified directly in `288a0d3`'s own investigation —
Warren's single stale `CronRunLog` entry was found and dated precisely, with health
reporting off the whole time) — so no data was lost. But it does mean a genuinely unrelated
infra problem (a crontab reinstall gap, nothing to do with FMP being paused) rode along
completely invisible to the in-app banner for as long as this flag stayed off, and was only
caught by a manual `crontab -l` vs. `crontab.txt` diff. That's the setting doing exactly
what its own docstring says it does — not a bug in the flag — but it's worth whoever manages
this environment knowing that "cron health banner is quiet" isn't the same guarantee as
"every cron job is actually running on schedule" while this flag is off, regardless of the
reason it's off.

## Summary

| Item | Status |
|---|---|
| `nightly_warren_signal_calculation` restored to live crontab (3:40 AM) | Done, verified |
| `backup_db` corrected to 3:55 AM live | Done, verified |
| Live crontab vs. `crontab.txt` | Byte-identical, re-confirmed after the change |
| Warren job manually triggered | Not done, per instructions -- next natural fire: 2026-09-14 03:40 UTC |
| `CRON_HEALTH_ENABLED=false` | Investigated: intentional, paired with `FMP_ENABLED=false` per `.env.example`'s own documented rationale. Recommend leaving off; not toggled. |
