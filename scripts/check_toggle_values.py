"""Read checkbox/radio/switch states in a real browser; no model or remote site."""

import json
from urllib.parse import quote

from jev_ultrafast.browser import Browser

HTML = """<!doctype html><title>Toggle values</title>
<label><input id="box" type="checkbox" value="true"> Enable feature</label>
<label><input type="radio" name="mode" value="public"> Public</label>
<label><input type="radio" name="mode" value="private" checked> Private</label>
<button role="switch" aria-checked="false" onclick="this.setAttribute('aria-checked','true')">Switch</button>
<button id="pressed" aria-pressed="false" onclick="this.setAttribute('aria-pressed','true')">Pinned</button>
<button id="expanded" aria-expanded="false">Details</button>
<div role="tab" aria-selected="true">Overview</div>
<div contenteditable="true" aria-label="Notes">Current note</div>
<label>Visibility<select><option value="1">Public</option><option value="2" selected>Private</option></select></label>
<ul><li role="option" aria-selected="true">Example choice</li></ul>
<a href="https://example.test/path?token=signed-secret#private">Signed link</a>
<label>Text<input type="text" value="true"></label>
<label><input type="checkbox" checked disabled> Disabled feature</label>
<input type="radio" name="unnamed" value="option-A">
<input type="radio" name="defaults">
<label><input type="radio" name="duplicate" value="one">Option</label>
<label><input type="radio" name="duplicate" value="two">Option</label>
<input id="secret-password" type="password" value="must-not-leak">
<input id="secret-hidden" type="hidden" value="must-not-leak">
<div style="margin-top:1800px"><button onclick="window.activated=true">Outside button</button></div>
"""


def main():
    browser = Browser("data:text/html," + quote(HTML))
    try:
        page = browser.observe(screenshot=False)
        by_label = {a["label"]: a for a in page["actions"]}
        assert by_label["Enable feature"]["checked"] == by_label["Enable feature"]["value"] == "false"
        assert by_label["Public"]["checked"] == by_label["Public"]["value"] == "false"
        assert by_label["Private"]["checked"] == by_label["Private"]["value"] == "true"
        assert by_label["Switch"]["checked"] == by_label["Switch"]["value"] == "false"
        assert by_label["Text"]["value"] == "true"
        assert by_label["radio (option-A)"]["submission_value"] == "option-A"
        assert by_label["radio"]["value"] == "false"
        duplicates = [a for a in page["actions"] if a["label"] == "Option"]
        assert [a["submission_value"] for a in duplicates] == ["one", "two"]
        assert all(a["value"] == "false" for a in duplicates)
        assert "Disabled feature" not in by_label
        facts = {f["label"]: f for f in page["observed_controls"]}
        assert facts["Disabled feature"]["checked"] == "true" and facts["Disabled feature"]["disabled"]
        facts = {f["label"]: f for f in page["observed_controls"]}
        assert facts["Pinned"]["pressed"] == facts["Pinned"]["value"] == "false"
        assert facts["Details"]["expanded"] == "false"
        assert facts["Overview"]["selected"] == "true"
        assert facts["Notes"]["value"] == "Current note"
        assert facts["Visibility"]["value"] == "Private"
        assert facts["Example choice"]["value"] == "Example choice"
        assert by_label["Visibility → Public"]["current_value"] == "Private"
        assert "must-not-leak" not in json.dumps(page["observed_controls"])
        assert by_label["Signed link"]["destination"] == "https://example.test/path"
        assert "signed-secret" not in json.dumps(page["actions"])
        outside = by_label["Outside button"]
        assert outside["kind"] == "reveal"
        browser.act(by_label["Enable feature"], page)
        after = browser.observe(screenshot=False)
        box = next(a for a in after["actions"] if a["label"] == "Enable feature")
        assert box["checked"] == box["value"] == "true"
        assert browser.evaluate("document.getElementById('box').value") == "true"
        browser.act(next(a for a in after["actions"] if a["label"] == "Switch"), after)
        switch = next(a for a in browser.observe(screenshot=False)["actions"] if a["label"] == "Switch")
        assert switch["checked"] == switch["value"] == "true"
        page = browser.observe(screenshot=False)
        pressed = next(a for a in page["actions"] if a["label"] == "Pinned")
        browser.act(pressed, page)
        after = browser.observe(screenshot=False)
        assert after["fingerprint"] != page["fingerprint"]
        assert not browser.fresh(page, pressed)
        assert next(f for f in after["observed_controls"] if f["label"] == "Pinned")["pressed"] == "true"
        page = browser.observe(screenshot=False)
        outside = next(a for a in page["actions"] if a["label"] == "Outside button")
        browser.act(outside, page)
        page = browser.observe(screenshot=False)
        button = next(a for a in page["actions"] if a["label"] == "Outside button")
        assert button["kind"] == "click"
        assert browser.evaluate("window.activated === true") is False
        browser.act(button, page)
        assert browser.evaluate("window.activated === true") is True
    finally:
        browser.close()
    print("PASS: toggle states are distinct from form submission tokens; text values stay text")


if __name__ == "__main__":
    main()
