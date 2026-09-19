"""Network topology: parsing location IDs and expanding an activity's path.

An activity runs start_location_id -> end_location_id and books EVERY tunnel
sector and platform sector along the way, inclusive of both end stations.
n tunnel sectors => n+1 platforms.  See docs/SPEC.md section 3.
"""
from __future__ import annotations

from dataclasses import dataclass

from .model import Instance


@dataclass(frozen=True)
class ParsedLocation:
    kind: str           # "SEC" | "PLAT"
    line: str
    bound: str
    sector_id: str | None = None      # "SEC:ALP:S01_S02" (no bound)
    station_id: str | None = None     # for PLAT


def parse_location(location_id: str) -> ParsedLocation:
    parts = location_id.split(":")
    if parts[0] == "SEC":
        _, line, span, bound = parts
        return ParsedLocation("SEC", line, bound, sector_id=f"SEC:{line}:{span}")
    if parts[0] == "PLAT":
        _, line, stn, bound = parts
        return ParsedLocation("PLAT", line, bound, station_id=stn)
    raise ValueError(f"unrecognised location id: {location_id}")


def platform_id(line: str, station: str, bound: str) -> str:
    return f"PLAT:{line}:{station}:{bound}"


def sector_location_id(sector_id: str, bound: str) -> str:
    return f"{sector_id}:{bound}"


class Network:
    """Indexed view of the topology, built once per instance."""

    def __init__(self, inst: Instance):
        self.inst = inst
        self.sector_by_id = {s.sector_id: s for s in inst.sectors}
        # per line, sectors in running order
        self.line_sectors: dict[str, list] = {}
        for s in sorted(inst.sectors, key=lambda s: s.seq):
            self.line_sectors.setdefault(s.line_code, []).append(s)
        # position of a sector within its own line, 0-based
        self.pos_in_line = {
            s.sector_id: i
            for line in self.line_sectors
            for i, s in enumerate(self.line_sectors[line])
        }

    # --- path expansion -------------------------------------------------
    def expand(self, activity_id: str) -> list[str]:
        """Every location_id this activity books, sorted for stable output."""
        act = self.inst.activities[activity_id]
        a, b = parse_location(act.start_location_id), parse_location(act.end_location_id)

        if a.line != b.line:
            raise ValueError(f"{activity_id}: endpoints span two lines")
        if a.bound != b.bound:
            raise ValueError(f"{activity_id}: endpoints span two bounds")
        line, bound = a.line, a.bound

        if a.kind == "SEC" and b.kind == "SEC":
            i, j = self.pos_in_line[a.sector_id], self.pos_in_line[b.sector_id]
            lo, hi = min(i, j), max(i, j)
            span = self.line_sectors[line][lo : hi + 1]
            stations = [span[0].from_station_id] + [s.to_station_id for s in span]
            locs = [sector_location_id(s.sector_id, bound) for s in span]
            locs += [platform_id(line, st, bound) for st in stations]
        elif a.kind == "PLAT" and b.kind == "PLAT":
            # station-to-station: sectors strictly between them, platforms inclusive
            order = self._station_order(line)
            i, j = order.index(a.station_id), order.index(b.station_id)
            lo, hi = min(i, j), max(i, j)
            stations = order[lo : hi + 1]
            locs = [platform_id(line, st, bound) for st in stations]
            locs += [
                sector_location_id(s.sector_id, bound)
                for s in self.line_sectors[line][lo:hi]
            ]
        else:
            raise NotImplementedError(
                f"{activity_id}: mixed SEC/PLAT endpoints not seen in data"
            )

        unknown = [l for l in locs if l not in self.inst.locations]
        if unknown:
            raise ValueError(f"{activity_id}: expanded to unknown locations {unknown}")
        return sorted(set(locs))

    def _station_order(self, line: str) -> list[str]:
        secs = self.line_sectors[line]
        return [secs[0].from_station_id] + [s.to_station_id for s in secs]

    # --- buffers --------------------------------------------------------
    @property
    def _bounds(self) -> list[str]:
        out: list[str] = []
        for loc in self.inst.locations.values():
            if loc.bound not in out:
                out.append(loc.bound)
        return sorted(out)

    def _interchange_spans(self, locs) -> set[tuple[str, str]]:
        """Sectors in `locs` that run between two interchange stations."""
        hubs = {st.station_id for st in self.inst.stations if st.is_interchange}
        found = set()
        for loc in locs:
            if not loc.startswith("SEC:"):
                continue
            sec = self.sector_by_id.get(parse_location(loc).sector_id)
            if sec and sec.from_station_id in hubs and sec.to_station_id in hubs:
                found.add((sec.from_station_id, sec.to_station_id))
        return found

    def buffer_locations(self, activity_id: str, occupied: list[str]) -> list[str]:
        """Exclusion-zone locations projected by this activity's possession.

        Live (2 sectors each side) and Non-live (Consist) (1) project a buffer.
        Live also mirrors the whole closure onto the opposite bound, and at the
        interchange crosses onto the other lines' tunnel between the same two
        interchange stations, and those platforms.
        """
        act = self.inst.activities[activity_id]
        rule = self.inst.buffer_for(act.contract_number)
        if rule.up_to_buffer_sectors == 0 and not rule.opposite_bound_required:
            return []

        out: set[str] = set()
        n = rule.up_to_buffer_sectors
        sec_locs = [l for l in occupied if l.startswith("SEC:")]

        if n:
            for loc in sec_locs:
                p = parse_location(loc)
                line, bound = p.line, p.bound
                idx = self.pos_in_line[p.sector_id]
                run = self.line_sectors[line]
                for k in range(max(0, idx - n), min(len(run), idx + n + 1)):
                    s = run[k]
                    out.add(sector_location_id(s.sector_id, bound))
                    out.add(platform_id(line, s.from_station_id, bound))
                    out.add(platform_id(line, s.to_station_id, bound))

        base = set(occupied) | out

        if rule.opposite_bound_required:  # Live mirrors onto the opposite bound
            for loc in list(base):
                base.add(_flip_bound(loc))
            # and crosses lines at the interchange tunnel. The sample calls
            # that tunnel H01_H02; find it from the data instead, so the rule
            # still fires on a network whose interchanges are named otherwise.
            for span in self._interchange_spans(base):
                a, b_ = span
                for other in self.inst.lines:
                    for bd in self._bounds:
                        base.add(f"SEC:{other}:{a}_{b_}:{bd}")
                        base.add(platform_id(other, a, bd))
                        base.add(platform_id(other, b_, bd))

        base -= set(occupied)
        return sorted(l for l in base if l in self.inst.locations)


def _flip_bound(location_id: str) -> str:
    if location_id.endswith(":EB"):
        return location_id[:-3] + ":WB"
    if location_id.endswith(":WB"):
        return location_id[:-3] + ":EB"
    return location_id
