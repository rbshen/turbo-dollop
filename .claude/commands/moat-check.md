---
description: Run the independent Moat check on one ticker (two blind research passes, saved as one check)
argument-hint: <ticker>
disable-model-invocation: true
allowed-tools: Bash(uv run --directory backend python -m pipeline.moat_check_prepare *), Bash(uv run --directory backend python -m pipeline.moat_check_save *), Bash(uv run --directory backend python -m pipeline.moat_check_finish *), Agent(moat-pass-1), Agent(moat-pass-2)
---

Run the independent Moat check for the ticker in $ARGUMENTS. Spec: docs/specs/moat-check.md. The criteria are docs/specs/moat-criteria.md: the passes read their own copy, you never open, quote or summarise them.

Hard rules:
- $ARGUMENTS must be exactly one ticker symbol (letters, digits, "." or "-"). If it is anything else, say so and stop.
- Never read, query or print any stored Moat rating, score or earlier check for this ticker, by any means, before or after the passes. The card compares them.
- Start the passes only as the named agents below, never as a fork, and give them only the text below.

1. Prepare: run `uv run --directory backend python -m pipeline.moat_check_prepare <ticker>`. If it exits non-zero, print its message and stop. Keep the `run_dir`, `run_date` and `stale_cutoff` values it prints, and show the user the margin rule and cache dates it printed.
2. Passes: in one message start `moat-pass-1` and `moat-pass-2` in parallel, each with this prompt, where N is the pass number:
   "Ticker: <ticker>. RUN_DATE: <run_date>. Stale cutoff: data periods ending before <stale_cutoff> are stale. Your folder: <run_dir>/passN. Read criteria.md and block.json there, follow criteria.md, write out.json there, reply with one line."
3. Save: run `uv run --directory backend python -m pipeline.moat_check_save <ticker> <run_dir>/pass1/out.json <run_dir>/pass2/out.json <run_date>`.
   - Exit 2 means a pass record was invalid or missing; the problem lines start with "pass 1:" or "pass 2:". Start again only the pass(es) named, once, with the same prompt plus those problem lines, then save again. If it still fails, print the problems, keep `run_dir` and stop.
   - Any other non-zero exit: print the message, keep `run_dir` and stop.
4. Done: print the one-line result and any warning lines, then run `uv run --directory backend python -m pipeline.moat_check_finish <run_dir>`.

A kept `run_dir` is removed by the next run once it is a day old.
