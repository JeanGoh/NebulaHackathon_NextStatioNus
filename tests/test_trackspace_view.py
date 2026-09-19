"""Selected-page and Ask API grounding regressions; no paid API calls."""
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from trackaccess import agent, isomap
from trackaccess.board import closures_for_week, crew_order
from trackaccess.model import load_instance
from trackaccess.submission import Access, Occupancy, Result, Submission
from trackaccess.trackspace_view import schedule_summary, attention_items, requested_changes

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def plan():
    inst = load_instance(ROOT/'PS1/01_data')
    locs = list(inst.locations)[:3]
    sub = Submission([Access('A001',1,1,True,1)],
                     [Occupancy('A001',1,l,'w1n1') for l in locs],
                     [Result('B','C001',inst.week_end(1),0)])
    report = {'feasible':True,'hard_violations':[],'score':5,
              'eclo_nights_total':1,'excess_access_nights_total':0,
              'contracts_overrunning':0,'overrun_days_total':0,
              'results':[{'contract_number':'C001','simulated_completion_date':str(inst.week_end(1)),'overrun_days':0}],
              'utilization':[{'week':1,'location_id':l,'used':1,'capacity':1,'excess':0} for l in locs],
              'footprints':{'A001':{'workLocations':locs[:2],'exclusion':locs}}}
    return inst, sub, report


def test_eclo_not_multiplied_by_footprint(plan):
    inst,sub,report=plan
    facts=schedule_summary(inst,sub,report)
    assert facts['eclo_accesses']==1
    assert sum(r['worst'] for r in facts['eclo_by_contract'])==1
    payload=isomap.payload(inst,sub)
    assert payload['scheduleSummary']['eclo_accesses']==1
    assert payload['scheduleSummary']['extra_access_nights']==0
    items=attention_items(inst,sub,report)
    assert items[0]['title']=='Week 1: 3 worksites at or above nominal capacity'
    assert 'nowhere' not in str(items) and 'no slack' not in str(items)


def test_closures_and_orders_use_engine_footprints(plan,monkeypatch):
    inst,sub,report=plan
    from trackaccess.network import Network
    def forbid(*args,**kwargs):
        raise AssertionError('Legacy footprint used')
    monkeypatch.setattr(Network,'expand',forbid)
    monkeypatch.setattr(Network,'buffer_locations',forbid)
    cl=closures_for_week(inst,sub,1,footprints=report['footprints'])
    assert cl[0]['closed']==report['footprints']['A001']['exclusion'][2:]
    order=crew_order(inst,sub,'C001',footprints=report['footprints'])
    assert len(order['weeks'][0]['jobs'][0]['locations'])==3


def test_tools_cannot_fall_back_or_double_count(plan,monkeypatch):
    inst,sub,report=plan
    def forbid(*args,**kwargs):
        raise AssertionError('Legacy computation used')
    for name in ('detect','solve','why_not_week','pull_earlier','fit_request'):
        monkeypatch.setattr(agent,name,forbid)
    box=agent.Toolbox(inst,sub,'B',trackspace_report=report)
    summary=json.loads(box.run('get_plan_summary',{}))
    assert summary['scenario']=='B' and summary['score']==5 and summary['is_preview']
    assert summary['eclo_accesses']==1
    week=json.loads(box.run('get_week',{'week':1}))
    assert week['activities']==1 and week['eclo_accesses']==1
    assert week['possessions']==1 and week['worksite_possessions']==3
    assert 'error' in json.loads(box.run('list_conflicts',{}))
    assert 'error' in json.loads(box.run('propose_change',{'goal':'bring_forward','activity_id':'A001'}))


def test_api_request_is_grounded_in_selected_scenario(plan,monkeypatch):
    inst,sub,report=plan
    import anthropic
    calls=[]
    def create(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(stop_reason='end_turn',content=[SimpleNamespace(type='text',text='Scenario B has 1 ECLO access.')])
    monkeypatch.setattr(anthropic,'Anthropic',lambda:SimpleNamespace(messages=SimpleNamespace(create=create)))
    monkeypatch.setattr(agent,'available',lambda:True)
    box=agent.Toolbox(inst,sub,'B',trackspace_report=report,trackspace_conflicts=[],
                      trackspace_scenarios={'B':{'score':5,'alternatives':[{'score':5,'score_gap':0}]}})
    answer,_=agent.ask(box,'How much ECLO?')
    assert answer=='Scenario B has 1 ECLO access.'
    system=calls[0]['system']
    assert '"scenario": "B"' in system and '"eclo_accesses": 1' in system
    assert '"score_gap": 0' in system
    assert {t['name'] for t in calls[0]['tools']}=={'get_plan_summary','get_scenarios','find_locations','get_week','get_contracts','list_conflicts'}


def test_unchanged_weeks_do_not_invent_resolution():
    conflict=SimpleNamespace(parties=['A001'])
    text=requested_changes(conflict,{'A001':[1]},{'A001':[1]})
    assert 'retained' in text and 'packing' not in text


def test_map_fits_frame_without_changing_schedule_data(plan):
    import re
    import subprocess
    inst, sub, _ = plan
    for conflicts in (None, []):
        expected = isomap.payload(inst, sub, conflicts=conflicts)
        html = isomap.render(inst, sub, conflicts=conflicts)
        embedded = json.loads(re.search(r'const D = (.*);', html).group(1))
        assert embedded == json.loads(json.dumps(expected))
        assert 'preserveAspectRatio="xMidYMid meet"' in html
        assert 'flex:1 1 0;min-height:0' in html
        assert 'height:auto' not in html
        assert 'Expand programme details' in html
        assert 'Collapse programme details' in html
        assert 'summary::before{content:"↓"' in html
        assert '[open] > summary::before{content:"↑"' in html
        assert 'More details below' in html
        assert 'body.scrollHeight - body.clientHeight - body.scrollTop <= 2' in html
        assert '@media(prefers-reduced-motion:reduce)' in html
        assert '<details id="legend-details"><summary>' in html
        for control in ('fit', 'zoom-in', 'zoom-out', 'fullscreen'):
            assert f'id="{control}"' in html
        for script in re.findall(r'<script[^>]*>(.*?)</script>', html, re.S):
            checked = subprocess.run(['node', '--check'], input=script,
                                     capture_output=True, text=True)
            assert checked.returncode == 0, checked.stderr


def test_programme_chips_expand_and_collapse_repeatedly():
    """Exercise the real JS handler without requiring a browser installation."""
    import subprocess
    function = isomap._SHELL.split('function addChips(row, list, cls){', 1)[1]
    function = 'function addChips(row, list, cls){' + function.split('\nfunction bannerRow', 1)[0]
    harness = r'''
const assert = require('node:assert/strict');
function element(){return {children:[],style:{},attrs:{},hidden:false,
  appendChild(child){this.children.push(child);},
  setAttribute(key,value){this.attrs[key]=value;},
  getAttribute(key){return this.attrs[key];}};}
const document={createElement:element}, slider={value:1}, CHIPS_SHOWN=3;
let week=1;
function draw(w){week=w;}
const entries=Array.from({length:13},(_,i)=>({who:'Programme '+i,worst:13-i,weeks:[i+1]}));
const red=element(), amber=element();
addChips(red,entries,''); addChips(amber,entries,'share');
const footer=red.children.at(-1);
assert.equal(footer.className,'chip-toggle-row');
const toggle=footer.children[0];
assert.equal(toggle.textContent,'+ 10 more');
for(let i=0;i<3;i++){
  toggle.onclick();
  assert.equal(toggle.textContent,'Show less');
  assert.equal(toggle.getAttribute('aria-expanded'),'true');
  assert.equal(red.children.filter(c=>!c.hidden).length,14);
  assert.equal(amber.children.filter(c=>!c.hidden).length,4);
  red.children.at(-2).onclick(); assert.equal(week,13);
  assert.equal(red.children.at(-1),footer);
  toggle.onclick();
  assert.equal(toggle.textContent,'+ 10 more');
  assert.equal(toggle.getAttribute('aria-expanded'),'false');
  assert.equal(red.children.filter(c=>!c.hidden).length,4);
  assert.equal(red.children.length,14);
}
const short=element(); addChips(short,entries.slice(0,3),'');
assert.equal(short.children.length,3);
const empty=element(); addChips(empty,[],''); assert.equal(empty.children.length,0);
'''
    result = subprocess.run(['node', '-e', function + harness],
                            capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_map_station_labels_identify_their_actual_platforms(plan):
    inst, sub, _ = plan
    data = isomap.payload(inst, sub)
    stations = [label for label in data['labels'] if not label.get('big')]
    platforms = {loc for loc in data['anchors'] if loc.startswith('PLAT:')}
    assert {loc for label in stations for loc in label['locations']} == platforms
    assert len(stations) == len(inst.stations)
    for label in stations:
        points = [data['anchors'][loc] for loc in label['locations']]
        assert label['x'] == round(sum(p[0] for p in points)/len(points), 1)
        assert label['y'] == round(sum(p[1] for p in points)/len(points), 1)
        assert all(f":{label['t']}:" in loc for loc in label['locations'])
    html = isomap.render(inst, sub)
    assert html.index('<g id="labels"') > html.index('<g id="markers"')
    assert 'if(!L.big)' in html
    assert 'stroke:"#6b62c9","stroke-width":1.4' in isomap._SHELL
    assert 'tag.textContent = "Interchange"' not in html
    assert all(' · ' in lane['t'] for lane in data['lanes'])
    for lane in data['lanes']:
        assert lane['y'] == round(lane['target'][1] - 28, 1)
        assert lane['x'] == lane['target'][0]
        assert lane['a'] == 'middle'
        assert any(loc.startswith(f"PLAT:{lane['line']}:") and
                   loc.endswith(f":{lane['bound']}") and anchor == lane['target']
                   for loc, anchor in data['anchors'].items())
    for heading in (label for label in data['labels'] if label.get('big')):
        line = next(key for key, name in inst.lines.items() if name == heading['t'])
        directions = [lane for lane in data['lanes'] if lane['line'] == line]
        assert heading['y'] <= min(lane['y'] for lane in directions) - 14
