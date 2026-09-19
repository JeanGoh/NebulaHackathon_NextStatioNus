"""Regressions for the active Trackspace pipeline (not the legacy solver)."""
import ast
import importlib.util
import re
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pandas as pd

from trackaccess import isomap
from trackaccess.conflicts import Conflict
from trackaccess.model import load_instance

ROOT = Path(__file__).resolve().parents[1]


def test_node_handoff_pipeline():
    result = subprocess.run(['node', str(ROOT/'tests/trackspace-regressions.mjs'), sys.executable],
                            capture_output=True, text=True, timeout=100)
    assert result.returncode == 0, result.stderr


def test_joint_weekly_grouping():
    spec = importlib.util.spec_from_file_location('request_groups', ROOT/'vendor/trackspace/check-request-groups.py')
    checker = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(checker)
    # Disjoint jobs may share a contractor access; counting connected components
    # as separate accesses would wrongly reject this request.
    week = {'week':1, 'activities':['a','b'], 'share':[],
            'limits':[{'members':[0,1], 'cap':1, 'fronts':2}]}
    assert checker.check([week]) == []
    week['share'] = [[0,1]]
    week['limits'][0]['fronts'] = 1
    assert checker.check([week]) == [1]
    # Each budget passes alone but the linked constraints cannot all hold.
    week = {'week':2, 'activities':['a','b','c'], 'share':[],
            'limits':[{'members':[0,1], 'cap':1, 'fronts':2},
                      {'members':[1,2], 'cap':1, 'fronts':2},
                      {'members':[0,2], 'cap':2, 'fronts':1}]}
    assert checker.check([week]) == [2]


def test_map_red_wins_and_contract_cells_are_deduplicated():
    inst = load_instance(ROOT/'PS1/01_data')
    loc = next(iter(inst.locations))
    red = Conflict('buffer',1,loc,['A001'],['C001'],'Closure clash')
    amber = Conflict('contention',1,loc,['A002'],['C001'],'Shared access',severity='coordination')
    for findings in ([red,amber], [amber,red]):
        state = isomap.conflict_states(inst,findings)[1][loc]
        assert state[4] & 16
        assert not state[4] & 64
        assert state[1] == 2
        assert 'Closure clash' in state[5] and 'Shared access' in state[5]
        data = isomap.payload(inst,None,conflicts=findings)
        assert data['conflictFlagCount'] == 2
        assert data['alertSummary'][0]['hard'] == 1
        assert data['alertSummary'][0]['share'] == 0
        assert data['alertSummary'][0]['hardWeeks'] == [1]
        assert data['alertSummary'][0]['shareWeeks'] == []
    html = isomap.render(inst,None,1,conflicts=[red,amber],mode='dark')
    for script in re.findall(r'<script[^>]*>(.*?)</script>', html, re.S):
        checked = subprocess.run(['node','--check'],input=script,
                                 capture_output=True,text=True,timeout=10)
        assert checked.returncode == 0, checked.stderr


def test_confidence_table_contains_real_alternatives_not_bound():
    tree = ast.parse((ROOT/'app.py').read_text())
    function = next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='confidence_rows')
    namespace = {'pd':pd}
    exec(compile(ast.Module(body=[function],type_ignores=[]),str(ROOT/'app.py'),'exec'),namespace)
    out = SimpleNamespace(objective=10,best_bound=5,report={'overrun_days_total':14},
                          alternatives=[{'score':12,'report':{'overrun_days_total':7}}])
    table = namespace['confidence_rows'](out)
    assert list(table['Plan']) == ['Chosen plan','Alternative 1']
    assert list(table['Score']) == [10,12]
    assert table.iloc[1]['Score difference'] == '+2.0'
