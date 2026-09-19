"""Isometric 3-D map of the network, one frame per week.

The dataset carries no geography: two lines of ten stations each, meeting at
the shared interchanges H01 and H02.  So this is a schematic drawn in
isometric projection, not a geographic map.  Workers read it the way they
read a line diagram -- which stretch of track is booked this week, who is on
it, and where something is running past its deadline.

Every figure shown comes from the same submission the rest of the app reads,
so the map cannot drift out of step with the schedule.
"""
from __future__ import annotations

import collections
import json

from .model import Instance
from .submission import Submission
from .trackspace_view import schedule_summary
from . import theme

# ---------------------------------------------------------------- projection
UX, UY = 66.0, 25.0          # half-width / half-height of one grid step
DECK_Z1 = 13.0               # thickness of a track deck
PLAT_Z1 = 33.0               # station platforms stand taller than the deck
PILLAR_Z0 = -40.0            # columns run down to the ground plane
LANE_HW = 0.31               # half-width of a lane, in grid units
PLAT_HU = 0.26               # half-length of a station platform
GAP = 0.03                   # gap between a platform and the next sector

# Lanes are derived from the instance, never hard-coded: any number of lines,
# whatever they are called, and whatever bounds they run.  Larger v draws
# nearer the viewer.
LANE_GAP = 0.95              # between the two tracks of one line
LINE_GAP = 1.85              # between one line and the next
BOUND_ORDER = {"WB": 0, "EB": 1}
BOUND_WORD = {"WB": "westbound", "EB": "eastbound"}


def lanes_for(inst: Instance) -> dict[tuple[str, str], float]:
    """Give every (line, bound) in the data its own lane."""
    bounds_of: dict[str, list[str]] = {}
    for loc in inst.locations.values():
        bounds_of.setdefault(loc.line_code, [])
        if loc.bound not in bounds_of[loc.line_code]:
            bounds_of[loc.line_code].append(loc.bound)

    order = [ln for ln in inst.lines if ln in bounds_of]
    order += [ln for ln in sorted(bounds_of) if ln not in order]

    out, v = {}, 0.0
    for line in order:
        bs = sorted(bounds_of[line], key=lambda b: (BOUND_ORDER.get(b, 9), b))
        for b in bs:
            out[(line, b)] = v
            v += LANE_GAP
        v += LINE_GAP - LANE_GAP
    return out

VERSION = 10                 # bump when the drawing changes, to bust caches
FREE = "#dbe4ee"             # track with nothing booked on it
PAL = {1: "#2a78d6", 2: "#eb6834", 3: "#1baf7a"}
HUB = "#6b62c9"              # H01 / H02, the shared interchanges
ALERT = "#e02424"        # late, and something can still be done
LOCKED = "#4a5463"       # late, and nothing in the schedule fixes it
FULL = "#f5a623"


def _pt(u: float, v: float, z: float) -> tuple[float, float]:
    return ((u - v) * UX, (u + v) * UY - z)


# ---------------------------------------------------------------- geometry
def _solids(inst: Instance) -> list[dict]:
    """Every drawable box, with the location it stands for."""
    out: list[dict] = []
    by_line: dict[str, list] = collections.defaultdict(list)
    for s in sorted(inst.stations, key=lambda s: s.seq):
        by_line[s.line_code].append(s)
    sec_by_line: dict[str, list] = collections.defaultdict(list)
    for s in sorted(inst.sectors, key=lambda s: s.seq):
        sec_by_line[s.line_code].append(s)

    for (line, bound), v in lanes_for(inst).items():
        stations = by_line.get(line, [])
        if not stations:
            continue
        idx = {s.station_id: i for i, s in enumerate(stations)}

        for i, st in enumerate(stations):
            loc = f"PLAT:{line}:{st.station_id}:{bound}"
            if loc not in inst.locations:
                continue
            out.append(dict(
                kind="plat", loc=loc, hub=bool(st.is_interchange),
                u0=i - PLAT_HU, u1=i + PLAT_HU,
                v0=v - LANE_HW, v1=v + LANE_HW, z0=0.0, z1=PLAT_Z1,
                station=st.station_id, line=line, bound=bound, seat=i))
            out.append(dict(
                kind="pillar", loc=None, hub=False,
                u0=i - 0.085, u1=i + 0.085, v0=v - 0.085, v1=v + 0.085,
                z0=PILLAR_Z0, z1=0.0, station=st.station_id,
                line=line, bound=bound, seat=i))

        for sec in sec_by_line[line]:
            i = idx.get(sec.from_station_id)
            j = idx.get(sec.to_station_id)
            if i is None or j is None:
                continue
            a, b = min(i, j), max(i, j)
            loc = f"{sec.sector_id}:{bound}"
            if loc not in inst.locations:
                continue
            out.append(dict(
                kind="deck", loc=loc, hub=False,
                u0=a + PLAT_HU + GAP, u1=b - PLAT_HU - GAP,
                v0=v - LANE_HW + 0.06, v1=v + LANE_HW - 0.06,
                z0=0.0, z1=DECK_Z1, station=None,
                line=line, bound=bound, seat=a))
    return out


def _faces(s: dict) -> dict[str, str]:
    """Top, left and right faces of one box, as SVG point strings."""
    u0, u1, v0, v1, z0, z1 = s["u0"], s["u1"], s["v0"], s["v1"], s["z0"], s["z1"]

    def poly(pts):
        return " ".join(f"{x:.1f},{y:.1f}" for x, y in pts)

    top = poly([_pt(u0, v0, z1), _pt(u1, v0, z1),
                _pt(u1, v1, z1), _pt(u0, v1, z1)])
    # the +v face, falling away to the lower left
    left = poly([_pt(u0, v1, z1), _pt(u1, v1, z1),
                 _pt(u1, v1, z0), _pt(u0, v1, z0)])
    # the +u face, falling away to the lower right
    right = poly([_pt(u1, v0, z1), _pt(u1, v1, z1),
                  _pt(u1, v1, z0), _pt(u1, v0, z0)])
    return {"top": top, "left": left, "right": right}


# ---------------------------------------------------------------- week state
def week_states(inst: Instance, sub: Submission,
                late_kind: dict[str, str] | None = None) -> dict[int, dict]:
    """For every week, what each booked location looks like.

    Per location:  [priority, teams, possessions, capacity, flags, tip, alert]
    flags: 1 = at its weekly limit, 2 = over it,
           4 = past a deadline and something could still be done about it,
           8 = past a deadline and nothing in the schedule fixes it.

    `late_kind` maps an activity to "act" or "stuck", exactly as the decisions
    panel splits them, so the map and that panel cannot tell different stories.
    Without it every overrun is drawn as actionable.
    """
    late_kind = late_kind or {}
    deadline = {cn: c.planned_completion_date for cn, c in inst.contracts.items()}

    groups: dict[tuple, set] = collections.defaultdict(set)
    members: dict[tuple, set] = collections.defaultdict(set)
    for o in sub.occupancies:
        groups[(o.location_id, o.week)].add(o.co_share_group)
        members[(o.location_id, o.week)].add(o.activity_id)

    # weeks an activity actually takes access, to judge "past its deadline"
    access_weeks = collections.defaultdict(set)
    eclo_weeks = set()
    for a in sub.accesses:
        access_weeks[a.activity_id].add(a.week)
        if a.eclo:
            eclo_weeks.add((a.activity_id, a.week))

    out: dict[int, dict] = {}
    for (loc, wk), aids in members.items():
        if loc not in inst.locations:
            continue
        cap = inst.locations[loc].supply_capacity
        ngroups = len(groups[(loc, wk)])

        crews, prio = [], 9
        act_bits, stuck_bits = [], []
        for aid in sorted(aids):
            act = inst.activities[aid]
            c = inst.contracts[act.contract_number]
            prio = min(prio, c.contract_priority)
            crews.append(c.contract_description)
            due = deadline.get(act.contract_number)
            if due is not None and inst.week_end(wk) > due and wk in access_weeks.get(aid, ()):
                days = (inst.week_end(wk) - due).days
                if late_kind.get(aid, "act") == "stuck":
                    stuck_bits.append(f"{c.contract_description} cannot finish on time "
                                      f"whatever is done — {days} days over")
                else:
                    act_bits.append(f"{c.contract_description} is working {days} days "
                                    f"past its deadline in this plan")

        flags = 0
        if ngroups >= cap:
            flags |= 1
        if ngroups > cap:
            flags |= 2
        if act_bits:
            flags |= 4
        if stuck_bits:
            flags |= 8
        if any((aid, wk) in eclo_weeks for aid in aids):
            flags |= 32               # bought with an early closure / late opening

        alert = ""
        if flags & 32 and not (flags & 14):
            n = sum(1 for aid in aids if (aid, wk) in eclo_weeks)
            alert = (f"{n} ECLO activity-access(es) cover this worksite this week; "
                     "each access supplies 1.5 work units, not an extra night")
        if flags & 2:
            alert = (f"Extra access-night bought here — {ngroups} possessions "
                     f"where there is room for {cap}")
        elif act_bits:
            alert = act_bits[0]
        elif stuck_bits:
            alert = stuck_bits[0]

        who = ", ".join(sorted(set(crews)))
        tip = (f"{who} — {len(aids)} team(s), {ngroups} of {cap} possession(s)")
        out.setdefault(wk, {})[loc] = [prio, len(aids), ngroups, cap,
                                       flags, tip, alert]
    schedule_end = (max((a.week for a in sub.accesses), default=inst.horizon_weeks)
                    if sub is not None and sub.accesses else inst.horizon_weeks)
    for wk in range(1, schedule_end + 1):
        out.setdefault(wk, {})
    return out


def conflict_states(inst: Instance, conflicts) -> dict[int, dict]:
    """The contested-track view, before any schedule exists.

    One row per flagged worksite-week, so what the map draws and what the
    tiles count are the same set. Red (bit 16) identifies a rule issue;
    amber (bit 64) identifies a sharing requirement without a local red issue.

    Same row shape as week_states so the renderer, the flags and the scrubber
    do not need to know which view they are drawing:
        [priority, parties, wanted, capacity, flags, tip, alert]
    """
    out: dict[int, dict] = {}
    cells = collections.defaultdict(list)
    for c in conflicts:
        if c.where in inst.locations and c.week:
            cells[c.week, c.where].append(c)
    for (week, loc), findings in cells.items():
        # Multiple rules may flag a cell. Never let an amber sharing finding
        # overwrite a red closure/capacity failure at the same location-week.
        hard_findings = [c for c in findings if c.severity == "blocking"]
        parties = {a for c in findings for a in c.parties}
        contracts = {cn for c in findings for cn in c.contracts}
        priority = min((inst.contracts[cn].contract_priority for cn in contracts
                        if cn in inst.contracts), default=3)
        cap = inst.locations[loc].supply_capacity
        need = max((c.need for c in findings), default=0)
        flags = 16 if hard_findings else 64
        if need >= cap and need:
            flags |= 1
        details = " · ".join(dict.fromkeys(c.detail for c in findings))
        out.setdefault(week, {})[loc] = [priority, len(parties), need, cap,
                                        flags, details, details]
    for wk in range(1, inst.horizon_weeks + 1):
        out.setdefault(wk, {})
    return out




def payload(inst: Instance, sub: Submission,
            late_kind: dict[str, str] | None = None,
            conflicts=None) -> dict:
    solids = _solids(inst)

    anchors, tiles = {}, []
    xs, ys = [], []
    for s in solids:
        f = _faces(s)
        for uu in (s["u0"], s["u1"]):
            for vv in (s["v0"], s["v1"]):
                for zz in (s["z0"], s["z1"]):
                    x, y = _pt(uu, vv, zz)
                    xs.append(x)
                    ys.append(y)
        if s["kind"] == "pillar":
            tiles.append(dict(loc=None, kind="pillar", hub=False,
                              depth=s["u0"] + s["v0"], **f))
            continue
        um = (s["u0"] + s["u1"]) / 2
        vm = (s["v0"] + s["v1"]) / 2
        ax, ay = _pt(um, vm, s["z1"])
        anchors[s["loc"]] = [round(ax, 1), round(ay, 1)]
        tiles.append(dict(loc=s["loc"], kind=s["kind"], hub=s["hub"],
                          depth=um + vm, **f))
    tiles.sort(key=lambda t: t["depth"])

    by_line = collections.defaultdict(list)
    for st in sorted(inst.stations, key=lambda s: s.seq):
        by_line[st.line_code].append(st)

    LANES = lanes_for(inst)
    lanes_of: dict[str, list[float]] = {}
    for (line, _b), v in LANES.items():
        lanes_of.setdefault(line, []).append(v)

    labels = []
    for line, vs in lanes_of.items():
        v = min(vs) - 0.72          # in the gap just outside this line's tracks
        for i, st in enumerate(by_line.get(line, [])):
            x, y = _pt(i, v, 0)
            labels.append(dict(x=round(x, 1), y=round(y + 5, 1), t=st.station_id,
                               a="middle", hub=bool(st.is_interchange)))
        lx, ly = _pt(-1.5, (min(vs) + max(vs)) / 2, 0)
        labels.append(dict(x=round(lx, 1), y=round(ly + 6, 1),
                           t=inst.lines.get(line, line), a="end", big=True))

    lane_tags = []
    for (line, bound), v in LANES.items():
        if line not in lanes_of:
            continue
        x, y = _pt(-0.72, v, DECK_Z1)
        lane_tags.append(dict(x=round(x, 1), y=round(y + 4, 1),
                              t=BOUND_WORD.get(bound, bound), a="end"))

    # A station that carries the same id on more than one line is an
    # interchange; link the two lines' nearest tracks wherever that happens.
    on_lines: dict[str, list[str]] = {}
    for st in inst.stations:
        if st.is_interchange:
            on_lines.setdefault(st.station_id, [])
            if st.line_code not in on_lines[st.station_id]:
                on_lines[st.station_id].append(st.line_code)

    links = []
    for sid, lns in on_lines.items():
        lns = [l for l in sorted(lns, key=lambda l: min(lanes_of.get(l, [1e9])))
               if l in lanes_of]
        for upper, lower in zip(lns, lns[1:]):
            a = b = None
            for (l, bd), v in LANES.items():
                if l == upper and v == max(lanes_of[upper]):
                    a = anchors.get(f"PLAT:{l}:{sid}:{bd}")
                if l == lower and v == min(lanes_of[lower]):
                    b = anchors.get(f"PLAT:{l}:{sid}:{bd}")
            if a and b:
                links.append(dict(x1=a[0], y1=a[1], x2=b[0], y2=b[1], t=sid))

    # the view has to cover the text too, not just the structure
    for L in labels + lane_tags:
        w = len(L["t"]) * (11.0 if L.get("big") else 7.2)
        a = L.get("a", "middle")
        x0 = L["x"] - (w if a == "end" else w / 2 if a == "middle" else 0)
        x1 = L["x"] + (w if a == "start" else w / 2 if a == "middle" else 0)
        xs += [x0, x1]
        ys += [L["y"] - 16, L["y"] + 6]

    minx, maxx = min(xs) - 26, max(xs) + 26
    miny, maxy = min(ys) - 132, max(ys) + 40

    if conflicts is not None:
        weeks = conflict_states(inst, conflicts)
    else:
        weeks = week_states(inst, sub, late_kind)

    # Everything that will ever raise a flag, so the map can show trouble
    # standing on the network before anyone touches the scrubber.
    alert_weeks, alert_locs, summary = [], {}, {}
    for w in sorted(weeks):
        hit = [loc for loc, v in weeks[w].items() if v[4] & 126]
        if not hit:
            continue
        alert_weeks.append(w)
        for loc in hit:
            alert_locs.setdefault(loc, []).append(w)
            msg = weeks[w][loc][6]
            fl = weeks[w][loc][4]
            if msg and conflicts is None and (fl & 34) and not (fl & 12):
                # an early closure is a cost the plan chose, not a late finish
                who = (weeks[w][loc][5] or "").split(" \u2014 ")[0] or "This plan"
                e = summary.setdefault(who, {"who": who, "weeks": [], "worst": 0,
                                             "kind": "eclo"})
                if w not in e["weeks"]:
                    e["weeks"].append(w)
                e["worst"] += 1
            elif msg and conflicts is None:
                who = msg.split(" is working ")[0].split(" cannot finish")[0]
                kind = "stuck" if (weeks[w][loc][4] & 8) and not (
                    weeks[w][loc][4] & 6) else "act"
                e = summary.setdefault(who, {"who": who, "weeks": [], "worst": 0,
                                             "kind": kind})
                if w not in e["weeks"]:
                    e["weeks"].append(w)
                for marker in ("working ", "— "):
                    if marker in msg:
                        try:
                            e["worst"] = max(e["worst"],
                                             int(msg.split(marker)[1].split(" days")[0]))
                        except (IndexError, ValueError):
                            pass
                        break

    schedule_end = (max((a.week for a in sub.accesses), default=inst.horizon_weeks)
                    if sub is not None and sub.accesses else inst.horizon_weeks)
    if conflicts is not None:
        # One entry per contract that is fighting for track, worst = how many
        # stretches it is contesting. The optimiser is what settles these.
        per = {}
        contract_cells = collections.defaultdict(dict)
        for c in conflicts:
            loc = getattr(c, "where", "")
            if not loc or loc not in inst.locations or not c.week:
                continue
            hard = getattr(c, "severity", "blocking") == "blocking"
            for cn in c.contracts:
                if cn not in inst.contracts:
                    continue
                cell = (c.week, loc)
                contract_cells[cn][cell] = contract_cells[cn].get(cell, False) or hard
        for cn, cells in contract_cells.items():
            for (week, loc), hard in cells.items():
                who = inst.contracts[cn].contract_description
                e = per.setdefault(who, {"who": who, "weeks": [], "worst": 0,
                                         "hard": 0, "share": 0, "kind": "share",
                                         "hardWeeks": [], "shareWeeks": []})
                if week not in e["weeks"]:
                    e["weeks"].append(week)
                e["worst"] += 1
                e["hard" if hard else "share"] += 1
                type_weeks = e["hardWeeks" if hard else "shareWeeks"]
                if week not in type_weeks:
                    type_weeks.append(week)
                if hard:
                    e["kind"] = "hard"
        for e in per.values():
            e["weeks"].sort()
            e["hardWeeks"].sort()
            e["shareWeeks"].sort()
        summary = per

    dates = {w: (f"{inst.week_start(w):%d %b}", f"{inst.week_end(w):%d %b %Y}")
             for w in range(1, schedule_end + 1)}
    located_conflicts = []
    if conflicts is not None:
        located_conflicts = [c for c in conflicts
                             if getattr(c, "where", "") in inst.locations and c.week]

    return dict(view=[round(minx), round(miny), round(maxx - minx),
                      round(maxy - miny)],
                tiles=tiles, labels=labels, lanes=lane_tags, links=links,
                anchors=anchors, weeks=weeks, dates=dates,
                mode="conflicts" if conflicts is not None else "schedule",
                scheduleSummary=schedule_summary(inst, sub) if sub is not None else None,
                conflictFlagCount=len(conflicts) if conflicts is not None else 0,
                mappedConflictFlagCount=len(located_conflicts),
                unmappedConflictFlagCount=(len(conflicts) - len(located_conflicts))
                if conflicts is not None else 0,
                alertWeeks=alert_weeks, alertLocs=alert_locs,
                alertSummary=sorted(summary.values(), key=lambda e: -e["worst"]),
                horizon=schedule_end)


# ---------------------------------------------------------------- rendering
_SHELL = """
<style>
 :root { --ink:#0b0b0b; --muted:#52514e; --line:#e6e5e1; --alert:#e02424; }
 *{box-sizing:border-box}
 #wrap{font-family:"Source Sans Pro",-apple-system,BlinkMacSystemFont,sans-serif;
       color:var(--ink);background:#f6f9fc;border:1px solid var(--line);
       border-radius:12px;padding:12px 14px 6px}
 #banner{display:flex;align-items:center;gap:10px;flex-wrap:wrap;
         border-radius:10px;padding:10px 13px;margin-bottom:11px;font-size:14px}
 #banner.bad{background:#fff0f0;border:1.5px solid #f3b7b7;
             box-shadow:0 0 0 4px rgba(224,36,36,.07)}
 #banner .row{display:flex;align-items:center;gap:9px;flex-wrap:wrap;width:100%}
 #banner .row+.row{margin-top:8px;padding-top:9px;border-top:1px solid #f0d3d3}
 #banner .hd.lock{color:#3c4653}
 .chip.lock{border-color:#c2c9d2;color:#3c4653}
 .chip.lock:hover{background:#4a5463;border-color:#4a5463;color:#fff}
 .tick.lock{background:#4a5463}
 #banner.ok{background:#eefaf1;border:1.5px solid #bfe6cc}
 #banner.share{background:#fff0f0;border:1.5px solid #e08c1a}
 #banner .hd.share{color:#a86410}
 .chip.share{border-color:#e08c1a;color:#a86410}
 .chip.share:hover{background:#e08c1a;border-color:#e08c1a;color:#fdfdfd}
 .tick.share{background:#e08c1a}
 #banner .hd{font-weight:800;color:var(--alert);letter-spacing:.01em}
 #banner.ok .hd{color:#0a8a35}
 .chip{border:1.5px solid #e6a5a5;background:#fdfdfd;color:#a01818;border-radius:999px;
       padding:5px 12px;font-size:13px;font-weight:650;cursor:pointer}
 .chip:hover{background:var(--alert);border-color:var(--alert);color:#fff}
 .bar{display:flex;align-items:center;gap:14px;flex-wrap:wrap;margin-bottom:6px}
 .key{display:flex;align-items:center;gap:6px;font-size:12.5px;color:var(--muted)}
 .sw{width:13px;height:13px;border-radius:3px;display:inline-block}
 button{font:inherit;font-size:14px;font-weight:600;padding:7px 16px;border-radius:8px;
        border:0;background:#2a78d6;color:#fff;cursor:pointer}
 button:hover{background:#1f63b5}
 .track{position:relative;flex:1;min-width:200px}
 .track input{width:100%;accent-color:#2a78d6;height:22px;margin:0;display:block}
 .ticks{position:absolute;left:0;right:0;top:-9px;height:9px;pointer-events:none}
 .tick{position:absolute;width:3px;height:9px;background:var(--alert);border-radius:2px;
       transform:translateX(-1.5px);box-shadow:0 0 0 1.5px #fdfdfd}
 .wk{font-size:15px;font-weight:600;white-space:nowrap}
 .dt{font-size:12.5px;color:var(--muted);white-space:nowrap}
 .note{font-size:12.5px;color:var(--muted);margin:2px 0 8px}
 .alertbar{font-size:13.5px;font-weight:700;color:var(--alert);min-height:20px;margin:2px 0 4px}
 svg{width:100%;height:auto;display:block}
 .bob{animation:bob 2.4s ease-in-out infinite}
 @keyframes bob{0%,100%{transform:translateY(0)}50%{transform:translateY(-9px)}}
 .ring{animation:ring 1.8s ease-out infinite;
        transform-box:fill-box;transform-origin:center}
 @keyframes ring{0%{transform:scale(.45);opacity:.55}100%{transform:scale(2.1);opacity:0}}
 .gring{animation:gring 1.8s ease-out infinite;
         transform-box:fill-box;transform-origin:center}
 @keyframes gring{0%{transform:scale(.3);opacity:.6}100%{transform:scale(1.6);opacity:0}}
 #tip{position:fixed;pointer-events:none;background:#1a1a1a;color:#fefefe;font-size:12.5px;
      padding:6px 9px;border-radius:6px;opacity:0;transition:opacity .12s;max-width:300px;
      z-index:9}
</style>
<div id="wrap">
  <div id="banner"></div>
  <div class="bar">
    <button id="play">&#9654;&nbsp; Play</button>
    <span class="track"><span class="ticks" id="ticks"></span>
      <input type="range" id="wk" min="1" max="__HORIZON__" value="1" step="1"></span>
    <span class="wk" id="wklab">Week 1</span><span class="dt" id="dtlab"></span>
  </div>
  <div class="bar" id="legend" style="gap:16px">
    <span class="key"><i class="sw" style="background:#2a78d6"></i>P1 critical</span>
    <span class="key"><i class="sw" style="background:#eb6834"></i>P2 important</span>
    <span class="key"><i class="sw" style="background:#1baf7a"></i>P3 routine</span>
    <span class="key"><i class="sw" style="background:#dbe4ee"></i>no work booked</span>
    <span class="key"><i class="sw" style="background:#fdfdfd;border:2.5px solid #f5a623"></i>at nominal capacity</span>
    <span class="key"><i class="sw" style="background:#e02424;border-radius:50%"></i>red clock = scheduled past deadline</span>
    <span class="key"><i class="sw" style="background:#e08c1a;border-radius:50%"></i>amber moon = early closure bought here</span>
    <span class="key"><i class="sw" style="background:#e08c1a;border-radius:50%"></i>amber plus = extra access-night bought here</span>
    <span class="key" style="opacity:.55"><i class="sw" style="background:#9aa3ae;border-radius:50%;opacity:.45"></i>faded = flagged in another week</span>
  </div>
  <div class="alertbar" id="alertbar"></div>
  <svg id="map" viewBox="__VIEW__" xmlns="http://www.w3.org/2000/svg">
    <defs>
      <filter id="soft" x="-30%" y="-30%" width="160%" height="160%">
        <feDropShadow dx="0" dy="9" stdDeviation="9" flood-color="#0b2545" flood-opacity="0.13"/>
      </filter>
      <filter id="glow" x="-90%" y="-90%" width="280%" height="280%">
        <feDropShadow dx="0" dy="0" stdDeviation="7" flood-color="#e02424" flood-opacity="0.85"/>
        <feDropShadow dx="0" dy="4" stdDeviation="3" flood-color="#5c0000" flood-opacity="0.45"/>
      </filter>
    </defs>
    <g id="scene" filter="url(#soft)"></g>
    <g id="links"></g>
    <g id="labels"></g>
    <g id="ghosts"></g>
    <g id="markers"></g>
  </svg>
</div>
<div id="tip"></div>
<script>
const D = __DATA__;
const FREE = "#dbe4ee", HUB = "#6b62c9", ALERT = "#e02424", FULL = "#f5a623";
const LOCKED = "#4a5463";
const ECLOC = "#e08c1a";   // early closure: hours taken out of the night
// bit 2 over capacity, bit 4 late but fixable, bit 8 late and unfixable,
// bit 16 contested. An exclamation mark means a clash between programmes;
// a clock means a date problem. The two never share a symbol.
function kindOf(f){
  if (f & 16) return "conflict";          // cannot fit here as requested
  if (f & 64) return "share";             // requires a shared possession
  if (f & 4)  return "act";               // late, and still movable
  if (f & 8)  return "stuck";             // late, and out of calendar
  if (f & 2)  return "excess";            // an extra access-night was bought
  return "eclo";                          // bought with extra night hours
}
const PAL = {1:"#2a78d6", 2:"#eb6834", 3:"#1baf7a"};
const NS = "http://www.w3.org/2000/svg";

function shade(hex, f){
  const n = parseInt(hex.slice(1), 16);
  const r = Math.round(((n>>16)&255)*f), g = Math.round(((n>>8)&255)*f), b = Math.round((n&255)*f);
  return "rgb("+r+","+g+","+b+")";
}
function el(tag, attrs){
  const e = document.createElementNS(NS, tag);
  for (const k in attrs) e.setAttribute(k, attrs[k]);
  return e;
}

const scene = document.getElementById("scene");
const TILES = {};
for (const t of D.tiles){
  const g = el("g", {});
  const base = t.kind === "pillar" ? "#c3cddb" : (t.hub ? HUB : FREE);
  const top = el("polygon", {points:t.top, fill:base, stroke:"#ffffff", "stroke-width":1.2,
                             "stroke-linejoin":"round"});
  const lf  = el("polygon", {points:t.left,  fill:shade(base,0.62), stroke:"none"});
  const rf  = el("polygon", {points:t.right, fill:shade(base,0.80), stroke:"none"});
  g.appendChild(lf); g.appendChild(rf); g.appendChild(top);
  scene.appendChild(g);
  if (t.loc){
    TILES[t.loc] = {top:top, l:lf, r:rf, hub:t.hub, g:g};
    g.addEventListener("mousemove", e => showTip(e, t.loc));
    g.addEventListener("mouseleave", hideTip);
  }
}

const labs = document.getElementById("labels");
for (const L of D.labels){
  const t = el("text", {x:L.x, y:L.y, "text-anchor":L.a,
    "font-size": L.big ? 20 : 13.5, "font-weight": L.big ? 700 : (L.hub ? 700 : 600),
    fill: L.big ? "#0b0b0b" : (L.hub ? "#4a42a8" : "#52514e"),
    stroke:"#f6f9fc", "stroke-width": L.big ? 5 : 3.5, "paint-order":"stroke fill",
    "stroke-linejoin":"round", "font-family":"inherit"});
  t.textContent = L.t; labs.appendChild(t);
}
for (const L of D.lanes){
  const t = el("text", {x:L.x, y:L.y, "text-anchor":(L.a || "start"),
                        "font-size":12, fill:"#7d7d79", "font-style":"italic",
                        stroke:"#f6f9fc", "stroke-width":3, "paint-order":"stroke fill",
                        "font-family":"inherit"});
  t.textContent = L.t; labs.appendChild(t);
}

const lnk = document.getElementById("links");
for (const L of (D.links || [])){
  lnk.appendChild(el("line", {x1:L.x1, y1:L.y1, x2:L.x2, y2:L.y2,
    stroke:"#6b62c9", "stroke-width":2.4, "stroke-dasharray":"7 6", opacity:.75}));
  const mx = (L.x1 + L.x2) / 2, my = (L.y1 + L.y2) / 2;
  const c = el("text", {x:mx, y:my - 7, "text-anchor":"middle", "font-size":11.5,
    fill:"#4a42a8", "font-weight":600, stroke:"#f6f9fc", "stroke-width":3.5,
    "paint-order":"stroke fill", "font-family":"inherit"});
  c.textContent = L.t + " interchange"; lnk.appendChild(c);
}

// ---- the flag itself: a warning sign on a post, big enough to find at a glance
function flag(live, kind){
  const bought = kind === "eclo" || kind === "excess";
  const share  = kind === "share";
  const col = kind === "stuck" ? LOCKED : (bought || share) ? ECLOC : ALERT;
  const alive = live && kind !== "stuck" && !bought;
  const clash = kind === "conflict";
  const moon  = kind === "eclo";
  const plus  = kind === "excess";
  const g = el("g", {});
  g.appendChild(el("line", {x1:0, y1:2, x2:0, y2:-74, stroke:col,
                            "stroke-width":4, "stroke-linecap":"round"}));
  g.appendChild(el("ellipse", {cx:0, cy:2, rx:13, ry:6.5, fill:col, opacity:.32}));
  if (alive){
    g.appendChild(el("ellipse", {cx:0, cy:2, rx:17, ry:8.5, fill:"none", stroke:col,
                                 "stroke-width":3, class:"gring"}));
  }
  const head = el("g", alive ? {class:"bob"} : {});
  if (alive) head.appendChild(el("circle", {cx:0, cy:-96, r:20, fill:col, class:"ring"}));
  if (share){
    // two rings: the teams fit here, but only by working one possession
    // together. Amber, because it needs agreeing -- not red, because nothing
    // here is impossible.
    head.appendChild(el("circle", {cx:0, cy:-90, r:24, fill:col,
                                   stroke:"#ffffff", "stroke-width":3.5}));
    head.appendChild(el("circle", {cx:-7.5, cy:-90, r:8.5, fill:"none",
                                   stroke:"#ffffff", "stroke-width":3}));
    head.appendChild(el("circle", {cx:7.5, cy:-90, r:8.5, fill:"none",
                                   stroke:"#ffffff", "stroke-width":3}));
  } else if (plus){
    // a plus: one more possession than this place nominally holds, bought
    head.appendChild(el("circle", {cx:0, cy:-90, r:24, fill:col,
                                   stroke:"#ffffff", "stroke-width":3.5}));
    head.appendChild(el("path", {d:"M-11,-90 L11,-90 M0,-101 L0,-79",
                                 stroke:"#ffffff", "stroke-width":4.6,
                                 "stroke-linecap":"round"}));
  } else if (moon){
    // a crescent: this night was bought by closing early or opening late
    head.appendChild(el("circle", {cx:0, cy:-90, r:24, fill:col,
                                   stroke:"#ffffff", "stroke-width":3.5}));
    head.appendChild(el("path", {d:"M6,-103 A15,15 0 1 0 6,-77 A12,12 0 1 1 6,-103 Z",
                                 fill:"#ffffff"}));
  } else if (!clash){
    // a clock: this is a date problem, not a clash. Deliberately not a
    // prohibition sign, which on a track map would read as "do not enter".
    head.appendChild(el("circle", {cx:0, cy:-90, r:24, fill:col,
                                   stroke:"#ffffff", "stroke-width":3.5}));
    head.appendChild(el("path", {d:"M0,-90 L0,-106 M0,-90 L11.5,-83",
                                 stroke:"#ffffff", "stroke-width":3.4,
                                 "stroke-linecap":"round", fill:"none"}));
    head.appendChild(el("circle", {cx:0, cy:-90, r:2.8, fill:"#ffffff"}));
  } else {
    head.appendChild(el("path", {d:"M0,-122 L23,-80 L-23,-80 Z", fill:col,
                                 stroke:"#ffffff", "stroke-width":3.5,
                                 "stroke-linejoin":"round"}));
    const bang = el("text", {x:0, y:-86, "text-anchor":"middle", fill:"#ffffff",
                             "font-size":24, "font-weight":800, "font-family":"inherit"});
    bang.textContent = "!";
    head.appendChild(bang);
  }
  g.appendChild(head);
  if (alive && !share) g.setAttribute("filter", "url(#glow)");
  return g;
}

// Faded symbols stand permanently wherever trouble happens at any point. On a
// big programme that becomes a swarm that hides the network, so keep only the
// most persistent ones -- the banner and the tick strip carry the rest.
const GHOST_CAP = 10;
const ghosts = document.getElementById("ghosts");
const GHOST = {};
const hardness = loc => {
  for (const w of (D.alertLocs[loc] || []))
    if (((D.weeks[w] || {})[loc] || [0,0,0,0,0])[4] & 16) return 1;
  return 0;
};
// What cannot fit stands on the network first; what only needs agreeing fills
// whatever room is left.
const ghostLocs = Object.keys(D.alertLocs || {})
  .sort((a, b) => (hardness(b) - hardness(a))
               || (D.alertLocs[b].length - D.alertLocs[a].length));
const ghostShown = ghostLocs.slice(0, GHOST_CAP);
const ghostHidden = ghostLocs.length - ghostShown.length;
for (const loc of ghostShown){
  const a = D.anchors[loc];
  if (!a) continue;
  const w0 = D.alertLocs[loc][0];
  const gk = kindOf(((D.weeks[w0] || {})[loc] || [0,0,0,0,0])[4]);
  const g = el("g", {transform:"translate(" + a[0] + "," + a[1] + ") scale(0.78)",
                     opacity:.30});
  g.appendChild(flag(false, gk));
  g.style.cursor = "help";
  g.addEventListener("mousemove", e => {
    tip.textContent = "Flagged in week " + D.alertLocs[loc].join(", ") + " \u2014 " +
                      (D.weeks[D.alertLocs[loc][0]][loc] || [])[6];
    tip.style.left = (e.clientX + 14) + "px";
    tip.style.top = (e.clientY + 14) + "px";
    tip.style.opacity = 1;
  });
  g.addEventListener("mouseleave", hideTip);
  ghosts.appendChild(g);
  GHOST[loc] = g;
}

const tip = document.getElementById("tip");
let CUR = 1;
function showTip(e, loc){
  const s = (D.weeks[CUR]||{})[loc];
  tip.textContent = s ? s[5] : "Nothing booked here in week " + CUR;
  tip.style.left = (e.clientX + 14) + "px";
  tip.style.top  = (e.clientY + 14) + "px";
  tip.style.opacity = 1;
}
function hideTip(){ tip.style.opacity = 0; }

const markers = document.getElementById("markers");
const alertbar = document.getElementById("alertbar");
const slider = document.getElementById("wk");

// ---- the banner and the timeline ticks: visible before anyone scrubs anything
const banner = document.getElementById("banner");
const AW = D.alertWeeks || [], AS = D.alertSummary || [];
const ACT = AS.filter(e => e.kind !== "stuck" && e.kind !== "eclo");
const STUCK = AS.filter(e => e.kind === "stuck");
const ECLOS = AS.filter(e => e.kind === "eclo");

function weekRanges(ws){
  const a = ws.slice().sort((x,y) => x - y);
  const out = [];
  for (let i = 0; i < a.length; ){
    let j = i;
    while (j + 1 < a.length && a[j+1] === a[j] + 1) j++;
    out.push(i === j ? String(a[i]) : a[i] + "\u2013" + a[j]);
    i = j + 1;
  }
  return out;
}

function weekPhrase(ws){
  const r = weekRanges(ws);
  if (!r.length) return "";
  if (r.length <= 3) return " \u2014 week" + (ws.length === 1 ? " " : "s ") + r.join(", ");
  return " \u2014 " + ws.length + " weeks, from " + r[0].split("\u2013")[0]
       + " to " + r[r.length-1].split("\u2013").pop();
}

// A wall of chips is unreadable. Show the worst few; the rest on request.
const CHIPS_SHOWN = 3;
function addChips(row, list, cls){
  const sorted = list.slice().sort((a,b) => b.worst - a.worst);
  const make = e => {
    const b = document.createElement("button");
    b.className = "chip" + (cls ? " " + cls : "");
    const wk = e.weeks[e.weeks.length - 1];
    b.textContent = e.who + " \u00B7 " + e.worst + (e.unit || "d over") + " \u00B7 week " + wk;
    b.onclick = () => { slider.value = wk; draw(wk); };
    return b;
  };
  for (const e of sorted.slice(0, CHIPS_SHOWN)) row.appendChild(make(e));
  const rest = sorted.slice(CHIPS_SHOWN);
  if (!rest.length) return;
  const more = document.createElement("button");
  more.className = "chip" + (cls ? " " + cls : "");
  more.style.fontWeight = "500";
  more.textContent = "+ " + rest.length + " more";
  more.onclick = () => {
    more.remove();
    for (const e of rest) row.appendChild(make(e));
  };
  row.appendChild(more);
}

function bannerRow(list, locked){
  const row = document.createElement("div");
  row.className = "row";
  const weeks = [];
  for (const e of list) for (const w of e.weeks) if (weeks.indexOf(w) === -1) weeks.push(w);
  const worst = list.slice().sort((a,b) => b.worst - a.worst)[0];
  const hd = document.createElement("span");
  hd.className = "hd" + (locked ? " lock" : "");
  hd.textContent = locked
    ? "\u23F1 Out of calendar: " + list.length
      + (list.length === 1 ? " programme cannot" : " programmes cannot")
      + " finish on time whatever is done. Renegotiate the dates."
      + (worst ? " Worst: " + worst.who + ", " + worst.worst + " days." : "")
    : "\u26A0 " + list.length + (list.length === 1 ? " programme finishes" : " programmes finish")
      + " late and could still be pulled earlier"
      + (worst ? ". Worst: " + worst.who + ", " + worst.worst + " days" : "")
      + weekPhrase(weeks) + ".";
  row.appendChild(hd);
  addChips(row, list, locked ? "lock" : "");
  return row;
}

const CONTESTED = D.mode === "conflicts";

if (CONTESTED){
  document.getElementById("legend").innerHTML =
    '<span class="key"><i class="sw" style="background:#2a78d6"></i>P1 critical</span>' +
    '<span class="key"><i class="sw" style="background:#eb6834"></i>P2 important</span>' +
    '<span class="key"><i class="sw" style="background:#1baf7a"></i>P3 routine</span>' +
    '<span class="key"><i class="sw" style="background:#dbe4ee"></i>no work</span>' +
    '<span class="key"><i class="sw" style="background:#e02424;border-radius:50%"></i>red = reschedule</span>' +
    '<span class="key"><i class="sw" style="background:#e08c1a;border-radius:50%"></i>amber = share access</span>' +
    '<span class="key"><i class="sw" style="background:#fdfdfd;border:2.5px solid #f5a623"></i>outline = full</span>' +
    '<span class="key" style="opacity:.55"><i class="sw" style="background:#9aa3ae;border-radius:50%;opacity:.45"></i>faded = other week</span>';
}

if (CONTESTED && AS.length){
  banner.className = "bad";
  const row = document.createElement("div");
  row.className = "row";
  const hd = document.createElement("span");
  hd.className = "hd";
  let hard = 0, shared = 0;
  for (const w of AW) for (const loc in (D.weeks[w] || {})){
    const f = D.weeks[w][loc][4];
    if (f & 16) hard++; else if (f & 64) shared++;
  }
  const unmapped = D.unmappedConflictFlagCount || 0;
  banner.className = hard ? "bad" : "share";
  hd.className = hard ? "hd" : "hd share";
  hd.textContent = hard
    ? "\u26A0 " + hard + " worksite-week" + (hard === 1 ? "" : "s") + " need replanning"
        + (shared ? " \u00b7 " + shared + " need shared access" : "")
        + (unmapped ? " \u00b7 " + unmapped + " programme-level issue" + (unmapped === 1 ? "" : "s") : "")
    : "\u25CE " + shared + " worksite-week" + (shared === 1 ? "" : "s")
        + " need shared access" + (unmapped ? " \u00b7 " + unmapped + " programme-level issues" : "");
  row.appendChild(hd);
  banner.appendChild(row);
  const HARD = AS.filter(e => e.hard).map(e => ({...e, weeks:e.hardWeeks}));
  const SHARE = AS.filter(e => e.share).map(e => ({...e, weeks:e.shareWeeks}));
  if (HARD.length){
    const row2 = document.createElement("div");
    row2.className = "row";
    for (const e of HARD){ e.worst = e.hard || e.worst; e.unit = " cannot fit"; }
    addChips(row2, HARD, "");
    banner.appendChild(row2);
  }
  if (SHARE.length){
    const row3 = document.createElement("div");
    row3.className = "row";
    for (const e of SHARE){ e.worst = e.share || e.worst; e.unit = " to share"; }
    addChips(row3, SHARE, "share");
    banner.appendChild(row3);
  }
} else if (!CONTESTED) {
  const s = D.scheduleSummary;
  banner.className = s.contracts_overrunning ? "bad" : "share";
  const row = document.createElement("div");
  row.className = "row";
  const hd = document.createElement("span");
  hd.className = "hd share";
  hd.textContent = s.eclo_accesses + " ECLO activity-accesses · "
    + s.extra_access_nights + " extra access-nights · "
    + s.contracts_overrunning + " contracts finish late";
  row.appendChild(hd);
  banner.appendChild(row);
  if (s.eclo_accesses) {
    const detail = document.createElement("div");
    detail.className = "row";
    detail.textContent = "ECLO provides 1.5 work units per access"
      + weekPhrase(s.eclo_weeks) + ". Each access is counted once, across all worksites.";
    banner.appendChild(detail);
    const chips = document.createElement("div");
    chips.className = "row";
    addChips(chips, s.eclo_by_contract, "share");
    banner.appendChild(chips);
  }
} else {
  banner.className = "ok";
  banner.textContent = "No mapped conflict flags.";
}
const ticks = document.getElementById("ticks");
for (const w of AW){
  let anyAct = false, anyHard = false;
  const st = D.weeks[w] || {};
  for (const loc in st){
    if (st[loc][4] & 28) anyAct = true;
    if (st[loc][4] & 16) anyHard = true;
  }
  const d = document.createElement("i");
  // In the contested view a week is red only if something there cannot fit at
  // all; a week that merely needs teams to share is amber, like its symbols.
  d.className = "tick" + (CONTESTED ? (anyHard ? "" : " share")
                                    : (anyAct ? "" : " lock"));
  d.style.left = ((w - 1) / (D.horizon - 1) * 100) + "%";
  d.title = "Week " + w + (CONTESTED
            ? (anyHard ? " has work that cannot fit as requested"
                       : " has teams that must share a possession")
            : anyAct ? " needs a decision" : " has work that cannot be moved");
  ticks.appendChild(d);
}

function draw(w){
  CUR = w;
  const st = D.weeks[w] || {};
  const hits = [];
  for (const loc in st){ if (st[loc][4] & 126) hits.push(loc); }

  for (const loc in TILES){
    const T = TILES[loc], s = st[loc];
    let base = T.hub ? HUB : FREE;
    if (s) base = PAL[s[0]] || FREE;
    T.top.setAttribute("fill", base);
    T.l.setAttribute("fill", shade(base, 0.62));
    T.r.setAttribute("fill", shade(base, 0.80));
    const flagged = s && (s[4] & 126);
    const bk = flagged ? kindOf(s[4]) : null;
    const atLimit = s && (s[4] & 1);
    const fcol = !flagged ? null
               : bk === "stuck" ? LOCKED
               : (bk === "eclo" || bk === "excess" || bk === "share") ? ECLOC : ALERT;
    // (an exclamation mark outlines the same red as a fixable overrun; the
    //  symbol on the post is what tells them apart)
    T.top.setAttribute("stroke", fcol || (atLimit ? FULL : "#ffffff"));
    T.top.setAttribute("stroke-width", flagged ? 5 : (atLimit ? 2.6 : 1.2));
  }

  for (const loc in GHOST){
    GHOST[loc].style.display = (hits.indexOf(loc) === -1) ? "" : "none";
  }

  while (markers.firstChild) markers.removeChild(markers.firstChild);
  hits.sort((a,b) => (D.anchors[a][1] - D.anchors[b][1]));
  for (const loc of hits){
    const a = D.anchors[loc], s = st[loc];
    const g = el("g", {transform:"translate(" + a[0] + "," + a[1] + ")"});
    g.appendChild(flag(true, kindOf(s[4])));
    g.style.cursor = "help";
    g.addEventListener("mousemove", ev => {
      tip.textContent = (s[6] || "Needs attention") + " \u2014 " + s[5];
      tip.style.left = (ev.clientX + 14) + "px";
      tip.style.top = (ev.clientY + 14) + "px";
      tip.style.opacity = 1;
    });
    g.addEventListener("mouseleave", hideTip);
    markers.appendChild(g);
  }

  let anyAct = false, anyHard = false, anyShare = false;
  for (const l of hits){
    const f = st[l][4];
    if (f & 12) anyAct = true;
    if (f & 16) anyHard = true;
    if (f & 64) anyShare = true;
  }
  // A week where teams only have to share is not an emergency: the line under
  // the map goes amber, the same as its symbols, so the two never disagree.
  alertbar.style.color = (anyAct || anyHard) ? "#e02424"
                       : anyShare ? "#e08c1a" : "#3c4653";
  const hardCount=hits.filter(l=>st[l][4]&16).length;
  const shareCount=hits.filter(l=>!(st[l][4]&16) && (st[l][4]&64)).length;
  alertbar.textContent = CONTESTED
    ? [hardCount ? hardCount + " worksites need rescheduling" : "",
       shareCount ? shareCount + " need shared access" : ""].filter(Boolean).join(" · ")
    : hits.length ? hits.length + " worksites need review — hover a marker for details." : "";
  document.getElementById("wklab").textContent = "Week " + w;
  const d = D.dates[w];
  document.getElementById("dtlab").textContent = d ? (d[0] + " \u2013 " + d[1]) : "";
}

slider.addEventListener("input", () => draw(+slider.value));

let timer = null;
const btn = document.getElementById("play");
btn.addEventListener("click", () => {
  if (timer){ clearInterval(timer); timer = null; btn.innerHTML = "&#9654;&nbsp; Play"; return; }
  btn.innerHTML = "&#10073;&#10073;&nbsp; Pause";
  timer = setInterval(() => {
    let w = +slider.value + 1;
    if (w > D.horizon) w = 1;
    slider.value = w; draw(w);
  }, 700);
});

draw(__START__);
slider.value = __START__;
</script>
"""


def _themed_shell(mode: str) -> str:
    """Apply the app palette to the self-contained map document.

    The map lives in an iframe, so page CSS cannot reach it. Keeping the
    colour translation here makes its labels, controls and alert states follow
    the same dark/light switch as the rest of the planner.
    """
    t = theme.tokens(mode)
    priority = theme.priority_colours(mode)
    dark = t["mode"] == "dark"
    edge = "#dbeafe" if dark else "#ffffff"
    tip_bg = t["panel2"] if dark else t["ink"]
    tip_ink = t["ink"] if dark else t["panel"]
    pill_bg = t["panel2"] if dark else t["panel"]
    replacements = {
        "#0b0b0b": t["ink"], "#52514e": t["muted"], "#e6e5e1": t["line"],
        "#e02424": t["red"], "#f6f9fc": t["bg2"], "#fff0f0": t["panel2"],
        "#f3b7b7": t["red"], "#f0d3d3": t["line"], "#3c4653": t["muted"],
        "#c2c9d2": t["line"], "#eefaf1": t["panel2"], "#bfe6cc": t["good"],
        "#0a8a35": t["good"], "#e6a5a5": t["red"], "#a01818": t["red"],
        "#2a78d6": priority[1], "#1f63b5": priority[1],
        "#eb6834": priority[2], "#1baf7a": priority[3],
        "#dbe4ee": t["free"], "#6b62c9": t["hub"], "#4a5463": t["locked"],
        "#f5a623": t["amber"], "#e08c1a": t["amber"], "#a86410": t["amber"],
        # the pillars: visible legs on dark, the original pale grey on light
        "#c3cddb": t["locked"] if dark else "#c3cddb",
        "#4a42a8": t["violet"], "#7d7d79": t["muted"],
        "#9aa3ae": t["faint"], "#0b2545": t["blue"], "#5c0000": t["red"],
        "#ffffff": edge,
        # The tooltip and the pill backgrounds have to invert with the mode,
        # so they carry their own sentinels rather than share --ink or white.
        "#1a1a1a": tip_bg, "#fefefe": tip_ink, "#fdfdfd": pill_bg,
    }
    out = _SHELL
    for before, after in replacements.items():
        out = out.replace(before, after)
    return out


def _note(inst: Instance) -> str:
    """Legacy network description kept for API/tests; no longer displayed."""
    lanes = lanes_for(inst)
    lines = sorted({line for line, _bound in lanes}, key=lambda line: min(
        value for (known, _bound), value in lanes.items() if known == line))
    word = {1: "one line", 2: "the two lines", 3: "the three lines"}.get(
        len(lines), f"the {len(lines)} lines")
    hubs = sorted({station.station_id for station in inst.stations
                   if station.is_interchange})
    hub_text = ""
    if hubs:
        listed = " and ".join(hubs) if len(hubs) < 3 else ", ".join(hubs[:-1]) + " and " + hubs[-1]
        hub_text = f", with {listed} the shared interchange{'s' if len(hubs) != 1 else ''}"
    per = max(sum(1 for line, _bound in lanes if line == known) for known in lines)
    tracks = "two tracks, one per direction" if per == 2 else f"{per} track{'s' if per != 1 else ''}"
    return (f"Isometric schematic of {word}. The dataset has no geography "
            f"&mdash; stations are shown in running order{hub_text}. Each line is "
            f"drawn as {tracks}.")


def render(inst: Instance, sub: Submission, start_week: int = 1,
           late_kind: dict[str, str] | None = None, conflicts=None,
           mode: str = "dark") -> str:
    p = payload(inst, sub, late_kind, conflicts)
    start = max(1, min(int(start_week), p["horizon"]))
    return (_themed_shell(mode)
            .replace("__VIEW__", " ".join(str(v) for v in p["view"]))
            .replace("__HORIZON__", str(p["horizon"]))
            .replace("__START__", str(start))
            .replace("__DATA__", json.dumps(p, separators=(",", ":"))))
