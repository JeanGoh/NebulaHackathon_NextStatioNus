"""Check a programme folder before anything tries to use it.

The judges run this on their own data. Without this, a renamed column shows up
as KeyError: 'station_id' somewhere deep in the loader, and a missing file
leaks a temp path. Every problem here names the file, the row and the fix.
"""
from __future__ import annotations

import csv
import datetime
from pathlib import Path

COLUMNS = {
    "01_LINES.csv": ["line_code", "line_name"],
    "02_STATIONS.csv": ["station_id", "line_code", "seq", "is_interchange"],
    "03_SECTORS.csv": ["sector_id", "line_code", "from_station_id",
                       "to_station_id", "seq", "is_shared"],
    "04_LOCATION_SUPPLY.csv": ["location_id", "location_kind", "line_code",
                               "bound", "supply_capacity"],
    "05_BUFFER_LOCATION.csv": ["nature_of_works", "up_to_buffer_sectors",
                               "opposite_bound_required"],
    "06_PARAMETERS.csv": ["key", "value"],
    "07_PROJECT_DETAILS.csv": ["contract_number", "contract_description",
                               "contract_award_date", "activity_type",
                               "nature_of_activity", "contract_priority",
                               "contract_completion_date",
                               "planned_completion_date", "number_of_workfronts",
                               "access_type", "number_of_maximum_access_per_week"],
    "08_ACTIVITY_DETAILS.csv": ["activity_id", "contract_number", "activity_type",
                                "start_location_id", "end_location_id",
                                "total_accesses", "planned_start_date",
                                "predecessor_activity_id", "activity_priority"],
}
ACCESS_TYPES = {"PM", "PC", "C"}


def _rows(p: Path) -> list[dict]:
    with p.open(newline="", encoding="utf-8-sig") as fh:
        return [r for r in csv.DictReader(fh)
                if any((v or "").strip() for v in r.values())]


def _int(v, where, what, problems, low=None):
    try:
        n = int(str(v).strip())
    except (TypeError, ValueError):
        problems.append(f"{where}: {what} is {v!r}, which is not a whole number")
        return None
    if low is not None and n < low:
        problems.append(f"{where}: {what} is {n}, which must be at least {low}")
        return None
    return n


def check(data_dir: str | Path) -> list[str]:
    """Everything wrong with this folder, in plain English. Empty list = usable."""
    d = Path(data_dir)
    problems: list[str] = []

    tables: dict[str, list[dict]] = {}
    for name, cols in COLUMNS.items():
        f = d / name
        if not f.exists():
            problems.append(f"{name} is missing from the folder")
            continue
        try:
            rows = _rows(f)
        except Exception as exc:
            problems.append(f"{name} could not be read as CSV ({exc})")
            continue
        if not rows:
            problems.append(f"{name} has no data rows")
            continue
        missing = [c for c in cols if c not in rows[0]]
        if missing:
            problems.append(f"{name} is missing column(s): {', '.join(missing)}. "
                            f"Expected: {', '.join(cols)}")
            continue
        tables[name] = rows
    if problems:
        return problems

    # --- parameters
    params = {r["key"].strip(): r["value"].strip() for r in tables["06_PARAMETERS.csv"]}
    for key in ("horizon_start", "horizon_weeks"):
        if key not in params:
            problems.append(f"06_PARAMETERS.csv: no row for {key!r}")
    if "horizon_start" in params:
        try:
            datetime.date.fromisoformat(params["horizon_start"])
        except ValueError:
            problems.append(f"06_PARAMETERS.csv: horizon_start is "
                            f"{params['horizon_start']!r}; expected YYYY-MM-DD")
    if "horizon_weeks" in params:
        _int(params["horizon_weeks"], "06_PARAMETERS.csv", "horizon_weeks",
             problems, low=1)

    # --- topology
    lines = {r["line_code"] for r in tables["01_LINES.csv"]}
    station_on = {(r["station_id"], r["line_code"]) for r in tables["02_STATIONS.csv"]}
    for r in tables["02_STATIONS.csv"]:
        if r["line_code"] not in lines:
            problems.append(f"02_STATIONS.csv: station {r['station_id']} is on line "
                            f"{r['line_code']}, which is not in 01_LINES.csv")
    for r in tables["03_SECTORS.csv"]:
        for end in ("from_station_id", "to_station_id"):
            if (r[end], r["line_code"]) not in station_on:
                problems.append(f"03_SECTORS.csv: {r['sector_id']} refers to station "
                                f"{r[end]} on line {r['line_code']}, which is not in "
                                f"02_STATIONS.csv")

    locations = {r["location_id"] for r in tables["04_LOCATION_SUPPLY.csv"]}
    for r in tables["04_LOCATION_SUPPLY.csv"]:
        _int(r["supply_capacity"], f"04_LOCATION_SUPPLY.csv ({r['location_id']})",
             "supply_capacity", problems, low=0)

    # --- buffers and contracts
    natures = {r["nature_of_works"] for r in tables["05_BUFFER_LOCATION.csv"]}
    contracts = set()
    for r in tables["07_PROJECT_DETAILS.csv"]:
        cn = r["contract_number"]
        contracts.add(cn)
        if r["nature_of_activity"] not in natures:
            problems.append(f"07_PROJECT_DETAILS.csv ({cn}): nature_of_activity "
                            f"{r['nature_of_activity']!r} has no row in "
                            f"05_BUFFER_LOCATION.csv (known: {sorted(natures)})")
        if r["access_type"] not in ACCESS_TYPES:
            problems.append(f"07_PROJECT_DETAILS.csv ({cn}): access_type "
                            f"{r['access_type']!r} is not one of "
                            f"{sorted(ACCESS_TYPES)}")
        p = _int(r["contract_priority"], f"07_PROJECT_DETAILS.csv ({cn})",
                 "contract_priority", problems, low=1)
        if p is not None and p > 3:
            problems.append(f"07_PROJECT_DETAILS.csv ({cn}): contract_priority is "
                            f"{p}; expected 1, 2 or 3")
        for col in ("number_of_workfronts", "number_of_maximum_access_per_week"):
            _int(r[col], f"07_PROJECT_DETAILS.csv ({cn})", col, problems, low=1)
        for col in ("contract_award_date", "contract_completion_date",
                    "planned_completion_date"):
            try:
                datetime.date.fromisoformat(r[col].strip())
            except ValueError:
                problems.append(f"07_PROJECT_DETAILS.csv ({cn}): {col} is "
                                f"{r[col]!r}; expected YYYY-MM-DD")

    # --- activities
    ids = {r["activity_id"] for r in tables["08_ACTIVITY_DETAILS.csv"]}
    for r in tables["08_ACTIVITY_DETAILS.csv"]:
        aid = r["activity_id"]
        if r["contract_number"] not in contracts:
            problems.append(f"08_ACTIVITY_DETAILS.csv ({aid}): contract "
                            f"{r['contract_number']} is not in 07_PROJECT_DETAILS.csv")
        ends = []
        for col in ("start_location_id", "end_location_id"):
            loc = r[col]
            if loc not in locations:
                problems.append(f"08_ACTIVITY_DETAILS.csv ({aid}): {col} {loc!r} is "
                                f"not in 04_LOCATION_SUPPLY.csv")
            else:
                ends.append(loc.split(":"))
        if len(ends) == 2:
            if ends[0][1] != ends[1][1]:
                problems.append(f"08_ACTIVITY_DETAILS.csv ({aid}): the two endpoints "
                                f"are on different lines ({ends[0][1]} and "
                                f"{ends[1][1]}); an activity runs along one line")
            if ends[0][-1] != ends[1][-1]:
                problems.append(f"08_ACTIVITY_DETAILS.csv ({aid}): the two endpoints "
                                f"are on different bounds ({ends[0][-1]} and "
                                f"{ends[1][-1]}); an activity runs in one direction")
        _int(r["total_accesses"], f"08_ACTIVITY_DETAILS.csv ({aid})",
             "total_accesses", problems, low=1)
        pred = (r["predecessor_activity_id"] or "").strip()
        if pred and pred not in ids:
            problems.append(f"08_ACTIVITY_DETAILS.csv ({aid}): predecessor "
                            f"{pred!r} is not an activity in this file")
        try:
            datetime.date.fromisoformat(r["planned_start_date"].strip())
        except ValueError:
            problems.append(f"08_ACTIVITY_DETAILS.csv ({aid}): planned_start_date is "
                            f"{r['planned_start_date']!r}; expected YYYY-MM-DD")

    return problems
