"""The complete agent loop. Typed choices, observable state, bounded execution."""

import base64
import hashlib
import json
import threading
import time
from pathlib import Path
from urllib.parse import urlsplit

from .browser import Browser, StalePage
from .model import (
    REQUEST_METER,
    ModelBudgetExceeded,
    action_space,
    assess,
    assessment_facts,
    choose,
    field_context,
    field_text,
    public_url,
)
from .questions import MAX_STEPS

# After input that can route to another page, an observation that lost its content is re-read until it returns.
# The same cap bounds the wait before an initial BLOCKED is final, while the first page is still rendering.
SETTLE_SECONDS = 10
SETTLE_SKIP_KINDS = {"wait", "scroll", "reveal"}
DONE_SETTLE_SECONDS = 1
MAX_SELECTION_ATTEMPTS = 4
MIN_GOAL_PROBABILITY = 0.7
MAX_STALE_TICKS = 20


class ConcurrentCommandError(ValueError):
    """A different caller owns this run; rejection must not stop that caller's work."""


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def cycle_key(page, action):
    """No transient indices/DOM identities or geometry; retain result text so a new carousel item is new state."""
    return digest({"url": page["url"], "title": page["title"], "text": page["text"],
                   "controls": page.get("observed_controls", []),
                   "action": {k: action.get(k) for k in (
                       "kind", "label", "role", "value", "checked", "pressed", "selected", "expanded",
                       "destination", "scope", "delta")}})


def lost_content(before, after):
    """True while the page after input has not yet rendered the content the page before it had.

    A page that had visible text but now has none counts as not yet rendered. So does a route
    change within the same origin whose main landmark had content before and now has none: missing,
    empty, or holding only navigation, like an app shell that keeps its header and sidebar while the
    next view loads. A main that holds nothing but navigation links therefore waits out the cap.
    """
    if before["text"].strip() and not after["text"].strip():
        return True
    old, new = urlsplit(before["url"]), urlsplit(after["url"])
    route_changed = (old.scheme, old.netloc) == (new.scheme, new.netloc) and old != new
    return route_changed and before.get("main") is True and after.get("main") is not True


class Agent:
    def __init__(self, url, goals, *, record_dir=None, screenshots=False, model_call_budget=MAX_STEPS * 2):
        task = goals.strip() if isinstance(goals, str) else "\n".join(goals).strip()
        if not task:
            raise ValueError("Supply a task")
        if type(model_call_budget) is not int or not 1 <= model_call_budget <= MAX_STEPS * 2:
            raise ValueError("model_call_budget must be an integer from 1 to 120")
        plan = [task]
        self.pending_text = None
        self.browser = Browser(url)
        self.record_dir = Path(record_dir) if record_dir else None
        self.screenshots = screenshots or bool(record_dir)
        try:
            page = self.browser.observe(screenshot=self.screenshots)
        except Exception:
            self.browser.close()
            raise
        self.state = dict(
            browser=self.browser,
            goal="\n".join(plan),
            page=page,
            decision=None,
            history=[],
            status="ready",
            plan=plan,
            plan_index=0,
            decisions=[],
            assessments=[],
            model_calls=0,
            wire_calls=0,
            model_call_budget=model_call_budget,
            initial_controls=[],
            text_calls=[],
            elapsed_ms=0,
            started_at=None,
            record=bool(self.record_dir),
        )
        if self.record_dir:
            self.record_dir.mkdir(parents=True, exist_ok=True)
            (self.record_dir / "000000.jpg").write_bytes(base64.b64decode(page["screenshot"]))

    def snapshot(self):
        return {
            **{k: v for k, v in self.state.items() if k != "browser"},
            "elements": action_space(self.state["page"]["actions"])[0],
        }

    def command(self, name, body=None):
        lock = self.__dict__.setdefault("_command_lock", threading.RLock())
        if not lock.acquire(blocking=False):
            raise ConcurrentCommandError("A command is already running")
        try:
            return self._command(name, body)
        finally:
            lock.release()

    def _command(self, name, body=None):
        body = body or {}
        state = self.state
        if name == "tick":
            try:
                self.command("predict", {})
                if state["status"] in {"done", "blocked"}:
                    return self.snapshot()
                if state["decision"] is None:
                    return self.snapshot()
                return self.command("act", {"fingerprint": state["page"]["fingerprint"]})
            except StalePage:
                state["decision"] = None
                state["status"] = "ready"
                state["stale_ticks"] = state.get("stale_ticks", 0) + 1
                try:
                    state["page"] = state["browser"].observe(screenshot=self.screenshots)
                except StalePage:
                    pass
                if state["stale_ticks"] >= MAX_STALE_TICKS:
                    state.update(status="blocked", stop_reason="observation_unstable")
                state["elapsed_ms"] = round((time.perf_counter() - state["started_at"]) * 1000)
                return self.snapshot()
        elif name == "predict":
            if not state["browser"]:
                raise ValueError("Start a demo first")
            if state["started_at"] is None:
                state["started_at"] = time.perf_counter()
            if not state["browser"].fresh(state["page"]):
                state["page"] = state["browser"].observe(screenshot=self.screenshots)
            state["decision"] = None
            if state["status"] in {"done", "blocked"}:
                raise ValueError("This run has stopped. Start a fresh demo.")
            self.settle()
            excluded = set()
            allow_done = True
            for _ in range(MAX_SELECTION_ATTEMPTS):
                offered = {**state["page"], "allow_done": allow_done,
                           "actions": [a for a in state["page"]["actions"] if a["id"] not in excluded]}
                key = digest({"goal": state["goal"], "page": {
                    k: v for k, v in offered.items() if k not in {"screenshot", "guards"}}})
                cache = self.__dict__.setdefault("_decision_cache", {})
                reused = key in cache
                if not reused:
                    d = self.invoke_model(choose, offered, state["goal"], state["history"])
                    if d is None:
                        return self.snapshot()
                    cache[key] = d
                d = {**cache[key], "cached": reused,
                     "offered_actions": [a["id"] for a in offered["actions"]]}
                if reused:
                    d.update(latency_ms=0, usage={})
                state["decisions"].append({**d, "fingerprint": state["page"]["fingerprint"],
                    "elapsed_ms": round((time.perf_counter() - state["started_at"]) * 1000)})
                if d.get("target") == "NONE":
                    kind = {"CLICK": "click", "TYPE_TEXT": "fill", "SELECT": "select", "REVEAL": "reveal"}.get(
                        d["operation"])
                    excluded.update(a["id"] for a in offered["actions"] if a["kind"] == kind)
                    continue
                if d["choice"] == "DONE":
                    inspection = self.inspect_goal()
                    if inspection is None or self.accept_completion(inspection):
                        return self.snapshot()
                    allow_done = False
                    continue
                state["decision"] = d
                break
            else:
                self.stop("no_supported_progress")
                return self.snapshot()
            state["status"] = "predicted"
        elif name == "act":
            decision, page = state["decision"], state["page"]
            if not decision or body.get("fingerprint") != page["fingerprint"]:
                raise ValueError("Observe and choose before acting")
            # Consume once, before any mutation or model call. A retry cannot double-click.
            state["decision"] = None
            selected = decision["choice"]
            if selected in {"DONE", "BLOCKED"}:
                if not state["browser"].fresh(page):
                    state["status"] = "ready"
                    raise StalePage("Page changed since the decision. Choose again.")
                if selected == "BLOCKED" and not any(h["kind"] != "wait" for h in state["history"]):
                    if getattr(self, "initial_blocked_deadline", None) is None:
                        self.initial_blocked_deadline = time.monotonic() + SETTLE_SECONDS
                    remaining = self.initial_blocked_deadline - time.monotonic()
                    if remaining > 0 and state["browser"].wait_for_change(page, remaining):
                        state["status"] = "ready"
                        raise StalePage("Page changed during the initial blocked decision. Choose again.")
                if selected == "DONE":
                    if state["browser"].wait_for_change(page, DONE_SETTLE_SECONDS):
                        raise StalePage("Page changed while checking completion")
                    assessment = self.inspect_goal()
                    if assessment is None:
                        return self.snapshot()
                    if not self.accept_completion(assessment):
                        self.stop("goal_unverified" if assessment["choice"] == "fulfilled" else
                                  "goal_" + assessment["choice"])
                else:
                    state.update(status="blocked", stop_reason="no_supported_progress")
                state["plan_index"] = int(state["status"] == "done")
                state["elapsed_ms"] = round((time.perf_counter() - state["started_at"]) * 1000)
                return self.snapshot()
            action = next(a for a in page["actions"] if a["id"] == selected)
            if action["kind"] == "wait" and decision.get("cached"):
                if state["browser"].wait_for_change(page, DONE_SETTLE_SECONDS):
                    raise StalePage("Page changed during cached wait")
            if len(state["history"]) >= MAX_STEPS:
                self.final_result("action_budget")
                return self.snapshot()
            pair = cycle_key(page, action)
            if action["kind"] not in SETTLE_SKIP_KINDS and pair in self.__dict__.setdefault("_executed_pairs", []):
                if not state["browser"].fresh(page):
                    raise StalePage("Page changed before cycle assessment")
                self.final_result("cycle")
                return self.snapshot()
            text, helper = None, None
            if action["kind"] == "fill":
                if not state["browser"].fresh(page):
                    raise StalePage("Page changed before text generation. Choose again.")
                context = field_context(state["goal"], action, page, state["history"])
                if self.pending_text and self.pending_text[0] == context:
                    _, text, helper = self.pending_text
                else:
                    try:
                        token = REQUEST_METER.set(self.count_wire_request)
                        try:
                            text, helper = field_text(context)
                        finally:
                            REQUEST_METER.reset(token)
                    except ModelBudgetExceeded:
                        self.stop("paid_request_budget")
                        return self.snapshot()
                    except (RuntimeError, ValueError, KeyError, TypeError):
                        self.stop("text_model_error")
                        return self.snapshot()
                    self.pending_text = (context, text, helper)
                    state["text_calls"].append({**helper, "field": action["label"], "value": text})
            # The selection uses whole-page facts, so its evidence must still match.
            # Browser.act also checks target identity, live geometry and occlusion before input.
            if not state["browser"].fresh(page, action if action["kind"] in {"click", "select", "reveal"} else None):
                raise StalePage("Page changed after selection. Choose again.")
            try:
                state["browser"].act(action, page, text=text)
            except (RuntimeError, TimeoutError) as error:
                state["history"].append({"step": len(state["history"]) + 1, "action": action["label"],
                    "kind": action["kind"], "choice": selected, "text": text, "page_changed": None,
                    "delivery": "uncertain", "error_type": type(error).__name__, "url": page["url"],
                    "probability": decision["probabilities"][selected], "confidence": decision["confidence"],
                    "latency_ms": decision["latency_ms"]})
                self.__dict__.setdefault("_executed_pairs", []).append(pair)
                self.stop("action_delivery_unconfirmed")
                try:
                    state["page"] = state["browser"].observe(screenshot=self.screenshots)
                except (RuntimeError, ValueError, TimeoutError):
                    state["final_observation_unavailable"] = True
                return self.snapshot()
            if action["kind"] not in SETTLE_SKIP_KINDS:
                state["settled_fingerprint"] = None
                state["mutating_inputs"] = state.get("mutating_inputs", 0) + 1
            self.__dict__.setdefault("_executed_pairs", []).append(pair)
            state["stale_ticks"] = 0
            self.pending_text = None
            state["elapsed_ms"] = round((time.perf_counter() - state["started_at"]) * 1000)
            # Record execution before observing. A stale post-action observation must not erase the action.
            state["history"].append(
                {
                    "step": len(state["history"]) + 1,
                    "action": action["label"],
                    "kind": action["kind"],
                    "choice": selected,
                    "probability": decision["probabilities"][selected],
                    "confidence": decision["confidence"],
                    "latency_ms": decision["latency_ms"],
                    "text": text,
                    "text_helper": helper["model"] if helper else None,
                    "text_latency_ms": helper["latency_ms"] if helper else 0,
                    "operation": decision["operation"],
                    "target": decision["target"],
                    "page_changed": None,
                    "url": page["url"],
                    "usage": decision["usage"],
                    "executed_ms": round((time.perf_counter() - state["started_at"]) * 1000),
                    "elapsed_ms": state["elapsed_ms"],
                }
            )
            state["page"] = state["browser"].observe(screenshot=self.screenshots)
            if (action["kind"] == "click" and action.get("role") == "link" and action.get("destination") and
                    action["destination"] != public_url(page["url"]) and
                    action["destination"] == public_url(state["page"]["url"])):
                state["mutating_inputs"] -= 1
            if action["kind"] not in SETTLE_SKIP_KINDS:
                # A client-side route change can show an empty page or an empty app shell for a moment.
                # Re-observe, without another model call, until the content returns or the wait ends.
                self.settle(previous=page)
            state["elapsed_ms"] = round((time.perf_counter() - state["started_at"]) * 1000)
            state["history"][-1].update(
                page_changed=state["page"]["fingerprint"] != page["fingerprint"],
                url=state["page"]["url"],
                elapsed_ms=state["elapsed_ms"],
            )
            if state["record"]:
                (self.record_dir / f"{state['elapsed_ms']:06d}.jpg").write_bytes(
                    base64.b64decode(state["page"]["screenshot"])
                )
            repeated = state["history"][-3:]
            state["status"] = (
                "blocked"
                if len(repeated) == 3 and all(h["page_changed"] is False and h["kind"] != "wait" for h in repeated)
                else "ready"
            )
            if state["status"] == "blocked":
                self.final_result("no_effect")
        else:
            raise ValueError("Unknown command")
        return self.snapshot()

    def stop(self, reason):
        self.state.update(status="blocked", stop_reason=reason, decision=None, plan_index=0)

    def settle(self, previous=None):
        """Bounded read-only quiet window before assessing initial or post-input results."""
        state = self.state
        if state.get("settled_fingerprint") == state["page"]["fingerprint"]:
            return
        deadline = time.monotonic() + SETTLE_SECONDS
        for _ in range(MAX_STALE_TICKS):
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            page = state["page"]
            timeout = remaining if previous is not None and lost_content(previous, page) else min(
                remaining, DONE_SETTLE_SECONDS)
            if not state["browser"].wait_for_change(page, timeout):
                if timeout >= DONE_SETTLE_SECONDS and not (previous and lost_content(previous, page)):
                    state["settled_fingerprint"] = page["fingerprint"]
                    self.baselines()
                return
            after = state["browser"].observe(screenshot=self.screenshots)
            state["page"] = after
            if after["fingerprint"] == page["fingerprint"] and not (previous and lost_content(previous, after)):
                # The full marker may change and return between reads. No quiet interval was witnessed.
                break
        state["settled_fingerprint"] = None

    def baselines(self):
        state, page = self.state, self.state["page"]
        url = public_url(page["url"])
        url_key = digest(page["url"])
        controls = page.get("observed_controls", [])
        baseline = self.__dict__.setdefault("_control_baselines", {})
        for i, fact in enumerate(controls):
            key = url_key + "\n" + fact.get("key", str(i) + "|" + fact.get("label", ""))
            if (key not in baseline and len(baseline) < 500 and
                    state.get("settled_fingerprint") == page["fingerprint"]):
                baseline[key] = {**fact, "url": url, "after_mutating_inputs": state.get("mutating_inputs", 0)}
        result = [baseline[key] for i, fact in enumerate(controls)
                  if (key := url_key + "\n" + fact.get("key", str(i) + "|" + fact.get("label", ""))) in baseline]
        state["initial_controls"] = result
        state["baseline_incomplete"] = len(result) != len(controls)
        return result

    def inspect_goal(self):
        state = self.state
        initial = self.baselines()
        key = digest(assessment_facts(state["page"], state["goal"], initial))
        cache = self.__dict__.setdefault("_goal_cache", {})
        if key not in cache:
            inspection = self.invoke_model(assess, state["page"], state["goal"],
                                           initial_controls=initial, final=True)
            if inspection is None:
                return None
            cache[key] = inspection
            state.setdefault("assessments", []).append({**inspection, "phase": "goal", "evidence_key": key})
        state["goal_assessment"] = cache[key]
        return cache[key]

    def accept_completion(self, inspection):
        state = self.state
        if inspection["choice"] != "fulfilled" or inspection["probabilities"]["fulfilled"] < MIN_GOAL_PROBABILITY:
            return False
        if state.get("settled_fingerprint") != state["page"]["fingerprint"]:
            self.stop("observation_unstable")
            return True
        if state.get("baseline_incomplete") or state["page"].get("observation_limits", {}).get("omitted_controls"):
            self.stop("observation_incomplete")
            return True
        if not state["browser"].fresh(state["page"]):
            raise StalePage("Page changed during goal assessment")
        if state["browser"].wait_for_change(state["page"], DONE_SETTLE_SECONDS):
            raise StalePage("Page changed while checking completion")
        state.update(status="done", plan_index=1, decision=None)
        state["elapsed_ms"] = round((time.perf_counter() - state["started_at"]) * 1000)
        return True

    def final_result(self, reason):
        self.settle()
        inspection = self.inspect_goal()
        if inspection is not None and not self.accept_completion(inspection):
            self.stop(reason)

    def invoke_model(self, function, *args, final=False, **kwargs):
        if not self.reserve_model_call(final=final):
            return None
        try:
            token = REQUEST_METER.set(self.count_wire_request)
            try:
                return function(*args, **kwargs)
            finally:
                REQUEST_METER.reset(token)
        except ModelBudgetExceeded:
            self.stop("paid_request_budget")
            return None
        except (RuntimeError, ValueError, KeyError, TypeError) as error:
            self.stop("model_error")
            self.state["error_type"] = type(error).__name__
            return None

    def count_wire_request(self):
        state = self.state
        if state.get("wire_calls", 0) >= state.get("model_call_budget", MAX_STEPS * 2):
            raise ModelBudgetExceeded()
        state["wire_calls"] = state.get("wire_calls", 0) + 1

    def reserve_model_call(self, *, final=False):
        state = self.state
        calls = state.setdefault("model_calls", len(state["decisions"]))
        budget = state.get("model_call_budget", MAX_STEPS * 2)
        if calls >= budget - int(not final):
            if not final and calls < budget:
                self.final_result("model_call_budget")
            else:
                self.stop("model_call_budget")
            return False
        state["model_calls"] += 1
        return True

    def run(self):
        while self.state["status"] not in {"done", "blocked"}:
            try:
                yield self.command("tick")
            except ConcurrentCommandError:
                raise
            except (RuntimeError, ValueError, KeyError, TypeError) as error:
                self.stop("execution_or_observation_error")
                self.state["error_type"] = type(error).__name__
                yield self.snapshot()

    def close(self):
        self.browser.close()

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        self.close()
