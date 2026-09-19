"""Instance data model and loaders for the 8 PS1 CSVs."""
from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path


def _d(s: str) -> date:
    return datetime.strptime(s.strip(), "%Y-%m-%d").date()


@dataclass(frozen=True)
class Station:
    station_id: str
    line_code: str
    seq: int
    is_interchange: bool


@dataclass(frozen=True)
class Sector:
    sector_id: str
    line_code: str
    from_station_id: str
    to_station_id: str
    seq: int
    is_shared: bool


@dataclass(frozen=True)
class Location:
    location_id: str
    location_kind: str
    line_code: str
    bound: str
    supply_capacity: int


@dataclass(frozen=True)
class BufferRule:
    nature_of_works: str
    up_to_buffer_sectors: int
    opposite_bound_required: bool


@dataclass(frozen=True)
class Contract:
    contract_number: str
    contract_description: str
    contract_award_date: date
    activity_type: str
    nature_of_activity: str
    contract_priority: int
    contract_completion_date: date
    planned_completion_date: date
    number_of_workfronts: int
    access_type: str
    max_access_per_week: int


@dataclass(frozen=True)
class Activity:
    activity_id: str
    contract_number: str
    activity_type: str
    start_location_id: str
    end_location_id: str
    total_accesses: int
    planned_start_date: date
    predecessor_activity_id: str | None
    activity_priority: int


@dataclass
class Instance:
    horizon_start: date
    horizon_weeks: int
    lines: dict[str, str]
    stations: list[Station]
    sectors: list[Sector]
    locations: dict[str, Location]
    buffers: dict[str, BufferRule]
    contracts: dict[str, Contract]
    activities: dict[str, Activity]

    # --- week arithmetic (see docs/SPEC.md section 2) ---
    def week_start(self, w: int) -> date:
        return self.horizon_start + timedelta(days=7 * (w - 1))

    def week_end(self, w: int) -> date:
        return self.horizon_start + timedelta(days=7 * (w - 1) + 6)

    def week_of(self, d: date) -> int:
        return (d - self.horizon_start).days // 7 + 1

    @property
    def weeks(self) -> range:
        return range(1, self.horizon_weeks + 1)

    def buffer_for(self, contract_number: str) -> BufferRule:
        nature = self.contracts[contract_number].nature_of_activity
        try:
            return self.buffers[nature]
        except KeyError:
            raise KeyError(
                f"{contract_number} has nature of activity {nature!r}, which has "
                f"no row in 05_BUFFER_LOCATION.csv. Known: "
                f"{sorted(self.buffers)}. Add a row for it (0,0 means no buffer)."
            ) from None


def _rows(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8-sig") as fh:
        return [r for r in csv.DictReader(fh) if any(v.strip() for v in r.values() if v)]


def load_instance(data_dir: str | Path) -> Instance:
    """Load an instance from a directory containing the 8 numbered CSVs."""
    p = Path(data_dir)

    params = {r["key"]: r["value"] for r in _rows(p / "06_PARAMETERS.csv")}

    lines = {r["line_code"]: r["line_name"] for r in _rows(p / "01_LINES.csv")}

    stations = [
        Station(r["station_id"], r["line_code"], int(r["seq"]), r["is_interchange"] == "1")
        for r in _rows(p / "02_STATIONS.csv")
    ]

    sectors = [
        Sector(
            r["sector_id"], r["line_code"], r["from_station_id"],
            r["to_station_id"], int(r["seq"]), r["is_shared"] == "1",
        )
        for r in _rows(p / "03_SECTORS.csv")
    ]

    locations = {
        r["location_id"]: Location(
            r["location_id"], r["location_kind"], r["line_code"],
            r["bound"], int(r["supply_capacity"]),
        )
        for r in _rows(p / "04_LOCATION_SUPPLY.csv")
    }

    buffers = {
        r["nature_of_works"]: BufferRule(
            r["nature_of_works"], int(r["up_to_buffer_sectors"]),
            r["opposite_bound_required"] == "1",
        )
        for r in _rows(p / "05_BUFFER_LOCATION.csv")
    }

    contracts = {
        r["contract_number"]: Contract(
            r["contract_number"], r["contract_description"], _d(r["contract_award_date"]),
            r["activity_type"], r["nature_of_activity"], int(r["contract_priority"]),
            _d(r["contract_completion_date"]), _d(r["planned_completion_date"]),
            int(r["number_of_workfronts"]), r["access_type"],
            int(r["number_of_maximum_access_per_week"]),
        )
        for r in _rows(p / "07_PROJECT_DETAILS.csv")
    }

    activities = {
        r["activity_id"]: Activity(
            r["activity_id"], r["contract_number"], r["activity_type"],
            r["start_location_id"], r["end_location_id"], int(r["total_accesses"]),
            _d(r["planned_start_date"]),
            r["predecessor_activity_id"].strip() or None,
            int(r["activity_priority"]),
        )
        for r in _rows(p / "08_ACTIVITY_DETAILS.csv")
    }

    return Instance(
        horizon_start=_d(params["horizon_start"]),
        horizon_weeks=int(params["horizon_weeks"]),
        lines=lines, stations=stations, sectors=sectors, locations=locations,
        buffers=buffers, contracts=contracts, activities=activities,
    )
