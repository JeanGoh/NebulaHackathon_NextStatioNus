"""Read and write the three submission CSVs."""
from __future__ import annotations

import csv
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from .model import _d

ACCESS_COLS = ["activity_id", "access_seq", "week", "eclo", "access_night"]
OCC_COLS = ["activity_id", "week", "location_id", "co_share_group"]
RESULT_COLS = ["scenario", "contract_number", "simulated_completion_date", "overrun_days"]


@dataclass(frozen=True)
class Access:
    activity_id: str
    access_seq: int
    week: int
    eclo: bool
    access_night: int

    @property
    def work_units(self) -> float:
        return 1.5 if self.eclo else 1.0


@dataclass(frozen=True)
class Occupancy:
    activity_id: str
    week: int
    location_id: str
    co_share_group: str


@dataclass(frozen=True)
class Result:
    scenario: str
    contract_number: str
    simulated_completion_date: date
    overrun_days: int


@dataclass
class Submission:
    accesses: list[Access] = field(default_factory=list)
    occupancies: list[Occupancy] = field(default_factory=list)
    results: list[Result] = field(default_factory=list)

    @property
    def scenario(self) -> str:
        scenarios = {r.scenario for r in self.results}
        if len(scenarios) != 1:
            raise ValueError(f"RESULTS.csv must hold exactly one scenario, found {scenarios}")
        return scenarios.pop()


def _rows(p: Path) -> list[dict[str, str]]:
    with p.open(newline="", encoding="utf-8-sig") as fh:
        return [r for r in csv.DictReader(fh) if any(v.strip() for v in r.values() if v)]


def load_submission(d: str | Path) -> Submission:
    p = Path(d)
    return Submission(
        accesses=[
            Access(r["activity_id"], int(r["access_seq"]), int(r["week"]),
                   r["eclo"].strip() == "1", int(r["access_night"]))
            for r in _rows(p / "SCHEDULE_ACCESS.csv")
        ],
        occupancies=[
            Occupancy(r["activity_id"], int(r["week"]), r["location_id"], r["co_share_group"])
            for r in _rows(p / "SCHEDULE_OCCUPANCY.csv")
        ],
        results=[
            Result(r["scenario"].strip(), r["contract_number"],
                   _d(r["simulated_completion_date"]), int(r["overrun_days"]))
            for r in _rows(p / "RESULTS.csv")
        ],
    )


def save_submission(sub: Submission, d: str | Path) -> None:
    p = Path(d)
    p.mkdir(parents=True, exist_ok=True)

    with (p / "SCHEDULE_ACCESS.csv").open("w", newline="") as fh:
        w = csv.writer(fh); w.writerow(ACCESS_COLS)
        for a in sorted(sub.accesses, key=lambda a: (a.activity_id, a.access_seq)):
            w.writerow([a.activity_id, a.access_seq, a.week, int(a.eclo), a.access_night])

    with (p / "SCHEDULE_OCCUPANCY.csv").open("w", newline="") as fh:
        w = csv.writer(fh); w.writerow(OCC_COLS)
        for o in sorted(sub.occupancies, key=lambda o: (o.activity_id, o.week, o.location_id)):
            w.writerow([o.activity_id, o.week, o.location_id, o.co_share_group])

    with (p / "RESULTS.csv").open("w", newline="") as fh:
        w = csv.writer(fh); w.writerow(RESULT_COLS)
        for r in sorted(sub.results, key=lambda r: r.contract_number):
            w.writerow([r.scenario, r.contract_number,
                        r.simulated_completion_date.isoformat(), r.overrun_days])
