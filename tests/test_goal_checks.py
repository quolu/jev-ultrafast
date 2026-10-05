"""Offline failures at completion, repetition and paid-request boundaries; no paid model calls."""

import threading
import time
from copy import deepcopy
from unittest.mock import Mock

import httpx
import pytest

from jev_ultrafast import agent as loop
from jev_ultrafast import model
from jev_ultrafast.browser import fingerprint


def answer(ids, selected):
    return {"choice": selected, "confidence": 1.0, "probabilities": {i: float(i == selected) for i in ids}}


def decision(selected):
    return {"choice": selected, "operation": "CLICK", "target": "1", "confidence": 1,
            "probabilities": {selected: 1}, "latency_ms": 0, "usage": {}}


def runner():
    a = loop.Agent.__new__(loop.Agent)
    a.screenshots = False
    a.pending_text = None
    page = {"url": "https://example.test/settings", "title": "Settings", "text": "Private", "scroll": {"y": 0},
            "actions": [{"id": "bad", "kind": "click", "label": "Wrong scope", "role": "link", "node": 1},
                        {"id": "good", "kind": "click", "label": "Save", "role": "button", "node": 2}],
            "observed_controls": [{"role": "radio", "label": "Private", "checked": "true", "disabled": False}]}
    page["fingerprint"] = fingerprint(page)
    a.state = {"browser": Mock(fresh=Mock(return_value=True), observe=Mock(return_value=page),
                               wait_for_change=Mock(return_value=False)),
               "page": page, "goal": "Make the package public", "history": [], "decisions": [],
               "decision": None, "status": "ready", "started_at": time.perf_counter(), "record": False,
               "model_calls": 0, "assessments": [], "text_calls": [], "initial_controls": []}
    return a




def test_claimed_completion_is_checked_before_finishing(monkeypatch):
    a = runner()
    choose = Mock(return_value=decision("DONE"))
    monkeypatch.setattr(loop, "choose", choose)
    monkeypatch.setattr(loop, "assess", Mock(return_value=answer(["fulfilled", "unmet", "not_observed"], "fulfilled")))
    result = a.command("tick")
    assert result["status"] == "done" and result["plan_index"] == 1
    assert result["history"] == []
    assert result["model_calls"] == 2
    a.state["browser"].act.assert_not_called()
    assert all(call.args[1] == loop.DONE_SETTLE_SECONDS
               for call in a.state["browser"].wait_for_change.call_args_list)


@pytest.mark.parametrize("assessment", ["unmet", "not_observed"])
def test_operation_done_cannot_override_the_current_result(monkeypatch, assessment):
    a = runner()
    a.state.update(status="predicted", decision=decision("DONE"))
    monkeypatch.setattr(loop, "assess", Mock(return_value=answer(["fulfilled", "unmet", "not_observed"], assessment)))
    result = a.command("act", {"fingerprint": a.state["page"]["fingerprint"]})
    assert result["status"] == "blocked" and result["stop_reason"] == "goal_" + assessment
    assert result["plan_index"] == 0
    a.state["browser"].act.assert_not_called()


def test_changed_settlement_reobserves_instead_of_finishing(monkeypatch):
    a = runner()
    a.state["browser"].wait_for_change.return_value = True
    monkeypatch.setattr(loop, "choose", Mock(return_value=decision("DONE")))
    monkeypatch.setattr(loop, "assess", Mock(return_value=answer(["fulfilled", "unmet", "not_observed"], "fulfilled")))
    result = a.command("tick")
    assert result["status"] == "blocked" and result["stop_reason"] == "observation_unstable"
    assert result["model_calls"] == 2
    a.state["browser"].act.assert_not_called()




def test_model_budget_ends_as_a_terminal_state_before_a_call(monkeypatch):
    a = runner()
    a.state["model_calls"] = loop.MAX_STEPS * 2
    assessment = Mock(side_effect=AssertionError("No request after budget"))
    monkeypatch.setattr(loop, "assess", assessment)
    result = a.command("tick")
    assert result["status"] == "blocked" and result["stop_reason"] == "model_call_budget"
    a.state["browser"].act.assert_not_called()


def test_assessment_uses_current_facts_and_ignores_action_history(monkeypatch):
    p = runner().state["page"]
    p["observed_controls"].append({"role": "radio", "label": "Public", "checked": "false", "disabled": True})
    calls = []

    def post(_url, _key, body):
        calls.append(body)
        choices = body["questions"]["assessment"]["criteria"]
        return {"model": "fixture", "answers": {"assessment": answer(choices, "unmet")}}

    monkeypatch.setenv("TYPESAFE_API_KEY", "fixture")
    monkeypatch.setattr(model, "post_json", post)
    result = model.assess(p, "Make the package public", initial_controls=p["observed_controls"])
    assert result["choice"] == "unmet"
    assert "recent_actions" not in calls[0]["state"]
    assert calls[0]["state"]["current_observation"]["controls"][-1]["disabled"] is True
    assert calls[0]["state"]["initial_controls"] == p["observed_controls"]


def test_done_cannot_reroll_the_same_unmet_result(monkeypatch):
    a = runner()
    assessment = Mock(side_effect=[answer(["fulfilled", "unmet", "not_observed"], "unmet"),
                                   AssertionError("A second judgment would be a reroll")])
    monkeypatch.setattr(loop, "assess", assessment)
    a.state.update(decision=decision("DONE"), status="predicted")
    result = a.command("act", {"fingerprint": a.state["page"]["fingerprint"]})
    assert result["status"] == "blocked" and result["stop_reason"] == "goal_unmet"
    assert a.inspect_goal()["choice"] == "unmet"
    assessment.assert_called_once()
    a.state["browser"].act.assert_not_called()


def test_first_visit_to_settings_is_a_preservation_baseline(monkeypatch):
    a = runner()
    a.state["page"]["url"] = "https://example.test/organization"
    a.state["page"]["observed_controls"] = []
    assert a.baselines() == []
    p = a.state["page"]
    p["url"] = "https://example.test/organization/settings"
    p["observed_controls"] = [{"key": "internal", "label": "Internal", "checked": "false"}]
    a.state["settled_fingerprint"] = p["fingerprint"]
    assert a.baselines()[0]["checked"] == "false"
    p["observed_controls"][0] = {"key": "internal", "label": "Internal", "checked": "true"}
    baseline = a.baselines()
    assert baseline[0]["checked"] == "false"
    assert baseline[0]["url"] == "https://example.test/organization/settings"


def test_delayed_failure_is_read_before_current_result_assessment(monkeypatch):
    a = runner()
    initial = deepcopy(a.state["page"])
    rejected = deepcopy(initial)
    rejected["text"] = "Error: save rejected. Currently private."
    rejected["fingerprint"] = fingerprint(rejected)
    browser = a.state["browser"]
    browser.wait_for_change.side_effect = [True, False]
    browser.observe.return_value = rejected
    a.state.update(decision=decision("good"), status="predicted", settled_fingerprint=initial["fingerprint"])
    browser.observe.side_effect = [initial, rejected]
    a.command("act", {"fingerprint": initial["fingerprint"]})
    browser.observe.side_effect = None

    def inspect(page, *_args, **_kwargs):
        assert page["text"] == rejected["text"]
        return answer(["fulfilled", "unmet", "not_observed"], "unmet")

    monkeypatch.setattr(loop, "assess", inspect)
    a.state.update(decision=decision("DONE"), status="predicted")
    browser.wait_for_change.side_effect = None
    browser.wait_for_change.return_value = False
    result = a.command("act", {"fingerprint": a.state["page"]["fingerprint"]})
    assert result["status"] == "blocked" and result["stop_reason"] == "goal_unmet"
    browser.act.assert_called_once()


def test_cycle_does_not_reexecute_after_node_replacement(monkeypatch):
    a = runner()
    monkeypatch.setattr(loop, "assess", Mock(return_value=answer(["fulfilled", "unmet", "not_observed"], "unmet")))
    a.state.update(decision=decision("good"), status="predicted")
    a.command("act", {"fingerprint": a.state["page"]["fingerprint"]})
    p = deepcopy(a.state["page"])
    p["actions"][1]["node"] = 200
    p["fingerprint"] = fingerprint(p)
    a.state.update(page=p, decision=decision("good"), status="predicted")
    a.state["browser"].observe.return_value = p
    result = a.command("act", {"fingerprint": p["fingerprint"]})
    assert result["status"] == "blocked" and result["stop_reason"] == "cycle"
    a.state["browser"].act.assert_called_once()




def test_model_failure_is_terminal_and_keeps_the_current_page(monkeypatch):
    a = runner()
    monkeypatch.setattr(loop, "choose", Mock(side_effect=RuntimeError("provider body with secrets")))
    result = a.command("predict")
    assert result["status"] == "blocked" and result["stop_reason"] == "model_error"
    assert result["page"]["text"] == "Private"
    assert "secrets" not in str(result)
    a.state["browser"].act.assert_not_called()


def test_partial_input_is_logged_and_never_retried():
    a = runner()
    a.state.update(decision=decision("good"), status="predicted")
    a.state["browser"].act.side_effect = RuntimeError("CDP lost after press")
    result = a.command("act", {"fingerprint": a.state["page"]["fingerprint"]})
    assert result["status"] == "blocked" and result["stop_reason"] == "action_delivery_unconfirmed"
    assert result["history"][0]["delivery"] == "uncertain"
    assert list(a.run()) == []
    a.state["browser"].act.assert_called_once()


def test_final_budget_request_observes_the_last_saved_result(monkeypatch):
    a = runner()
    a.state["model_calls"] = loop.MAX_STEPS * 2 - 1
    a.state["page"]["text"] = "Saved: Public=true"
    a.state["page"]["fingerprint"] = fingerprint(a.state["page"])
    monkeypatch.setattr(loop, "assess", Mock(return_value=answer(["fulfilled", "unmet", "not_observed"], "fulfilled")))
    result = a.command("predict")
    assert result["status"] == "done" and result["model_calls"] == loop.MAX_STEPS * 2


def test_urls_and_oversize_requests_do_not_disclose_or_reach_the_api(monkeypatch):
    assert model.public_url("https://name:secret@example.test/path?token=secret#secret") == "https://example.test/path"
    post = Mock(side_effect=AssertionError("No API request for an oversized body"))
    monkeypatch.setattr(model.CLIENT, "post", post)
    with pytest.raises(RuntimeError, match="size limit"):
        model.post_json("https://example.test", "fixture", {"state": "x" * 100_001})
    post.assert_not_called()


def test_wire_budget_counts_retries_and_text_model_requests(monkeypatch):
    a = runner()
    a.state["model_call_budget"] = 2
    responses = [httpx.Response(503, json={}), httpx.Response(200, json={"answers": {}})]
    post = Mock(side_effect=responses)
    monkeypatch.setattr(model.CLIENT, "post", post)
    monkeypatch.setattr(model.time, "sleep", lambda *_args: None)
    token = model.REQUEST_METER.set(a.count_wire_request)
    try:
        model.post_json("https://api.typesafe.ai/v1/systemone", "fixture", {})
        with pytest.raises(model.ModelBudgetExceeded):
            model.post_json("https://text-helper.test/chat/completions", "fixture", {})
    finally:
        model.REQUEST_METER.reset(token)
    assert a.state["wire_calls"] == post.call_count == 2


def test_none_target_abstains_without_an_executable_target(monkeypatch):
    def post(_url, _key, body):
        return {"model": "fixture", "answers": {
            "operation": answer(body["questions"]["operation"]["criteria"], "CLICK"),
            "click_target": answer(body["questions"]["click_target"]["criteria"], "NONE"),
        }}
    monkeypatch.setenv("TYPESAFE_API_KEY", "fixture")
    monkeypatch.setattr(model, "post_json", post)
    result = model.choose(runner().state["page"], "Only use a disabled control", [])
    assert result["choice"] == "BLOCKED" and result["target"] == "NONE"




def test_none_click_target_still_allows_revealing_the_needed_control(monkeypatch):
    a = runner()
    a.state["page"]["actions"].append({"id": "offscreen", "node": 3, "kind": "reveal", "label": "Settings"})
    a.state["page"]["fingerprint"] = fingerprint(a.state["page"])
    offered = []

    def choose(page, *_args):
        offered.append([x["id"] for x in page["actions"]])
        if len(offered) == 1:
            return {**decision("BLOCKED"), "target": "NONE"}
        return {**decision("offscreen"), "operation": "REVEAL"}

    monkeypatch.setattr(loop, "choose", choose)
    monkeypatch.setattr(loop, "assess", Mock(return_value=answer(["fulfilled", "unmet", "not_observed"], "unmet")))
    result = a.command("tick")
    assert offered == [["bad", "good", "offscreen"], ["offscreen"]]
    assert result["history"][0]["kind"] == "reveal"
    assert result["model_calls"] == 2


def test_baselines_keep_distinct_port_origins_and_ipv6():
    assert model.public_url("http://user:secret@[::1]:8080/a?token=secret#private") == "http://[::1]:8080/a"
    a = runner()
    a.state["page"]["url"] = "http://localhost:8080/settings"
    a.state["settled_fingerprint"] = a.state["page"]["fingerprint"]
    first = a.baselines()
    a.state["page"]["url"] = "http://localhost:8081/settings"
    a.state["page"]["observed_controls"][0]["checked"] = "false"
    assert a.baselines()[0]["checked"] == "false"
    assert first[0]["checked"] == "true"


def test_redirect_baseline_is_marked_as_after_mutating_input(monkeypatch):
    a = runner()
    monkeypatch.setattr(loop, "assess", Mock(return_value=answer(["fulfilled", "unmet", "not_observed"], "unmet")))
    a.state.update(decision=decision("good"), status="predicted")
    a.command("act", {"fingerprint": a.state["page"]["fingerprint"]})
    a.state["page"]["url"] = "https://example.test/settings/result"
    assert a.baselines()[0]["after_mutating_inputs"] == 1


def test_navigation_before_first_settings_observation_is_not_a_write():
    a = runner()
    a.state["page"]["actions"][1].update(role="link", destination="https://example.test/settings/result")
    navigated = deepcopy(a.state["page"])
    navigated["url"] = "https://example.test/settings/result"
    navigated["fingerprint"] = fingerprint(navigated)
    a.state["browser"].observe.return_value = navigated
    a.state.update(decision=decision("good"), status="predicted")
    a.command("act", {"fingerprint": a.state["page"]["fingerprint"]})
    a.state["page"]["url"] = "https://example.test/settings/result"
    assert a.baselines()[0]["after_mutating_inputs"] == 0


def test_second_runner_cannot_stop_an_active_command():
    a = runner()
    a._command_lock = threading.RLock()
    held, release = threading.Event(), threading.Event()

    def own_run():
        with a._command_lock:
            held.set()
            release.wait(2)

    owner = threading.Thread(target=own_run)
    owner.start()
    assert held.wait(2)
    try:
        with pytest.raises(loop.ConcurrentCommandError):
            next(a.run())
        assert a.state["status"] == "ready"
        assert "stop_reason" not in a.state
    finally:
        release.set()
        owner.join(2)






def test_first_preservation_baseline_waits_for_hydrated_controls():
    a = runner()
    hydrated = deepcopy(a.state["page"])
    hydrated["observed_controls"][0]["checked"] = "false"
    hydrated["marker"] = [hydrated["text"], hydrated["observed_controls"]]
    hydrated["fingerprint"] = fingerprint(hydrated)
    assert a.baselines() == []
    a.state["browser"].wait_for_change.side_effect = [True, False]
    a.state["browser"].observe.return_value = hydrated
    a.settle()
    assert a.baselines()[0]["checked"] == "false"
    assert a.baselines()[0]["after_mutating_inputs"] == 0






def test_unknown_text_is_not_retried_or_fabricated(monkeypatch):
    monkeypatch.setenv("TEXT_MODEL_API_KEY", "fixture")
    post = Mock(return_value={"choices": [{"message": {"content": '{"text":null}'}}]})
    monkeypatch.setattr(model, "post_json", post)
    with pytest.raises(ValueError, match="no valid field value"):
        model.field_text({"goal": "Enter an unavailable personal value"})
    post.assert_called_once()




def test_same_observation_reuses_selection_without_more_paid_requests(monkeypatch):
    a = runner()
    choose = Mock(return_value={**decision("wait"), "operation": "WAIT"})
    a.state["page"]["actions"].append({"id": "wait", "kind": "wait", "label": "Wait"})
    monkeypatch.setattr(loop, "choose", choose)
    monkeypatch.setattr(loop, "assess", Mock(side_effect=AssertionError("No completion claimed")))
    for _ in range(3):
        a.command("tick")
    assert a.state["status"] == "ready"
    assert a.state["model_calls"] == 1
    choose.assert_called_once()
    assert a.state["browser"].act.call_count == 3


def test_normal_step_needs_only_the_existing_selection_request(monkeypatch):
    a = runner()
    monkeypatch.setattr(loop, "choose", Mock(return_value=decision("good")))
    assess = Mock(side_effect=AssertionError("Do not re-judge a normal operation"))
    monkeypatch.setattr(loop, "assess", assess)
    a.command("tick")
    assert a.state["model_calls"] == 1
    assert a.state["history"][0]["choice"] == "good"
    assess.assert_not_called()


def test_malformed_text_is_terminal_without_a_paid_format_retry(monkeypatch):
    monkeypatch.setenv("TEXT_MODEL_API_KEY", "fixture")
    post = Mock(return_value={"choices": [{"message": {"content": '{"text":"Example"}\n```'}}]})
    monkeypatch.setattr(model, "post_json", post)
    with pytest.raises(ValueError, match="nothing typed"):
        model.field_text({"goal": "Search for Example"})
    post.assert_called_once()


def test_unfulfilled_done_continues_to_save_without_candidate_rejudgment(monkeypatch):
    a = runner()
    offers = []
    def choose(page, *_args):
        offers.append(page["allow_done"])
        return decision("DONE" if page["allow_done"] else "good")
    monkeypatch.setattr(loop, "choose", choose)
    assessment = Mock(return_value=answer(["fulfilled", "unmet", "not_observed"], "unmet"))
    monkeypatch.setattr(loop, "assess", assessment)
    result = a.command("tick")
    assert offers == [True, False]
    assert result["history"][0]["action"] == "Save"
    assert result["model_calls"] == 3
    assessment.assert_called_once()


def test_anchor_save_is_a_write_even_with_a_truthy_same_page_destination():
    a = runner()
    a.state["page"]["actions"][1].update(role="link", destination=a.state["page"]["url"])
    a.state.update(decision=decision("good"), status="predicted")
    a.command("act", {"fingerprint": a.state["page"]["fingerprint"]})
    assert a.baselines()[0]["after_mutating_inputs"] == 1


def test_preservation_baselines_do_not_mix_query_routes():
    a = runner()
    a.state["settled_fingerprint"] = a.state["page"]["fingerprint"]
    a.state["page"]["url"] += "?id=1"
    assert a.baselines()[0]["checked"] == "true"
    a.state["page"]["url"] = "https://example.test/settings?id=2"
    a.state["page"]["observed_controls"][0]["checked"] = "false"
    assert a.baselines()[0]["checked"] == "false"


def test_cached_selection_does_not_report_new_provider_usage(monkeypatch):
    a = runner()
    a.state["page"]["actions"].append({"id": "wait", "kind": "wait", "label": "Wait"})
    choose = Mock(return_value={**decision("wait"), "latency_ms": 42, "usage": {"tokens": 12}})
    monkeypatch.setattr(loop, "choose", choose)
    a.command("tick")
    result = a.command("tick")
    assert result["decisions"][-1]["cached"] is True
    assert result["history"][-1]["latency_ms"] == 0
    assert result["history"][-1]["usage"] == {}
    assert "decision_cache" not in result and "goal_cache" not in result
    choose.assert_called_once()
