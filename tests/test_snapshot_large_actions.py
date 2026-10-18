"""Run the complete snapshot with a minimal DOM and large native-select candidates."""

import json
import subprocess
from pathlib import Path

import pytest

SNAPSHOT = Path(__file__).resolve().parents[1] / "jev_ultrafast" / "snapshot.js"
DOM = r"""
const fs = require('node:fs');
const [source, offered, obscured] = process.argv.slice(1);
global.window = {};
global.location = {href: 'https://fixture.invalid/'};
global.scrollX = global.scrollY = 0;
global.innerWidth = 1120; global.innerHeight = 768;
global.NodeFilter = {SHOW_TEXT: 4};
const body = {innerText: '', scrollHeight: 768};
function control(tagName, y, count, label) {
  const e = {
    tagName, type: tagName === 'SELECT' ? 'select-one' : 'button',
    value: '', checked: false, selectedIndex: -1, disabled: false, readOnly: false,
    isConnected: true, parentElement: body, labels: [], childNodes: [],
    checkVisibility: () => true, matches: () => false,
    closest: s => s === 'input,select,textarea' && tagName === 'SELECT' ? e : null,
    getAttribute: key => key === 'aria-label' ? label : null,
    hasAttribute: () => false, querySelector: () => null,
    contains: other => other === e,
    getBoundingClientRect: () => ({x:20, y, width:300, height:30, right:320, bottom:y+30}),
    getClientRects: () => [e.getBoundingClientRect()],
    options: Array.from({length: count}, (_, i) => ({
      value: String(i), label: `Option ${i}`, selected: false, disabled: false,
      closest: () => null,
    })),
    selectedOptions: [],
  };
  return e;
}
const select = control('SELECT', 20, Number(offered), 'Choices');
const covered = control('SELECT', 60, Number(obscured), 'Covered');
const button = control('BUTTON', 100, 0, 'Continue');
const selects = [select, covered];
global.document = {
  body, documentElement: body, title: 'Large select fixture',
  getElementById: () => null,
  querySelectorAll: selector => selector === 'input,textarea,select' ? selects :
    selector.startsWith('a[href]') ? [...selects, button] : [],
  createTreeWalker: () => ({nextNode: () => null}), createRange: () => ({}),
  elementFromPoint: (x, y) => y >= 20 && y < 50 ? select : y >= 100 && y < 130 ? button : null,
};
global.getComputedStyle = () => ({overflowY: 'visible'});
const page = eval(fs.readFileSync(source, 'utf8'));
console.log(JSON.stringify({
  actions: page.actions.map(a => ({id:a.id, kind:a.kind, label:a.label, value:a.value})),
  semanticCount: page.marker[8].length,
  coveredInSemantics: page.marker[8].filter(a => a.label.startsWith('Covered')).length,
  guardCount: Object.keys(page.guards).length,
  omitted: page.omitted_actions,
}));
"""


def snapshot(source, offered, covered):
    result = subprocess.run(
        ["node", "-e", DOM, str(source), str(offered), str(covered)],
        capture_output=True, text=True, check=True,
    )
    return json.loads(result.stdout)


@pytest.mark.parametrize("offered,covered", [(3, 7), (150_000, 7), (0, 150_000)])
def test_snapshot_keeps_order_semantics_and_cap_with_many_options(offered, covered):
    page = snapshot(SNAPSHOT, offered, covered)
    actions = page["actions"]
    assert len(actions) == min(offered + 2, 250)
    assert actions[-1] == {"id": "wait", "kind": "wait", "label": "Wait for the page to update"}
    elements = actions[:-1]
    select_count = min(offered, 249)
    assert [a["value"] for a in elements[:select_count]] == [str(i) for i in range(select_count)]
    assert [a["id"] for a in elements] == [f"e{i + 1}" for i in range(len(elements))]
    assert all(a["label"].startswith("Choices") for a in elements[:select_count])
    if offered < 249:
        assert elements[-1]["label"] == "Continue"
    assert page["semanticCount"] == offered + covered + 1
    assert page["coveredInSemantics"] == covered
    assert page["guardCount"] == (2 if offered else 1)
    assert page["omitted"] == offered + 2 - len(actions)
