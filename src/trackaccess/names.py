"""Plain-English names for everything that has a code.

Codes stay in brackets once so the CSVs can still be matched, but nobody should
have to decode C007 or SEC:BET:H01_H02:EB to understand a sentence.
"""
from __future__ import annotations

from .model import Instance

LINE = {"ALP": "Alpha line", "BET": "Beta line"}
BOUND = {"EB": "eastbound", "WB": "westbound"}
TIER = {1: "critical", 2: "important", 3: "routine"}
JOB_TIER = {1: "high", 2: "default", 3: "low"}


def job_priority(inst: Instance, aid: str) -> str:
    """'high priority within its contract' -- the nudge, not the band."""
    return f"{JOB_TIER[inst.activities[aid].activity_priority]} priority within its contract"


def place(loc: str) -> str:
    """SEC:BET:S15_S16:EB -> 'Beta line eastbound, S15–S16 tunnel'"""
    kind, line, mid, bound = loc.split(":")
    where = f"{LINE.get(line, line)} {BOUND.get(bound, bound)}"
    if kind == "SEC":
        return f"{where}, {mid.replace('_', '–')} tunnel"
    return f"{where}, {mid} platform"


def place_short(loc: str) -> str:
    """For tables: 'Beta EB · S15–S16 tunnel'"""
    kind, line, mid, bound = loc.split(":")
    line_s = {"ALP": "Alpha", "BET": "Beta"}.get(line, line)
    what = f"{mid.replace('_', '–')} tunnel" if kind == "SEC" else f"{mid} platform"
    return f"{line_s} {bound} · {what}"


def contract(inst: Instance, cn: str, with_code: bool = True) -> str:
    c = inst.contracts[cn]
    return f"{c.contract_description} ({cn})" if with_code else c.contract_description


def contractor(inst: Instance, cn: str) -> str:
    """Who they are, with the detail a controller wants: 'Renewal programme 7 —
    critical, non-live consist work'."""
    c = inst.contracts[cn]
    nature = {"Live": "live-rail", "Non-live (Consist)": "non-live consist",
              "Non-live (Others)": "non-live"}.get(c.nature_of_activity,
                                                  c.nature_of_activity)
    return f"{c.contract_description} — {TIER[c.contract_priority]}, {nature} work"


def job(inst: Instance, aid: str, with_code: bool = True) -> str:
    """'Renewal programme 7's job on the Alpha line westbound, S05–S06 tunnel (A046)'"""
    a = inst.activities[aid]
    c = inst.contracts[a.contract_number]
    start, end = a.start_location_id, a.end_location_id
    if start == end:
        where = place(start)
    else:
        s, e = start.split(":"), end.split(":")
        where = (f"{LINE.get(s[1], s[1])} {BOUND.get(s[3], s[3])}, "
                 f"{s[2].split('_')[0]} to {e[2].split('_')[-1]}")
    code = f" ({aid})" if with_code else ""
    return f"{c.contract_description}'s job on the {where}{code}"


def job_short(inst: Instance, aid: str) -> str:
    """For tables and buttons: 'Renewal programme 7 · S05–S06 (A046)'"""
    a = inst.activities[aid]
    c = inst.contracts[a.contract_number]
    s, e = a.start_location_id.split(":"), a.end_location_id.split(":")
    span = s[2] if s[2] == e[2] else f"{s[2].split('_')[0]}–{e[2].split('_')[-1]}"
    return f"{c.contract_description} · {span.replace('_', '–')} ({aid})"


def week(inst: Instance, w: int) -> str:
    return f"week {w} ({inst.week_start(w):%d %b})"
