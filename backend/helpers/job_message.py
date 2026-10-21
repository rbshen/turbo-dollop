"""Small pure helpers for the one-line result messages of the cron jobs (CronRunLog.error_summary, shown on Settings > Scheduled Jobs)."""

NAME_LIST_CAP = 10


def name_list(names: list[str], cap: int = NAME_LIST_CAP) -> str:
    """"AAA, BBB" for up to `cap` names, then ", +N more". Empty string for no names. Order is kept as given."""
    if not names:
        return ""
    shown = ", ".join(names[:cap])
    return f"{shown}, +{len(names) - cap} more" if len(names) > cap else shown


def counted(count: int, label: str, names: list[str] | None = None) -> str:
    """"6 no analyst data (AAA, BBB)": the count and label, plus the capped name list only when names were given for that count."""
    return f"{count} {label} ({name_list(names)})" if names else f"{count} {label}"


def labelled(label: str, count: int, names: list[str] | None = None) -> str:
    """"failed 1 (BBB)": the label first, for the problem lists of the opportunity jobs ("gaps 3, incomplete 2, failed 1 (BBB)")."""
    return f"{label} {count} ({name_list(names)})" if names else f"{label} {count}"
