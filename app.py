"""Track Access Planner.

Opens on the schedule currently in force. Requests are checked against it.
Planning a future horizon is a separate exercise you go to deliberately.

Run:  streamlit run app.py
"""
from __future__ import annotations

import datetime
import hashlib
import io
import json
import os
import sys
import tempfile
import zipfile
from pathlib import Path

import altair as alt
import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT / "src"))

from trackaccess.agent import Toolbox, ask
from trackaccess.agent import available as agent_available
from trackaccess.board import (closures_for_week, contract_rows, crew_order,
                               headline, needs_attention, recommend,
                               week_board)
from trackaccess.calibrate import calibrate
from trackaccess.conflicts import as_requested, resolution
from trackaccess.conflicts import summarise as conflict_summary
from trackaccess import isomap
from trackaccess import names as N
from trackaccess.explain import analyse, why_not_week
from trackaccess.propose import (Proposal, fit_request, narrate_proposal,
                                 proposal_facts, pull_earlier)
from trackaccess.model import load_instance
from trackaccess.submission import load_submission, save_submission
from trackaccess.trackspace_bridge import (TrackspaceUnavailable,
                                           availability as trackspace_availability,
                                           ENGINE_RULESET, requested_pressure,
                                           solve_trackspace, search_alternatives)
from trackaccess import theme
from trackaccess.trackspace_view import attention_items, schedule_summary, requested_changes
from trackaccess.validate import Policy, validate
from trackaccess.whatif import (JobSpec, diagnose_rejection, placement_options,
                                weeks_by_activity, with_extra_job)

TRACKSPACE_POLICY = Policy(buffer_pushes_carriers_only=True)

@st.cache_data(ttl=300, show_spinner=False)
def planner_availability():
    return trackspace_availability()


PLANNER_OK, PLANNER_WHY = planner_availability()


def embed_html(html: str, height: int):
    """Put a self-contained page on screen.

    st.components.v1.html is past its announced removal date and st.iframe is
    the replacement, but the two take different arguments and Cloud installs
    whatever is newest. Support both rather than find out at deploy time.
    """
    if hasattr(st, "iframe"):
        st.iframe(html, height=height)
    else:
        components.html(html, height=height, scrolling=False)


CP_SAT_TIME_LIMIT_SECONDS = 120.0


def plan(path, code, progress=None, seconds: float = CP_SAT_TIME_LIMIT_SECONDS):
    """Build one scenario using Trackspace only.

    A Python fallback would create a result with different rules and scores.
    It is better to stop and identify the missing Trackspace runtime than to
    show a plausible-looking comparison from another planner.
    """
    if not PLANNER_OK:
        raise TrackspaceUnavailable(PLANNER_WHY)
    return solve_trackspace(path, code, progress, seconds=seconds), "Trackspace"

PRIORITY = {1: "P1 · critical", 2: "P2 · important", 3: "P3 · routine"}
PRIORITY_NOTE = ("Priority sets what a late finish costs: **P1 counts 100× per day**, "
                 "P2 10×, P3 1×. When something has to give, it gives on P3 first "
                 "and touches P1 last.")

PLANS = {
    "Protect the track": dict(code="A", blurb="Never book more work than a location "
                                              "can take. Deadlines slip where they must."),
    "Hit every deadline": dict(code="B", blurb="Every contract finishes on time. Buy "
                                               "extra nights and longer closures."),
    "Balanced": dict(code="C", blurb="Allow a little overbooking and a little "
                                     "slippage, whichever costs less."),
}
CODE_TO_NAME = {v["code"]: k for k, v in PLANS.items()}
REQUIRED = ["01_LINES.csv", "02_STATIONS.csv", "03_SECTORS.csv",
            "04_LOCATION_SUPPLY.csv", "05_BUFFER_LOCATION.csv",
            "06_PARAMETERS.csv", "07_PROJECT_DETAILS.csv", "08_ACTIVITY_DETAILS.csv"]

try:
    if "ANTHROPIC_API_KEY" in st.secrets and not os.environ.get("ANTHROPIC_API_KEY"):
        os.environ["ANTHROPIC_API_KEY"] = str(st.secrets["ANTHROPIC_API_KEY"])
except Exception:
    pass

st.set_page_config(page_title="NextStatioNUS", page_icon="🚇",
                   layout="wide", initial_sidebar_state="expanded")

# Do not let a browser session keep displaying an old schedule after the
# embedded Trackspace validation rules have changed.
if st.session_state.get("trackspace_ruleset") != ENGINE_RULESET:
    for _stale in ("outs", "in_force", "assistant_answer", "assistant_scope"):
        st.session_state.pop(_stale, None)
    st.session_state["trackspace_ruleset"] = ENGINE_RULESET

# The application is deliberately dark-only. Native Streamlit controls and
# the 3-D renderer now share one fixed palette rather than a fragile toggle.
st.session_state["ui_mode"] = "dark"
MODE = "dark"
_T = theme.tokens(MODE)
P = theme.priority_colours(MODE)
INK, MUTED, LINE = _T["ink"], _T["muted"], _T["line"]
GOOD, WARN, CRIT = _T["good"], _T["amber"], _T["red"]
SEQ = [_T["free"], _T["locked"], _T["cyan"], _T["blue"], _T["violet"], _T["ink"]]
st.markdown(theme.css(MODE), unsafe_allow_html=True)
alt.data_transformers.disable_max_rows()


# ---------------------------------------------------------------- helpers
def tile(col, k, v, n="", color=INK):
    col.markdown(f"<div class='tile'><div class='k'>{k}</div>"
                 f"<div class='v' style='color:{color}'>{v}</div>"
                 f"<div class='n'>{n}</div></div>", unsafe_allow_html=True)


loc_label = N.place_short


@st.cache_resource(show_spinner=False)
def load_inst(path: str):
    return load_instance(path)


@st.cache_resource(show_spinner=False)
def bundled_schedule(path: str):
    """The schedule already in force: the committed plan shipped with the repo."""
    marker = ROOT / "submissions" / "PLAN_IN_FORCE.txt"
    code = marker.read_text().strip()[:1].upper() if marker.exists() else "A"
    folder = ROOT / "submissions" / code
    if folder.exists():
        return load_submission(folder), code, "committed schedule of record"
    out, _engine = plan(path, code)
    return out.submission, code, "derived from the current programme"


@st.cache_data(show_spinner=False)
def conflicts_for(data_dir: str, key):
    """One source of truth: the same Trackspace rules as A/B/C use.

    Every finding is order-independent, so the numbers on the tiles, the rows
    in the table and the symbols on the map are the same set counted three
    ways, and none of them move unless the programme does.
    """
    cs = requested_pressure(data_dir)
    return cs, conflict_summary(cs)


def conflict_rows(inst, conflicts):
    """Make the requested-programme clashes readable before optimisation."""
    rows = []
    # What cannot be delivered comes first; within that, chronological.
    for c in sorted(conflicts, key=lambda c: (c.severity != "blocking",
                                              c.week, c.where)):
        try:
            where = N.place_short(c.where) if c.where else "—"
        except (ValueError, AttributeError):
            # Preserve a data identifier if a future input format introduces a
            # location name outside the standard SEC:/STN: convention.
            where = c.where or "—"
        rows.append({
            "Action": "Cannot fit as asked" if c.severity == "blocking"
                      else "Share a possession",
            "Rule": c.label,
            "Week": c.week,
            "Location": where,
            # One column, one type: a date-order clash has no possession count,
            # and pandas will not put an em dash in an integer column.
            "Possessions needed": str(c.need) if c.need else "\u2014",
            "Worksite has": str(c.supply) if c.supply else "\u2014",
            "Teams": len(c.parties),
            "Contracts": ", ".join(c.contracts),
            "What clashes": c.detail,
            "Likely resolution": c.options[0] if c.options else "Optimiser to resolve",
        })
    return rows


def submission_files(submission, scenario: str) -> dict[str, bytes]:
    """Return the three CSV deliverables produced for one scenario."""
    folder = Path(tempfile.mkdtemp()) / scenario
    save_submission(submission, folder)
    return {file.name: file.read_bytes() for file in sorted(folder.iterdir())}


def outcome_submission_files(outcome, scenario: str) -> dict[str, bytes]:
    """Use the CP-SAT handoff's exact exported CSV text when available."""
    raw = getattr(outcome, "csv_files", None)
    if raw:
        return {name: text.encode("utf-8") for name, text in raw.items()}
    return submission_files(outcome.submission, scenario)


@st.cache_data(show_spinner=False)
def conflict_map(_inst, _confs, key, mode: str):
    """The contested-track view: what the eight CSVs ask for, before any plan."""
    return isomap.render(_inst, None, 1, conflicts=_confs, mode=mode)


@st.cache_data(show_spinner=False)
def network_map(_inst, _sub, start, key, mode: str, _late_kind=None):
    """Isometric map of the network. `key` is a digest of the schedule and of
    the renderer version, so the map is rebuilt whenever either changes."""
    return isomap.render(_inst, _sub, start, _late_kind, mode=mode)


def themed_chart(chart):
    """Keep Altair's canvas, labels and legend in the active UI mode."""
    return (chart.configure(background=_T["bg"])
            .configure_axis(labelColor=MUTED, titleColor=MUTED,
                            domainColor=LINE, tickColor=LINE, gridColor=LINE)
            .configure_legend(labelColor=INK, titleColor=INK))


def _timeline_reason(code: str, activity_count: int, eclo_count: int,
                     extra_access: int) -> str:
    """A factual policy-level explanation for one scheduled week.

    Trackspace records the chosen schedule and the scenario metrics, not a
    per-location natural-language rationale.  Keep the wording tied to those
    recorded facts rather than inventing a reason for an individual station.
    """
    if not activity_count:
        return "No work is scheduled."
    facts = []
    if eclo_count:
        facts.append("ECLO is used to add 1.5 work units per access")
    if extra_access:
        facts.append("additional access is used above nominal supply")
    if not facts:
        facts.append({
            "A": "work stays within nominal weekly supply",
            "B": "work is placed to protect the fixed completion dates",
            "C": "the selected trade-off uses no extra access this week",
        }[code])
    text = "; ".join(facts)
    return text[:1].upper() + text[1:] + "."


def scenario_timeline(inst, sub, code: str, report: dict | None) -> pd.DataFrame:
    """One complete, hoverable planning-horizon timeline for a scenario."""
    access_by_week: dict[int, set[str]] = {}
    eclo_by_week: dict[int, int] = {}
    for access in sub.accesses:
        access_by_week.setdefault(access.week, set()).add(access.activity_id)
        if access.eclo:
            eclo_by_week[access.week] = eclo_by_week.get(access.week, 0) + 1

    locations_by_week: dict[int, set[str]] = {}
    possessions_by_week: dict[int, set[str]] = {}
    for occupancy in sub.occupancies:
        locations_by_week.setdefault(occupancy.week, set()).add(occupancy.location_id)
        possessions_by_week.setdefault(occupancy.week, set()).add(occupancy.co_share_group)

    excess_by_week: dict[int, int] = {}
    for item in (report or {}).get("utilization", []):
        if item.get("excess", 0):
            week = int(item["week"])
            excess_by_week[week] = excess_by_week.get(week, 0) + int(item["excess"])

    rows = []
    for week in inst.weeks:
        locations = sorted(locations_by_week.get(week, set()))
        stations = [N.place_short(loc) for loc in locations if loc.startswith("PLAT:")]
        tunnels = [N.place_short(loc) for loc in locations if loc.startswith("SEC:")]
        activity_count = len(access_by_week.get(week, set()))
        eclo_count = eclo_by_week.get(week, 0)
        extra_access = excess_by_week.get(week, 0)
        rows.append({
            "week": week,
            "week_label": f"Week {week}",
            "dates": f"{inst.week_start(week):%d %b} – {inst.week_end(week):%d %b %Y}",
            "activity_count": activity_count,
            "possession_count": len(possessions_by_week.get(week, set())),
            "stations": "; ".join(stations) or "—",
            "tunnels": "; ".join(tunnels) or "—",
            "eclo": eclo_count,
            "extra_access": extra_access,
            "reason": _timeline_reason(code, activity_count, eclo_count, extra_access),
            "lane": "Scheduled work",
        })
    return pd.DataFrame(rows)


def scenario_timeline_chart(rows: pd.DataFrame):
    """A readable full-horizon bar timeline, with every week available on hover."""
    tooltip = [
        alt.Tooltip("week_label:N", title="Week"),
        alt.Tooltip("dates:N", title="Dates"),
        alt.Tooltip("activity_count:Q", title="Activities"),
        alt.Tooltip("possession_count:Q", title="Possessions"),
        alt.Tooltip("stations:N", title="Platforms"),
        alt.Tooltip("tunnels:N", title="Tunnels"),
        alt.Tooltip("eclo:Q", title="ECLO accesses"),
        alt.Tooltip("extra_access:Q", title="Extra access"),
        alt.Tooltip("reason:N", title="Why this week"),
    ]
    base = alt.Chart(rows).encode(
        x=alt.X("week:O", title="Planning week",
                axis=alt.Axis(labelAngle=0, labelOverlap=False, tickMinStep=1)),
        y=alt.Y("activity_count:Q", title="Activities scheduled", scale=alt.Scale(nice=True)),
    )
    bars = base.mark_bar(cornerRadiusTopLeft=3, cornerRadiusTopRight=3,
                         color=_T["blue"]).encode(tooltip=tooltip)
    labels = base.mark_text(dy=-8, color=INK, fontWeight=600).encode(
        text=alt.condition(alt.datum.activity_count > 0,
                           alt.Text("activity_count:Q"), alt.value(""))
    )
    return themed_chart((bars + labels).properties(height=250))


def confidence_rows(outcome) -> pd.DataFrame:
    """Compare actual validated schedules, never a bound masquerading as a plan."""
    chosen = float(outcome.objective)
    rows = [{
        "Plan": "Chosen plan", "Score": round(chosen, 1),
        "Score difference": "—",
        "Overrun days": outcome.report.get("overrun_days_total", 0),
        "ECLO": outcome.report.get("eclo_nights_total", 0),
        "Extra access": outcome.report.get("excess_access_nights_total", 0),
    }]
    for index, candidate in enumerate(getattr(outcome, "alternatives", []), 1):
        report = candidate["report"]
        rows.append({
            "Plan": f"Alternative {index}", "Score": round(candidate["score"], 1),
            "Score difference": f"{candidate['score'] - chosen:+.1f}",
            "Overrun days": report.get("overrun_days_total", 0),
            "ECLO": report.get("eclo_nights_total", 0),
            "Extra access": report.get("excess_access_nights_total", 0),
        })
    return pd.DataFrame(rows)


def programme_chart(inst, sub, crows):
    """One row per contract; bars where they work; a black cut-off line at each
    contract's deadline. Anything to the right of its line is late."""
    have = pd.DataFrame([{"contract": inst.activities[a.activity_id].contract_number,
                          "week": a.week} for a in sub.accesses]).drop_duplicates()
    meta = {r["contract"]: r for r in crows}
    have["who"] = have["contract"].map(lambda c: meta[c]["who"])
    have["priority"] = have["contract"].map(lambda c: PRIORITY[meta[c]["priority"]])
    have["status"] = have["contract"].map(lambda c: meta[c]["status"])
    have["x1"] = have["week"] - 0.5
    have["x2"] = have["week"] + 0.5
    have["late"] = have.apply(
        lambda r: r["week"] > meta[r["contract"]]["deadline_week"], axis=1)
    have["state"] = have["late"].map({True: "late", False: "on time"})
    order_c = [r["contract"] for r in crows]
    late_lbl = pd.DataFrame([{"contract": r["contract"],
                              "x": r["last_week"] + 0.65,
                              "txt": f"late {r['overrun_days']}d"}
                             for r in crows if r["overrun_days"]])
    dl = pd.DataFrame([{"contract": r["contract"], "cutoff": r["deadline_week"] + 0.5,
                        "deadline": f"due by end of week {r['deadline_week']}"}
                       for r in crows])
    schedule_end = max((a.week for a in sub.accesses), default=inst.horizon_weeks)
    xaxis = alt.X("x1:Q", title="Week of programme",
                  scale=alt.Scale(domain=[0.5, schedule_end + 0.5], nice=False),
                  axis=alt.Axis(values=list(range(1, schedule_end + 1)),
                                labelExpr="datum.value", grid=False, labelColor=MUTED,
                                titleColor=MUTED, tickCount=schedule_end))
    yaxis = alt.Y("contract:N", sort=order_c, title=None,
                  axis=alt.Axis(grid=False, domain=False, ticks=False, labelColor=MUTED,
                                labelOverlap=False, labelFontSize=12))
    bars = (alt.Chart(have).mark_rect(cornerRadius=2)
            .encode(x=xaxis, x2="x2:Q", y=yaxis,
                    stroke=alt.condition(alt.datum.late, alt.value(CRIT),
                                         alt.value(_T["panel"])),
                    strokeWidth=alt.condition(alt.datum.late, alt.value(2.5),
                                              alt.value(1.5)),
                    color=alt.Color("priority:N", title="Contract priority",
                                    scale=alt.Scale(domain=list(PRIORITY.values()),
                                                    range=[P[1], P[2], P[3]]),
                                    legend=alt.Legend(orient="top", titleFontSize=12,
                                                      labelFontSize=12, symbolSize=120)),
                    tooltip=["contract", "who", "priority", "week", "state"]))
    lbl = (alt.Chart(late_lbl).mark_text(align="left", baseline="middle", color=CRIT,
                                         fontSize=11, fontWeight="bold")
           .encode(x="x:Q", y=alt.Y("contract:N", sort=order_c), text="txt:N"))
    cut = (alt.Chart(dl).mark_tick(orient="vertical", thickness=3, size=26, color=INK)
           .encode(x="cutoff:Q", y=alt.Y("contract:N", sort=order_c),
                   tooltip=[alt.Tooltip("contract:N"), alt.Tooltip("deadline:N")]))
    return themed_chart((bars + cut + lbl).properties(height=30 * len(order_c) + 120)
                        .configure_view(strokeWidth=0))


def apply_proposal(pr: Proposal, label: str):
    """The planner said yes. This is the only place the schedule in force changes."""
    st.session_state["in_force"] = {
        "submission": pr.submission, "scenario": sc,
        "provenance": st.session_state.get("in_force", {}).get(
            "provenance", provenance) if "in_force" in st.session_state
        else f"{provenance}, amended",
    }
    if pr.instance is not None:
        st.session_state["inst_override"] = pr.instance
    st.session_state.setdefault("changelog", []).append({
        "when": datetime.datetime.now().strftime("%d %b %H:%M"),
        "what": label, "steps": pr.steps, "cost": pr.score_change})
    for k in ("proposal", "options", "answer"):
        st.session_state.pop(k, None)
    st.rerun()


def preview_plan(submission, scenario: str, name: str, report: dict | None = None):
    """Open a generated scenario in the live dashboard and network map."""
    st.session_state["in_force"] = {
        "submission": submission,
        "scenario": scenario,
        "provenance": f"previewing {name} plan",
        "trackspace_report": report,
    }
    st.session_state.pop("options", None)
    st.session_state["ui_page"] = "plan"


def proposal_card(pr: Proposal, key: str):
    """One recommended change: the facts, the model's read of them, and yes/no."""
    with st.container(border=True):
        if not pr.ok:
            st.markdown(f"🔴 **{pr.summary}**")
            if pr.why_not:
                st.markdown(f"<span style='color:{MUTED}'>{pr.why_not}</span>",
                            unsafe_allow_html=True)
            return
        facts = proposal_facts(inst, sub, pr)
        tgt = facts.get("target")
        cost = ("no cost to the rest of the programme" if abs(pr.score_change) < 1e-6
                else f"cost to the programme {pr.score_change:+.1f}")
        st.markdown(f"💡 **Recommended change** — {pr.summary}")

        # -- the model's read, if it can be had ------------------------------
        # Cached against the PROPOSAL, not the widget key: two different
        # requests share a widget key, and keying on it served the first
        # request's assessment for every one after it.
        cache = st.session_state.setdefault("narrations", {})
        sig = json.dumps({"goal": pr.goal, "summary": pr.summary, "steps": pr.steps,
                          "cost": pr.score_change,
                          "weeks": facts.get("target", {}).get("weeks") if facts.get("target") else None},
                         sort_keys=True, default=str)
        ck = hashlib.sha1(sig.encode()).hexdigest()
        if agent_available():
            failed = None
            if ck not in cache:
                with st.spinner("Weighing it up…"):
                    try:
                        cache[ck] = narrate_proposal(facts)
                    except Exception as exc:
                        failed = exc          # never cached: a retry should retry
            if ck in cache:
                st.markdown(f"<div style='padding:10px 14px;border-left:3px solid {P[1]};"
                            f"background:{_T['panel2']};border-radius:6px;font-size:15px;"
                            f"line-height:1.55'>{cache[ck]}</div>",
                            unsafe_allow_html=True)
            elif failed is not None:
                st.caption(f"No written assessment this time ({type(failed).__name__}). "
                           f"The facts below are unaffected.")
            st.markdown("")

        # -- the facts the model was given ------------------------------------
        if tgt:
            wk = (f"weeks {tgt['weeks'][0]}–{tgt['weeks'][-1]}" if len(tgt["weeks"]) > 1
                  else f"week {tgt['weeks'][0]}")
            st.markdown(f"**{tgt['contractor']}** ({tgt['priority']}, {tgt['work']}) works "
                        f"{wk} — {', '.join(tgt['dates'])}.")
            st.markdown("Worksites: " + " · ".join(tgt["worksites"][:6])
                        + (f" and {len(tgt['worksites']) - 6} more" if len(tgt["worksites"]) > 6 else ""))
            if tgt["shares_possession_with"]:
                st.markdown("Shares a possession with: " + "; ".join(
                    f"week {w}: {', '.join(v)}" for w, v in tgt["shares_possession_with"].items()))
            else:
                st.markdown("Sole use of every worksite — nobody else on them those weeks.")
            if tgt["keeps_clear"]:
                st.markdown("Its safety buffer keeps clear: " + " · ".join(tgt["keeps_clear"][:4]))
            if tgt["eclo_nights"]:
                st.markdown(f"⚠️ Uses {tgt['eclo_nights']} early-closure night(s).")
        if facts["other_jobs_that_move"]:
            st.markdown("**Other work that moves**")
            for m in facts["other_jobs_that_move"]:
                st.markdown(f"- {m['contractor']} ({m['priority']}) — {m['change']} — "
                            f"{m['worksites'][0]}" + (" …" if len(m["worksites"]) > 1 else ""))
        st.markdown("**Tell:** " + ", ".join(facts["contractors_to_notify"]))
        st.caption(f"{len(pr.moved)} other job(s) move · {cost} · found by trying "
                   f"“{facts['how_found']}” first · every safety rule re-checked and passed")

        y, n = st.columns([1, 1])
        if y.button("Yes, make this change", key=f"yes_{key}", type="primary",
                    width='stretch'):
            apply_proposal(pr, pr.goal)
        if n.button("No, leave it as it is", key=f"no_{key}", width='stretch'):
            st.session_state.pop("proposal", None)
            st.rerun()


def job_chart(inst, sub, crows, only=None):
    """Jobs on their own rows, grouped under their contract. `only` narrows to
    one contract. Same rules as the contract chart: red outline past the
    contract's deadline, black cut-off, ▲ for a job flagged high within its
    contract. Rows are ordered by a numeric rank, which survives the trip
    through Streamlit where a list of label strings did not."""
    meta = {r["contract"]: r for r in crows}
    aids = [aid for c in [r["contract"] for r in crows]
            for aid in sorted(a for a, x in inst.activities.items()
                              if x.contract_number == c)
            if (not only or c == only)]
    rank = {aid: i for i, aid in enumerate(aids)}
    label = {aid: N.job_short(inst, aid) for aid in aids}
    rows = []
    for a in sub.accesses:
        if a.activity_id not in rank:
            continue
        act = inst.activities[a.activity_id]
        r = meta[act.contract_number]
        rows.append({"job": label[a.activity_id], "rank": rank[a.activity_id],
                     "who": r["who"], "priority": PRIORITY[r["priority"]],
                     "job_priority": N.JOB_TIER[act.activity_priority] + " within contract",
                     "week": a.week, "x1": a.week - 0.5, "x2": a.week + 0.5,
                     "late": a.week > r["deadline_week"],
                     "eclo": "early closure" if a.eclo else "standard night",
                     "worksite": N.place(act.start_location_id)})
    df = pd.DataFrame(rows)
    df["state"] = df["late"].map({True: "late", False: "on time"})
    present = sorted(set(df["rank"]))
    dl = pd.DataFrame([{"job": label[aid], "rank": rank[aid],
                        "cutoff": meta[inst.activities[aid].contract_number]["deadline_week"] + 0.5}
                       for aid in aids if rank[aid] in present])
    hi = pd.DataFrame([{"job": label[aid], "rank": rank[aid]} for aid in aids
                       if rank[aid] in present and inst.activities[aid].activity_priority == 1])
    ysort = alt.EncodingSortField(field="rank", order="ascending")
    schedule_end = max((a.week for a in sub.accesses), default=inst.horizon_weeks)
    xaxis = alt.X("x1:Q", title="Week of programme",
                  scale=alt.Scale(domain=[0.5, schedule_end + 0.5], nice=False),
                  axis=alt.Axis(values=list(range(1, schedule_end + 1)),
                                labelExpr="datum.value", grid=False, labelColor=MUTED,
                                titleColor=MUTED))
    yaxis = alt.Y("job:N", sort=ysort, title=None,
                  axis=alt.Axis(grid=False, domain=False, ticks=False, labelColor=MUTED,
                                labelOverlap=False, labelFontSize=10, labelLimit=340))
    bars = (alt.Chart(df).mark_rect(cornerRadius=2)
            .encode(x=xaxis, x2="x2:Q", y=yaxis,
                    stroke=alt.condition(alt.datum.late, alt.value(CRIT), alt.value(_T["panel"])),
                    strokeWidth=alt.condition(alt.datum.late, alt.value(2.5), alt.value(1.5)),
                    color=alt.Color("priority:N", title="Contract priority",
                                    scale=alt.Scale(domain=list(PRIORITY.values()),
                                                    range=[P[1], P[2], P[3]]),
                                    legend=alt.Legend(orient="top")),
                    tooltip=[alt.Tooltip("job:N"), alt.Tooltip("who:N"),
                             alt.Tooltip("priority:N", title="contract priority"),
                             alt.Tooltip("job_priority:N", title="job priority"),
                             alt.Tooltip("week:Q"), alt.Tooltip("worksite:N"),
                             alt.Tooltip("eclo:N"), alt.Tooltip("state:N")]))
    cut = (alt.Chart(dl).mark_tick(orient="vertical", thickness=2, size=18, color=INK)
           .encode(x="cutoff:Q", y=alt.Y("job:N", sort=ysort)))
    layers = bars + cut
    if len(hi):
        layers = layers + (alt.Chart(hi)
                           .mark_text(text="▲", color=INK, fontSize=11, align="right",
                                      baseline="middle")
                           .encode(x=alt.value(-6), y=alt.Y("job:N", sort=ysort),
                                   tooltip=alt.value("high priority within its contract")))
    # Streamlit's container sizing treats `height` as the whole canvas, legend
    # and axis included -- so give each row its 26px on top of ~120px of chrome.
    return themed_chart(layers.properties(height=26 * len(present) + 120)
                        .configure_view(strokeWidth=0))


# ---------------------------------------------------------------- instance
def clear_uploaded_programme():
    """Forget one uploaded dataset and every plan derived from it."""
    for key in ("upload_digest", "upload_path", "upload_initial", "outs", "in_force",
                "assistant_answer", "assistant_scope", "ui_page"):
        st.session_state.pop(key, None)
    # A new widget key clears Streamlit's displayed file chips on the rerun.
    st.session_state["upload_nonce"] = st.session_state.get("upload_nonce", 0) + 1


def go_to(page: str):
    """Navigate without throwing away the uploaded programme or built plans."""
    st.session_state["ui_page"] = page


def go_back():
    """Return to the immediately preceding planning step."""
    page = st.session_state.get("ui_page", "landing")
    st.session_state["ui_page"] = {
        "plan": "scenarios",
        "scenarios": "conflicts",
        "conflicts": "landing",
    }.get(page, "landing")


def resume_programme():
    st.session_state["ui_page"] = (
        "scenarios" if st.session_state.get("outs") else "conflicts"
    )


def global_assistant(inst=None, submission=None, scenario: str = "",
                     seconds: float = 20.0, scope: str = "",
                     trackspace_report: dict | None = None,
                     trackspace_conflicts=None, trackspace_scenarios=None):
    """The one persistent, API-backed question box for the whole app.

    The language model never receives a schedule directly: it calls Toolbox
    checks against the selected plan.  Before a plan has been built there is
    deliberately nothing to query, but the same control remains in place.
    """
    with st.container(border=True):
        context_key = hashlib.sha256(json.dumps(["trackspace-view-v2", scenario, trackspace_report,
                                                trackspace_scenarios, scope],sort_keys=True,default=str).encode()).hexdigest()
        if st.session_state.get('assistant_context_key') != context_key:
            st.session_state.pop('assistant_answer', None)
            st.session_state.pop('assistant_scope', None)
            st.session_state['assistant_context_key'] = context_key
        if scope:
            st.caption("Answering about " + scope)
        st.markdown("#### Ask the planner")
        if not agent_available():
            st.text_input("Ask the planner", label_visibility="collapsed", disabled=True,
                          placeholder="Connect your API key to ask about a schedule",
                          key="assistant_offline")
            st.caption("Assistant unavailable — add `ANTHROPIC_API_KEY` to Streamlit secrets.")
            return
        if (inst is None or submission is None or not submission.accesses
                or trackspace_report is None):
            st.text_input("Ask the planner", label_visibility="collapsed", disabled=True,
                          placeholder="Run the optimiser, then ask about a scenario",
                          key="assistant_waiting")
            st.caption("The assistant becomes available as soon as a schedule exists.")
            return

        with st.form("global_assistant_form", border=False, clear_on_submit=True):
            qcol, bcol = st.columns([5, 1])
            question = qcol.text_input(
                "Ask the planner", label_visibility="collapsed",
                placeholder="Ask anything about this schedule…",
                key="global_assistant_question",
            )
            submitted = bcol.form_submit_button("Ask", type="primary", width="stretch")

        if submitted and question.strip():
            box = Toolbox(inst, submission, scenario, float("nan"),
                          seconds=min(seconds, 20),
                          trackspace_report=trackspace_report,
                          trackspace_conflicts=trackspace_conflicts,
                          trackspace_scenarios=trackspace_scenarios)
            with st.spinner("Checking the schedule…"):
                try:
                    st.session_state["assistant_answer"] = ask(box, question.strip())
                    st.session_state["assistant_scope"] = scope or f"Scenario {scenario}"
                except Exception as exc:
                    st.session_state["assistant_answer"] = (f"Could not answer: {exc}", [])
                    st.session_state["assistant_scope"] = scope or f"Scenario {scenario}"

        if st.session_state.get("assistant_answer"):
            answer, trace = st.session_state["assistant_answer"]
            st.caption("Answering against " + st.session_state.get("assistant_scope", scope))
            st.info(answer)
            if trace:
                with st.expander(f"Checks run ({len(trace)})"):
                    for tr in trace:
                        st.markdown(f"**`{tr.tool}`** `{tr.args}`")
                        st.code(tr.result[:1200], language="json")


def build_all_scenarios(data_dir: str, seconds: float):
    """Run the three Trackspace policies, then advance to the comparison page."""
    outs, bar = {}, st.progress(0.0, "Working…")
    for i, (name, meta) in enumerate(PLANS.items()):
        def show_search_progress(info, i=i, name=name):
            bar.progress(i / len(PLANS),
                         f"{name}: optimising and validating the main plan…")

        bar.progress(i / len(PLANS), f"Starting “{name}”…")
        try:
            outs[name], engine_used = plan(data_dir, meta["code"],
                                           show_search_progress, seconds)
        except (TrackspaceUnavailable, RuntimeError) as exc:
            bar.empty()
            st.error(f"Trackspace could not build {name}: {exc}")
            return False
        st.session_state["engine_used"] = engine_used
        bar.progress((i + 1) / len(PLANS), f"Finished “{name}”.")
    bar.empty()
    st.session_state["outs"] = outs
    return True


st.sidebar.markdown("### Track access")
# The app begins with a programme the user brings. There is no bundled
# shortcut: a schedule shown before anyone uploaded anything is a schedule for
# somebody else's railway.
path = None
if True:
    nonce = st.session_state.get("upload_nonce", 0)
    ups = st.sidebar.file_uploader("Drop the 8 programme CSVs", type="csv",
                                   accept_multiple_files=True,
                                   key=f"programme_upload_{nonce}")
    retained = st.session_state.get("upload_path")
    if ups or retained:
        st.sidebar.button("Clear uploaded programme", on_click=clear_uploaded_programme,
                          width="stretch")
    if ups:
        miss = [r for r in REQUIRED if r not in {f.name for f in ups}]
        if miss:
            st.sidebar.error("Missing: " + ", ".join(miss))
        else:
            # Streamlit reruns on every button click.  Keep this exact upload
            # stable across reruns; otherwise clicking "Build the plans" would
            # replace the temporary folder and discard the plans it just made.
            contents = [(f.name, f.getvalue()) for f in ups]
            digest = hashlib.sha256(b"".join(
                name.encode("utf-8") + b"\0" + body
                for name, body in sorted(contents)
            )).hexdigest()
            if st.session_state.get("upload_digest") != digest:
                tmp = Path(tempfile.mkdtemp())
                for name, body in contents:
                    (tmp / name).write_bytes(body)
                st.session_state["upload_digest"] = digest
                st.session_state["upload_path"] = str(tmp)
                st.session_state["ui_page"] = "conflicts"
                st.session_state.pop("in_force", None)
                st.session_state.pop("upload_initial", None)
                # Plans are tied to the activity ids in the previous programme.
                # Never carry them across to an uploaded programme.
                st.session_state.pop("outs", None)
                st.session_state.pop("assistant_answer", None)
                st.session_state.pop("assistant_scope", None)
            path = st.session_state["upload_path"]
    elif retained:
        # The uploader is hidden while "Current programme" is selected, but
        # the retained directory keeps the same eight files and scenario
        # results across reruns.
        path = retained
    else:
        st.sidebar.caption("Expected: " + ", ".join(REQUIRED))

if not path:
    page = "landing"
elif "ui_page" not in st.session_state:
    page = "plan" if st.session_state.get("in_force") else (
        "scenarios" if st.session_state.get("outs") else "conflicts")
    st.session_state["ui_page"] = page
else:
    page = st.session_state["ui_page"]

# Back navigation is a compact static control above the wordmark; the landing
# page intentionally has no previous step, so it does not render one.
if page != "landing":
    st.button("← Back", type="primary", on_click=go_back, key="back_navigation",
              help="Return to the previous planning step.")

# The logo always leads. The full-width assistant is placed underneath only
# once the visitor has entered the planning flow, never on the welcome page.
st.markdown('<h1 class="brand-title"><span class="brand-next">NextStatio</span><span class="brand-station-n">N</span><span class="brand-us">US</span></h1>',
            unsafe_allow_html=True)
if page == "landing":
    st.markdown(theme.landing(MODE), unsafe_allow_html=True)
    if path:
        st.info("Your uploaded programme is still saved. Continue whenever you are ready.")
        st.button("Continue planning", type="primary", on_click=resume_programme)
    st.markdown(theme.train_banner(MODE), unsafe_allow_html=True)
    st.stop()

# Reserve this exact place for the search bar. It is filled after the active
# Trackspace plan/report has been resolved below.
assistant_slot = st.empty()

inst = load_inst(path)
# The page is the mode. There are no radio controls or hidden alternate views.
mode = "The schedule in force" if page == "plan" else "Plan a future horizon"
# The deliverable belongs at the top of the sidebar. Reserve the space now and
# fill it once a scenario exists.
download_slot = st.sidebar.empty()

# The reviewer controls were three switches every worker had to learn to
# ignore. The checks behind them are still worth showing someone auditing the
# solver, so they live at ?reviewer=1 rather than in everyone's way.
reviewer = str(st.query_params.get("reviewer", "")).lower() in ("1", "true", "yes")

# A bigger programme deserves a longer search. This replaces the slider nobody
# running the night should have to reason about.
seconds = max(30, min(120, 10 + len(inst.activities) // 2))

planning_policy = TRACKSPACE_POLICY

# Planning begins with the requested CSV programme itself.  Do not generate a
# provisional in-force plan first: it is slow, hides the input conflicts and is
# not the plan the user asked the optimiser to compare.
if mode == "Plan a future horizon":
    confs, csum = conflicts_for(path, (ENGINE_RULESET, path, tuple(sorted(inst.activities))))
    blocking = [c for c in confs if c.severity == "blocking"]
    coordination = [c for c in confs if c.severity == "coordination"]
else:
    # What is in force: something committed this session, else the bundled schedule.
    if "in_force" in st.session_state:
        f = st.session_state["in_force"]
        sub, sc, provenance = f["submission"], f["scenario"], f["provenance"]
        inst = st.session_state.get("inst_override", inst)
    else:
        # Unreachable in normal use: a programme with nothing in force goes
        # through the conflicts-then-scenarios flow above.
        sub, sc, provenance = bundled_schedule(path)

    if not sub.accesses:
        st.error(f"No feasible Scenario {sc} schedule could be produced for this programme.")
        st.info("Open **Plan a future horizon** and build all three scenarios to see "
                "which policy can schedule this data. Check the CSV relationships if "
                "none of them can.")
        st.stop()

    rep = st.session_state.get("in_force", {}).get("trackspace_report")
    if not rep or not rep.get("feasible"):
        st.error("This preview has no validated Trackspace report. Return and rerun the scenarios.")
        st.stop()
    crows = contract_rows(inst, sub)
    late = [r for r in crows if r["overrun_days"]]
    confs, csum = conflicts_for(path, (ENGINE_RULESET, path, tuple(sorted(inst.activities))))
    blocking = [c for c in confs if c.severity == "blocking"]
    coordination = [c for c in confs if c.severity == "coordination"]
    req_w, plan_w = as_requested(inst), weeks_by_activity(sub)

# The assistant is intentionally attached to Trackspace's saved result/report,
# not to the legacy Python solver. During comparison it reads Balanced by
# default (then A, then B); once a card is opened it reads that exact card.
assistant_inst, assistant_sub, assistant_sc = inst, None, ""
assistant_scope, assistant_report = "", None
if page == "plan":
    active = st.session_state.get("in_force", {})
    assistant_sub, assistant_sc = sub, sc
    assistant_scope = active.get("provenance", f"Scenario {sc}")
    assistant_report = active.get("trackspace_report")
else:
    for assistant_name in ("Balanced", "Protect the track", "Hit every deadline"):
        candidate = st.session_state.get("outs", {}).get(assistant_name)
        if candidate is not None and candidate.submission.accesses:
            assistant_sub = candidate.submission
            assistant_sc = PLANS[assistant_name]["code"]
            assistant_scope = f"{assistant_name} (Scenario {assistant_sc})"
            assistant_report = candidate.report
            break
with assistant_slot.container():
    scenario_context = {}
    for name, candidate in st.session_state.get('outs', {}).items():
        scenario_context[PLANS[name]['code']] = {
            'name':name, 'status':candidate.status, 'score':candidate.report.get('score'),
            'feasible':candidate.report.get('feasible'), 'lower_bound':candidate.best_bound,
            'overrun_days':candidate.report.get('overrun_days_total'),
            'eclo_accesses':candidate.report.get('eclo_nights_total'),
            'extra_access_nights':candidate.report.get('excess_access_nights_total'),
            'alternatives_searched':bool((candidate.optimality or {}).get('alternative_search_requested')
                                         or (candidate.optimality or {}).get('alternative_search_status')
                                         or candidate.alternatives),
            'alternatives':[{'score':a['score'], 'score_gap':round(a['score']-candidate.objective,1),
                             'feasible':a['report']['feasible']} for a in candidate.alternatives]}
    global_assistant(assistant_inst, assistant_sub, assistant_sc, seconds,
                     assistant_scope, assistant_report, confs, scenario_context)


# ============================================================ PLANNING MODE
if mode == "Plan a future horizon":
    if page == "conflicts":
        st.markdown("#### 1. Check the uploaded programme")
        located = [c for c in confs if getattr(c, "where", "")]
        map_cells = {(c.week, c.where) for c in located}
        undated = [c for c in blocking if not getattr(c, "where", "")]
        stat1, stat2, stat3 = st.columns(3)
        stat1.metric("Rule issues", len(blocking),
                     help="Rule failures at the requested weeks, before ECLO or extra access. "
                          "Includes closures, sharing limits, contractor limits and date order. "
                          "Several rules may flag the same worksite.")
        stat2.metric("Sharing requirements", len(coordination),
                     help="Teams need a shared possession. Other rule issues may still "
                          "require their work to move.")
        stat3.metric("Worksite-weeks flagged", len(map_cells),
                     help="Unique worksite and week pairs. Red means a rule issue; "
                          "amber means shared access is required. Red takes priority.")
        if blocking:
            st.warning(f"{len(blocking)} rule issues need a new plan. Run the optimiser below.")
        elif coordination:
            st.info("The requested weeks pass the checks when teams share access as required.")
        else:
            st.success("No conflicts were found in the programme as requested.")
        if confs:
            st.caption(f"{len(map_cells)} mapped worksite-weeks · {len(undated)} programme-level issues. "
                       "Multiple rules can flag the same worksite.")
            if located:
                embed_html(conflict_map(inst, confs,
                                        hashlib.md5(repr((isomap.VERSION, ENGINE_RULESET, path,
                                                          sorted((c.kind, c.week, c.where, c.severity,
                                                                  c.parties, c.detail) for c in confs))
                                                         ).encode()).hexdigest(), MODE),
                           height=660)
            with st.expander(f"Show all {len(confs)} rule flag(s) as a table",
                             expanded=False):
                st.dataframe(pd.DataFrame(conflict_rows(inst, confs)),
                             width="stretch", hide_index=True, height=360)
        else:
            st.caption("Capacity, buffers, weekly contractor limits and predecessor order all pass "
                       "at the requested dates.")

        st.markdown("#### 2. Run the three-scenario optimiser")
        if st.button("Run the optimiser for A, B and C", type="primary"):
            if build_all_scenarios(path, CP_SAT_TIME_LIMIT_SECONDS):
                st.session_state["ui_page"] = "scenarios"
                st.rerun()
        st.stop()

    outs = st.session_state.get("outs")
    if not outs:
        st.session_state["ui_page"] = "conflicts"
        st.rerun()

    summary = {}
    for name, o in outs.items():
        if not o.submission.accesses:
            summary[name] = None
            continue
        code = PLANS[name]["code"]
        rows = contract_rows(inst, o.submission)
        lt = [r for r in rows if r["overrun_days"]]
        validation = o.report if hasattr(o, "report") else validate(
            inst, o.submission, code, planning_policy)
        if isinstance(validation, dict):
            result_rows = validation.get("results", [])
            overdue = validation["contracts_overrunning"]
            summary[name] = {
                "on_time": len(inst.contracts) - overdue, "total": len(inst.contracts),
                "activities": validation["completed_activities"],
                "overdue_contracts": overdue,
                "overrun_days": validation["overrun_days_total"],
                "worst": max((r["overrun_days"] or 0 for r in result_rows), default=0),
                "eclo": validation["eclo_nights_total"],
                "extra": validation["excess_access_nights_total"],
                "score": o.objective, "ok": validation["feasible"],
            }
        else:
            f = analyse(inst, o.submission, code, o.objective)
            summary[name] = {"on_time": len(rows) - len(lt), "total": len(rows),
                             "activities": len({a.activity_id for a in o.submission.accesses}),
                             "overdue_contracts": len(lt),
                             "overrun_days": sum(r["overrun_days"] for r in rows),
                             "worst": max([r["overrun_days"] for r in lt], default=0),
                             "eclo": f.eclo_nights, "extra": f.excess_nights,
                             "score": o.objective, "ok": validation.feasible}

    live = [n for n in PLANS if summary[n]]
    if not live:
        st.error("None of the three could be scheduled.")
        st.stop()
    best, why = recommend({k: summary[k] for k in live})
    st.markdown(f"<p class='lede'>We suggest <b>{best}</b>. {why[0]}</p>",
                unsafe_allow_html=True)
    st.markdown("#### 3. Scenario recommendation and CSV submissions")
    comparison = []
    for name in PLANS:
        s, o = summary[name], outs[name]
        if s is None:
            comparison.append({
                "Scenario": f"{name} ({PLANS[name]['code']})",
                "Activities scheduled": f"0 / {len(inst.activities)}",
                "Contracts overdue": None, "Contract overrun days": None,
                "ECLO nights": None, "Extra access-nights": None, "Score": None,
                "Valid": "✗", "Result": f"No feasible plan ({o.status})",
            })
        else:
            comparison.append({
                "Scenario": f"{name} ({PLANS[name]['code']})",
                "Activities scheduled": f"{s['activities']} / {len(inst.activities)}",
                "Contracts overdue": s["overdue_contracts"],
                "Contract overrun days": s["overrun_days"],
                "ECLO nights": s["eclo"], "Extra access-nights": s["extra"],
                "Score": round(s["score"], 1),
                "Valid": "✓" if s["ok"] else "✗", "Result": o.status,
            })
    st.dataframe(pd.DataFrame(comparison), width='stretch', hide_index=True)
    with st.expander("Why this one, and what the alternatives give you"):
        for line in why[1:]:
            st.markdown("- " + line)

    cols = st.columns(len(live))
    for col, name in zip(cols, live):
        s, meta = summary[name], PLANS[name]
        cost = []
        if s["worst"]:
            cost.append(f"worst delay {s['worst']} days")
        if s["eclo"]:
            cost.append(f"{s['eclo']} early closures")
        if s["extra"]:
            cost.append(f"{s['extra']} extra nights")
        tag = (f"<span style='font-size:11px;color:{GOOD};font-weight:600'>SUGGESTED</span>"
               if name == best else
               f"<span style='font-size:11px;color:{MUTED}'>alternative</span>")
        col.markdown(
            f"<div class='tile' style='height:100%'>{tag}"
            f"<div style='font-size:16px;font-weight:600;margin:2px 0 6px'>{name}</div>"
            f"<div class='v' style='color:{GOOD if s['on_time'] == s['total'] else WARN}'>"
            f"{s['on_time']} of {s['total']}</div><div class='n'>contracts on time</div>"
            f"<div class='n' style='margin-top:8px'>"
            f"{'Costs ' + ', '.join(cost) if cost else 'Costs nothing'}</div>"
            f"<div class='n' style='margin-top:6px'>{meta['blurb']}</div></div>",
            unsafe_allow_html=True)
        col.button("View this plan in the 3D model", key=f"preview_{name}",
                   width='stretch', type="primary", on_click=preview_plan,
                   args=(outs[name].submission, PLANS[name]["code"], name,
                         outs[name].report if hasattr(outs[name], "report") else None))

        with st.expander(f"Download {name}: 3 CSV outputs"):
            code = PLANS[name]["code"]
            files = outcome_submission_files(outs[name], code)
            st.caption("One CSV for the access schedule, one for location occupancy, "
                       "and one for contract results.")
            download_cols = st.columns(3)
            for download_col, (filename, contents) in zip(download_cols, files.items()):
                download_col.download_button(filename, contents,
                                             file_name=filename, mime="text/csv",
                                             key=f"csv_{code}_{filename}",
                                             width="stretch")
            buf = io.BytesIO()
            with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
                for filename, contents in files.items():
                    z.writestr(filename, contents)
            st.download_button("Download all 3 as a ZIP", buf.getvalue(),
                               file_name=f"submission_{code}.zip",
                               mime="application/zip", key=f"dl_{name}")

    st.markdown("#### 4. Whole-horizon schedule timeline")
    st.caption("Each cell is one planning week. Hover it for the selected platforms, "
               "tunnels and the scenario-policy reason; the table retains every week "
               "for review or export checking.")
    timeline_tabs = st.tabs([f"{name} ({PLANS[name]['code']})" for name in live])
    for tab, name in zip(timeline_tabs, live):
        with tab:
            code, outcome = PLANS[name]["code"], outs[name]
            timeline = scenario_timeline(inst, outcome.submission, code, outcome.report)
            st.altair_chart(scenario_timeline_chart(timeline), width="stretch")
            with st.expander(f"Show every week for {name}", expanded=False):
                st.dataframe(
                    timeline.rename(columns={
                        "week_label": "Week", "dates": "Dates",
                        "activity_count": "Activities",
                        "possession_count": "Possessions",
                        "stations": "Platforms selected", "tunnels": "Tunnels selected",
                        "eclo": "ECLO accesses", "extra_access": "Extra access",
                        "reason": "Why this week",
                    })[["Week", "Dates", "Activities", "Possessions",
                         "Platforms selected", "Tunnels selected", "ECLO accesses",
                         "Extra access", "Why this week"]],
                    width="stretch", hide_index=True, height=420,
                )

    st.markdown("#### 5. Search confidence")
    st.caption("Main plans are ready first. Search for alternatives below only when needed. "
               "Lower scores are better; equal scores are ties, not a confidence percentage.")
    confidence_tabs = st.tabs([f"{name} ({PLANS[name]['code']})" for name in live])
    for tab, name in zip(confidence_tabs, live):
        with tab:
            outcome = outs[name]
            optimality = getattr(outcome, "optimality", None) or {}
            searched = bool(optimality.get('alternative_search_requested') or
                            optimality.get('alternative_search_status') or outcome.alternatives)
            if not searched:
                st.caption("Alternatives have not been searched yet. Your main plan is already validated.")
                if st.button(f"Find up to 3 alternatives for Scenario {PLANS[name]['code']}",
                             key=f"find_alternatives_{PLANS[name]['code']}"):
                    try:
                        with st.spinner("Checking alternatives for this scenario (up to 45 seconds of search)…"):
                            candidates, statuses = search_alternatives(path, PLANS[name]['code'], outcome)
                        outcome.alternatives = candidates
                        outcome.optimality = {**optimality, 'alternative_search_requested':True,
                                              'alternative_search_status':statuses}
                        st.session_state['outs'] = outs
                        st.rerun()
                    except (TrackspaceUnavailable, RuntimeError, ValueError) as exc:
                        st.error(f"Could not finish the alternative search. Your main plan is unchanged. {exc}")
            table = confidence_rows(outcome)
            st.dataframe(table, width="stretch", hide_index=True)
            optimality = getattr(outcome, "optimality", None) or {}
            alternatives = getattr(outcome, "alternatives", [])
            if alternatives:
                st.caption("Alternatives change activity weeks or ECLO choices. These are the best "
                           "found within the search time, not guaranteed rankings. Scores include "
                           "priority-weighted delay and access costs, not just overrun days.")
                with st.expander("Download alternative schedules"):
                    for index, candidate in enumerate(alternatives, 1):
                        buf = io.BytesIO()
                        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
                            for filename, content in candidate["csvFiles"].items():
                                z.writestr(filename, content)
                        st.download_button(f"Alternative {index} — {candidate['score']:.1f} points",
                                           buf.getvalue(), f"scenario_{PLANS[name]['code']}_alternative_{index}.zip",
                                           "application/zip", key=f"alt_{name}_{index}")
            elif "INFEASIBLE" in optimality.get("alternative_search_status", []):
                st.caption("No other activity-week/ECLO schedule exists within the configured model limits.")
            elif searched:
                st.caption("No additional valid schedule was found within the search time.")
            if alternatives and alternatives[0]['score'] < outcome.objective - 0.001:
                st.info("An alternative has a lower score. The original plan and its downloads remain unchanged; the alternative can be downloaded separately.")
            if optimality.get("matches_bound"):
                st.success("Optimal for this encoded Trackspace model and its configured "
                           "horizon/group limits.")
            else:
                bound = float(getattr(outcome, "best_bound", float("nan")))
                if pd.notna(bound):
                    st.info(f"The search stopped before proving optimality. The best score is "
                            f"{outcome.objective:.1f}; the solver has not ruled out a score "
                            f"as low as {bound:.1f}.")
                else:
                    st.caption("The solver returned a feasible plan but no numeric lower bound.")
    if reviewer:
        st.markdown("---")
        st.markdown("#### Technical")
        for name in live:
            o, code = outs[name], PLANS[name]["code"]
            r = o.report if hasattr(o, "report") else validate(
                inst, o.submission, code, planning_policy)
            st.markdown(f"**{name}** (scenario {code}) — {o.status}, "
                        f"score {o.objective:.1f}, "
                        f"{'feasible' if (r['feasible'] if isinstance(r, dict) else r.feasible) else 'INFEASIBLE'}")
    st.stop()

# ====================================================== THE SCHEDULE IN FORCE
st.info(f"**Scenario {sc} preview** — {CODE_TO_NAME.get(sc, sc)}. Not a committed operational schedule.")

# ---- the network, week by week -----------------------------------------------
st.markdown("#### Where the work is, week by week")
# the same split the decisions panel uses: late work someone can still act on
# versus late work nothing in the schedule fixes
_late_kind = {}
_map_key = hashlib.md5(
    repr((isomap.VERSION, sorted(_late_kind.items()),
          sorted((a.activity_id, a.week, a.eclo, a.access_night) for a in sub.accesses),
          sorted((o.activity_id,o.week,o.location_id,o.co_share_group) for o in sub.occupancies))).encode()).hexdigest()
embed_html(
    network_map(inst, sub, min(r["first_week"] for r in crows), _map_key, MODE, _late_kind),
    # The isometric network is wide but also tall at desktop widths.  The old
    # 820px iframe cropped its lower stations and warning pins.
    height=1160)
st.caption("Drag the week, or press play. Colour is the contract's priority; "
           "an amber outline marks nominal capacity; red marks work past its deadline. "
           "Amber ECLO and extra-access markers show scenario choices, not violations.")

st.altair_chart(programme_chart(inst, sub, crows), width='stretch')
st.caption("One row per contract. The black line is the deadline. Bars outlined in "
           "red are past it — those contracts need a decision below. "
           "P1 lateness costs 100× P3.")

# ---- look inside one contract ------------------------------------------------
_c1, _c2 = st.columns([1, 2])
pick = _c1.selectbox("Look inside a contract",
                     ["—"] + [f"{r['who']} ({r['contract']})" for r in crows]
                     + ["All jobs, every contract"],
                     help="A contract is a programme of work; a job is one stretch "
                          "of track inside it. Deadlines belong to contracts; the "
                          "schedule places jobs.")
if pick != "—":
    if pick.startswith("All jobs"):
        st.altair_chart(job_chart(inst, sub, crows), width='stretch')
        st.caption(f"All {len(inst.activities)} jobs. ▲ = high priority within its "
                   "contract, which decides which of that contract's jobs gives way "
                   "first and never outranks another contract.")
    else:
        cn_pick = pick.rsplit("(", 1)[-1].rstrip(")")
        r = next(r for r in crows if r["contract"] == cn_pick)
        jobs = [a for a, x in inst.activities.items() if x.contract_number == cn_pick]
        late_jobs = [x for x in rep.get('activityResults', [])
                     if inst.activities[x['activity_id']].contract_number == cn_pick and x['overrun_days']]
        _c2.markdown(
            f"<div style='padding-top:28px;color:{MUTED}'>"
            f"<b style='color:{INK}'>{r['who']}</b> · {PRIORITY[r['priority']]} · "
            f"{len(jobs)} job(s), {r['nights']} nights, weeks {r['first_week']}–"
            f"{r['last_week']} · due {r['due']:%d %b} · "
            + (f"<b style='color:{CRIT}'>{len(late_jobs)} job(s) late</b>"
               if late_jobs else f"<b style='color:{GOOD}'>on time</b>")
            + "</div>", unsafe_allow_html=True)
        st.altair_chart(job_chart(inst, sub, crows, only=cn_pick), width='stretch')
        st.caption("▲ = high priority within this contract: if two of its jobs compete, "
                   "the other gives way. Hover a bar for the worksite and night type.")

attention = attention_items(inst, sub, rep)
ICON = {"act": "🔴", "known": "⚪", "watch": "🟡", "ok": "✅"}
HEAD = {"act": CRIT, "known": MUTED, "watch": WARN, "ok": GOOD}
pending = st.session_state.get("options")
def _action_card(it):
    with st.container(border=True):
        st.markdown(f"<div style='border-left:4px solid {HEAD[it['severity']]};"
                    f"padding-left:10px;margin:-4px 0 6px'>{ICON[it['severity']]} "
                    f"<b style='color:{HEAD[it['severity']]};font-size:16px'>"
                    f"{it['title']}</b></div>", unsafe_allow_html=True)
        st.markdown(f"<span style='color:{MUTED};font-size:14px'>{it['detail']}</span>",
                    unsafe_allow_html=True)
        if it.get("job"):
            b1, b2 = st.columns([1, 1])
            if b1.button("Propose a swap that brings it forward",
                         key=f"fix_{it['job']}", type="primary"):
                with st.spinner("Working out the smallest change…"):
                    st.session_state["proposal"] = (
                        pull_earlier(inst, sub, sc, it["job"], seconds=min(seconds, 20)),
                        f"fix_{it['job']}")
            if b2.button("Show what is in the way", key=f"why_{it['job']}"):
                for w in range(it["floor"], it["last"]):
                    rs = why_not_week(inst, sub, it["job"], w)
                    st.markdown(f"**Week {w}:** " + "; ".join(rs))
            pr = st.session_state.get("proposal")
            if pr and pr[1] == f"fix_{it['job']}":
                proposal_card(pr[0], pr[1])
        elif it["severity"] == "known":
            if st.button("Draft the note to each contractor", key="note_known"):
                for j in it["jobs"]:
                    with st.container(border=True):
                        st.markdown(f"**To {j['contractor']}** — about their job on the "
                                    f"{j['where']} ({j['job']})")
                        st.markdown(
                            f"Your request for {j['nights']} night(s) from week "
                            f"{j['earliest']} cannot finish before week {j['floor']}, "
                            f"which is {j['over']} days past the week-{j['deadline']} "
                            f"completion date. No arrangement of other work changes "
                            f"that — it is the calendar, not congestion.")
                        st.markdown("Three ways to resolve it. Please tell us which:")
                        st.markdown(f"1. **Accept a revised completion date** of "
                                    f"{j['floor_date']}.")
                        st.markdown(f"2. **Start earlier** — from week "
                                    f"{j['deadline'] - j['nights'] + 1} at the latest, "
                                    f"if your mobilisation allows.")
                        st.markdown(f"3. **Split the work** — {j['fits']} night(s) before "
                                    f"the deadline, the remainder under a follow-on "
                                    f"period.")
                        st.caption("Copy this into your usual channel. The dates are "
                                   "from the schedule in force.")
            st.caption("→ " + it["action"])
        elif it["severity"] == "watch":
            if st.button(f"Who to confirm with for week {it['week']}", key=f"wk_{it['week']}"):
                b_ = week_board(inst, sub, it["week"])
                full = [r for r in b_ if r['location'] in it['locations']]
                names = sorted({inst.contracts[c["contract"]].contract_description
                                for r in full for c in r["crew"]})
                st.markdown(f"**{len(names)} contractors on worksites at their limit in "
                            f"week {it['week']}** ({inst.week_start(it['week']):%d %b} – "
                            f"{inst.week_end(it['week']):%d %b}):")
                for nm in names:
                    st.markdown(f"- {nm}")
                st.caption("Confirm crews, access and any early-closure need with each "
                           "by the Thursday before. Then open **This week** and set the "
                           f"slider to {it['week']} for the full board.")
            st.caption("→ " + it["action"])
        elif it["action"]:
            st.caption("→ " + it["action"])


# A programme with two dozen late contracts produces two dozen cards. Lead with
# a count and the few worth acting on; the rest stay one click away.
_ACT = [i for i in attention if i["severity"] == "act"]
_KNOWN = [i for i in attention if i["severity"] == "known"]
_WATCH = [i for i in attention if i["severity"] == "watch"]
_OK = [i for i in attention if i["severity"] == "ok"]

st.markdown("#### Recommended actions")
if _OK and not (_ACT or _KNOWN):
    st.success("**Nothing needs a decision.** Every contract lands on time.")
    for it in _WATCH:
        st.caption(f"⚠ {it['title']} — {it['action']}")
else:
    bits = []
    if _ACT:
        bits.append(f"**{len(_ACT)}** contracts finish late in this plan")
    if _KNOWN:
        n = sum(len(i.get("jobs") or [1]) for i in _KNOWN)
        bits.append(f"**{n}** cannot finish on time whatever is done")
    if _WATCH:
        bits.append(f"**{len(_WATCH)}** weeks with nominal-capacity alerts")
    st.markdown(" · ".join(bits))

    SHOWN = 3
    ordered = _ACT + _KNOWN + _WATCH
    for it in ordered[:SHOWN]:
        _action_card(it)
    rest = ordered[SHOWN:]
    if rest:
        with st.expander(f"Show the other {len(rest)}"):
            for it in rest:
                _action_card(it)

log = st.session_state.get("changelog", [])
if log:
    with st.expander(f"Changes made since the committed schedule ({len(log)})"):
        for e in reversed(log):
            st.markdown(f"**{e['when']}** — {e['what']}  ·  cost {e['cost']:+.1f}")
            for s in e["steps"]:
                st.caption("  " + s)
if pending:
    opts = [o for o in pending[0] if o.fits]
    with st.container(border=True):
        st.markdown(f"🔵 **<span style='color:{P[1]}'>A request is waiting on a "
                    f"decision</span>**", unsafe_allow_html=True)
        st.markdown(f"<span style='color:{MUTED};font-size:14px'>"
                    + (f"{len(opts)} way(s) to take it have been worked out."
                       if opts else "It cannot be taken under this schedule.")
                    + "</span>", unsafe_allow_html=True)
        st.caption("→ See the **New request** tab.")
st.markdown("")

T = st.tabs(["This week", "New request", "Contracts", "How clashes were settled"]
            + (["Technical"] if reviewer else []))

# ------------------------------------------------------------------ the week
with T[0]:
    v1, v2 = st.columns([1, 2])
    view = v1.selectbox("Show", ["Everyone on the network"]
                        + [f"{r['who']} ({r['contract']})" for r in crows],
                        label_visibility="collapsed")
    schedule_end = max((a.week for a in sub.accesses), default=inst.horizon_weeks)
    wk = v2.slider("Week", 1, schedule_end,
                   min(r["first_week"] for r in crows),
                   help="Week of the programme")
    st.caption(f"{inst.week_start(wk):%a %d %b} – {inst.week_end(wk):%a %d %b %Y}")

    if view == "Everyone on the network":
        board = week_board(inst, sub, wk)
        if not board:
            st.info(f"No work booked in week {wk}.")
        else:
            st.markdown(f"**{len({c['activity'] for r in board for c in r['crew']})} activities** across "
                        f"**{len({r['location'] for r in board})} worksites**, "
                        f"{len({r['location'] for r in board if r['sharing']})} of them shared.")
            st.dataframe(pd.DataFrame([{
                "Worksite": loc_label(r["location"]), "Type": r["kind"],
                "Teams": r["team_count"],
                "Sharing?": "shared" if r["sharing"] else "sole use",
                "Who's on site": ", ".join(
                    inst.contracts[m["contract"]].contract_description
                    for m in r["crew"]),
                "Work": ", ".join(sorted({m["nature"] for m in r["crew"]})),
                "Late finish?": "ECLO" if r["eclo"] else "",
            } for r in sorted(board, key=lambda r: (r["kind"], r["location"]))]),
                width='stretch', hide_index=True)
            if 'footprints' not in rep:
                st.caption("Rerun Trackspace to load its current closure footprints; legacy buffers are not shown.")
            cl = [x for x in closures_for_week(inst, sub, wk, footprints=rep.get('footprints', {})) if x["closed"]]
            if cl:
                with st.expander(f"Track kept clear by safety buffers ({len(cl)})"):
                    for x in cl:
                        st.markdown(f"**{N.contract(inst, x['contract'])}** "
                                    f"({x['nature']}) closes "
                                    + ", ".join(loc_label(l) for l in x["closed"][:6])
                                    + (" …" if len(x["closed"]) > 6 else ""))
    else:
        cn_ = view.rsplit("(", 1)[-1].rstrip(")")
        order = crew_order(inst, sub, cn_, footprints=rep.get('footprints', {}))
        st.markdown(f"### Working orders — {order['description']} ({order['contract']})")
        st.caption(f"{order['nature']} · access type {order['access_type']} · up to "
                   f"{order['weekly_allowance']} nights a week with {order['teams']} "
                   f"team(s) · due {order['due']:%d %b %Y}")
        this_week = [w for w in order["weeks"] if w["week"] == wk]
        if not this_week:
            nxt = [w["week"] for w in order["weeks"] if w["week"] > wk]
            st.info(f"{order['description']} is not out in week {wk}."
                    + (f" Next out in week {nxt[0]}." if nxt else " Programme complete."))
        for w in this_week:
            for j in w["jobs"]:
                with st.container(border=True):
                    st.markdown(f"**{N.place(j['from'])}"
                                + ("" if j["from"] == j["to"]
                                   else f" → {N.place(j['to']).split(', ')[-1]}")
                                + f"** ({j['activity']}) · week {w['week']}, "
                                f"{w['from']:%a %d %b} – {w['to']:%a %d %b}"
                                + ("  ·  ⚠️ **early closure / late opening**"
                                   if j["eclo"] else ""))
                    st.caption(N.job_priority(inst, j["activity"]))
                    st.markdown("**Worksites** — "
                                + " · ".join(loc_label(l) for l in j["locations"]))
                    st.markdown(("**Sharing the possession with** — "
                                 + ", ".join(inst.contracts[c_].contract_description
                                             for c_ in j["sharing_with"]))
                                if j["sharing_with"] else
                                "**Sole use** — nobody else on these worksites.")
                    if j["must_keep_clear"]:
                        st.markdown("**Keep clear (safety buffer)** — "
                                    + " · ".join(loc_label(l)
                                                 for l in j["must_keep_clear"][:8])
                                    + (" …" if len(j["must_keep_clear"]) > 8 else ""))
        st.markdown("**Whole programme for this contractor**")
        st.dataframe(pd.DataFrame([{
            "Week": w["week"], "Dates": f"{w['from']:%d %b} – {w['to']:%d %b}",
            "Jobs": ", ".join(j["activity"] for j in w["jobs"]),
            "Worksites": sum(len(j["locations"]) for j in w["jobs"]),
            "Sharing with": ", ".join(sorted({inst.contracts[c].contract_description
                                              for j in w["jobs"]
                                              for c in j["sharing_with"]})) or "—",
            "Early closure": "yes" if any(j["eclo"] for j in w["jobs"]) else "",
        } for w in order["weeks"]]), width='stretch', hide_index=True)

# ------------------------------------------------------------------ clashes
with T[3]:
    st.caption("Contractors ask without seeing each other's requests. This is where "
               "those requests collided, and what the schedule did about each one.")
    if blocking:
        st.markdown(f"**{len(blocking)} request(s) could not be met as asked**")
        for cf in blocking:
            with st.container(border=True):
                st.markdown(f"🔴 **{cf.label}** — week {cf.week}"
                            + (f" · {loc_label(cf.where)}" if cf.where else ""))
                st.markdown(cf.detail)
                st.caption("Schedule changes: " + requested_changes(cf, req_w, plan_w))
    else:
        st.success("Every request could be met as asked.")

    if coordination:
        with st.expander(f"{len(coordination)} sharing requirements in the original requests"):
            st.dataframe(pd.DataFrame([{
            "Week": cf.week, "Worksite": loc_label(cf.where),
            "Teams": len(cf.parties), "Contracts": ", ".join(cf.contracts),
            "Schedule changes": requested_changes(cf, req_w, plan_w),
            } for cf in sorted(coordination, key=lambda c: (-len(c.parties), c.week))]),
                width='stretch', hide_index=True, height=300)

# ------------------------------------------------------------------ request
with T[1]:
    st.info("This is a read-only Trackspace preview. Update the input CSVs and rerun A/B/C to evaluate a new request. No legacy solver will change this plan.")

# ------------------------------------------------------------ contracts
with T[2]:
    st.dataframe(pd.DataFrame([{
        "Programme": f"{r['who']} ({r['contract']})",
        "Priority": PRIORITY[r["priority"]],
        "Work": r["nature"], "Nights": r["nights"],
        "Runs": f"wk {r['first_week']}–{r['last_week']}",
        "Due": r["due"].strftime("%d %b %Y"),
        "Finishes": r["finishes"].strftime("%d %b %Y"), "Status": r["status"],
    } for r in crows]), width='stretch', hide_index=True)

    st.caption("Earlier completion is not tested by this view. Rerun Trackspace with revised inputs to evaluate a change.")

# ------------------------------------------------------------------ technical
if reviewer:
    with T[4]:
        st.caption("For reviewers checking the solver rather than running the night.")
        st.success(f"Scenario {sc}: bundled Trackspace validation passed — no hard violations.")
        st.json({k:v for k,v in rep.items() if k != "footprints"})
        st.caption("This is the bundled handoff validator, not external certification.")
        with st.expander("Every access, as scheduled"):
            st.dataframe(pd.DataFrame([{
                "activity": a.activity_id, "seq": a.access_seq, "week": a.week,
                "eclo": int(a.eclo), "access_night": a.access_night}
                for a in sub.accesses]), width='stretch', height=320, hide_index=True)

# Export the schedule in force.
_tmp = Path(tempfile.mkdtemp()) / sc
save_submission(sub, _tmp)
_buf = io.BytesIO()
with zipfile.ZipFile(_buf, "w", zipfile.ZIP_DEFLATED) as _z:
    for _f in sorted(_tmp.iterdir()):
        _z.write(_f, arcname=f"{sc}/{_f.name}")
_plan_name = CODE_TO_NAME.get(sc, sc)
with download_slot.container():
    st.download_button(f"Download Scenario {sc} \u2014 3 CSVs", _buf.getvalue(),
                       file_name=f"schedule_{sc}.zip", mime="application/zip",
                       width='stretch', type="primary")
    st.caption(f"{_plan_name}: access schedule, occupancy and contract results.")
