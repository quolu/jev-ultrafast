<img src="docs/banner.svg" alt="Jev Ultrafast · Browser Use × TypeSafe" width="100%" />

# Jev Ultrafast ⚡

> [!IMPORTANT]
> **The Browser Use Cloud waitlist is open.** Get early access to ultrafast browser agents in the cloud.
> **[Join the waitlist →](https://browser-use.com/ultrafast?utm_source=github&utm_medium=readme&utm_campaign=jev-ultrafast)**

**A browser agent with a dynamic, indexed action space.**

Give it one goal. [TypeSafe's Jev](https://docs.typesafe.ai/introduction) picks an operation and an element. A small LLM writes text only when the operation is `TYPE_TEXT`.

**Earlier-version recorded demonstration: Zürich → London on Google Flights in 7.1 seconds.** One natural-language goal, actual text generation, and loading waits included.

<a href="docs/demo.mp4"><img src="docs/demo.gif" alt="A real Google Flights search at 1× speed, with generated city names and dynamic operation/target decisions" width="100%" /></a>

[Watch the MP4](docs/demo.mp4) · [Measurements](docs/performance.md) · [Read the loop](jev_ultrafast/agent.py)

## The action space

Every observation produces a new element table:

```text
[1] button    Change ticket type · Round trip
[2] combobox  Where from?        · San Francisco
[3] combobox  Where to?          · empty
[4] textbox   Departure          · empty
...
```

The operations are `CLICK`, `TYPE_TEXT`, `SELECT`, `REVEAL`, `SCROLL_UP`, `SCROLL_DOWN`, `WAIT`, `DONE`, and `BLOCKED`, plus named nested-region scroll operations when a visible scroll container is sampled. Only supported operations and targets are offered.

```text
                      one TypeSafe request
                     ┌───────────────────────────┐
page → element table → operation                 │
                     │ click_target              │
                     │ type_text_target          │
                     │ select_target, if present │
                     └─────────────┬─────────────┘
                         use the matching target
                                   │
                    CLICK [7] ─────┤──→ browser
                TYPE_TEXT [3] ─────┘
                          ↓
                   small LLM → text → browser
```

Target questions are speculative. If the operation is `CLICK`, only `click_target` can execute. Operation and target share **one network round trip per selection stage**. Each target head contains only compatible elements. Native dropdown choices carry an observed element/option index.

There are no site-specific action scripts or prepared field strings in the policy. The Flights example supplies a goal and independently verifies the outcome. The screenshot renderer adds labels afterward; it does not drive the browser.

## Try it

```bash
git clone https://github.com/browser-use/jev-ultrafast.git
cd jev-ultrafast
uv sync
cp .env.example .env
# Add TYPESAFE_API_KEY and TEXT_MODEL_API_KEY.
uv run jev
```

Open **http://127.0.0.1:8766** and click **Start demo → Run automatically**. The inspector shows numbered elements, operation probabilities, target probabilities, and executed actions. **Choose next** pauses before execution.

Chrome connects through [Browser Harness](https://github.com/browser-use/browser-harness), installed by `uv sync`. Run `uv run browser-harness --doctor` if it needs connecting. Allow remote debugging in Chrome when prompted.

`TEXT_MODEL_API_KEY` is an OpenRouter key in the example configuration. The current demo uses `inception/mercury-2.5` with reasoning disabled. Gemini, GLM, and DeepSeek can also use the OpenAI-compatible text helper; configure the appropriate model, endpoint, and reasoning setting.

## Use the library

```python
from jev_ultrafast import Agent

with Agent(
    "https://www.google.com/travel/flights?hl=en",
    "Find one-way flights from Zurich to London on September 20, 2026, "
    "for one adult in economy. Stop when matching flight options are visible.",
) as agent:
    for state in agent.run():
        print(state["elapsed_ms"], state["status"])
```

Run with `uv run --env-file .env python your_script.py`. The same policy can run a different task:

```bash
uv run --env-file .env python examples/run.py \
  --url https://en.wikipedia.org/wiki/Main_Page \
  --goal 'Find and open the Wikipedia article about Gödel’s incompleteness theorems.'
```

`uv run --env-file .env python examples/flights.py --keep-open` performs the flight search, checks the actual route/date/results, and saves its trace. It does not select or book a flight.

## Why it moves

- **Choose from observed operations and targets.** Their questions share one request. A claimed completion receives a separate current-result check; candidate and region classifiers are not used.
- **No screenshots in the default agent loop.** Jev consumes structured state. The inspector opts into screenshots; the video uses a separate continuous screencast.
- **One browser call per snapshot.** Read visible controls, their names, values, and text atomically. Keep references to the actual DOM nodes.
- **Validate the selected target.** Clicks check the document, form values, target, and nearby context. Animation alone does not force another prediction. Resolve current geometry and reject covered controls before input.
- **Wait for useful state.** After typing into a combobox, wait for visible suggestions, capped at 200 ms. Other interactions get at most two animation frames or 50 ms. These reads happen after execution is logged.
- **Keep hidden tabs rendering.** Focus emulation prevents background animation throttling without switching Chrome's visible tab.
- **Read current values.** Checkbox, radio, and switch values describe checked state, with HTML submission tokens kept separately. Read-only control facts include disabled and offscreen fields; hidden, password, and file inputs are withheld. Visible text remains bounded.
- **Reveal observed controls.** `REVEAL` scrolls a known offscreen node into view without activating it. Sampled scrollable feeds and sidebars also become named, freshness-checked actions.
- **Reuse an interrupted text request.** A generated value survives a stale-page retry only if the entire text-helper input is unchanged.

Every executed target is resolved from an observed node. The executor rechecks page freshness and click occlusion. Model output never becomes selectors, coordinates, shell commands, or executable JavaScript. Text-helper output must parse as a small JSON object before typing.

## Small enough to read

| File | Job |
| --- | --- |
| [agent.py](jev_ultrafast/agent.py) | The complete loop and text-helper handoff |
| [snapshot.js](jev_ultrafast/snapshot.js) | Atomic DOM snapshot, indexed controls, freshness guards |
| [browser.py](jev_ultrafast/browser.py) | Browser connection, current geometry, execution |
| [model.py](jev_ultrafast/model.py) | Dynamic operation/target heads and text generation |
| [questions.py](jev_ultrafast/questions.py) | Model instructions |
| [demo.py](jev_ultrafast/demo.py) | Local inspector |

## Evidence and limits

The video predates the goal-state repair and records a **7,073 ms** Google Flights run. Timing starts after initial page observation and includes model calls, generated text, browser work, stale decisions, and loading waits. A fresh independent check verifies the one-way setting, Zürich, London, September 20, 2026, and visible flight options. The video plays at 1×, with no opening hold and a 0.5-second final hold.

The earlier policy, before the completion checks and quiet windows below, was measured in six alternating runs with identical models and settings. In that historical comparison, both versions passed **3/3**. Median task time went from **9.450 s → 7.092 s**, a **25% reduction**; median browser protocol calls went from **1,092 → 101**. This is three repeats of one task on one browser profile, not a general reliability benchmark.

That earlier policy used in those recordings opened the requested Wikipedia article in **2.798 s** and passed a local hotel search/filter task in **1.896 s**. Runs, failures, source hashes, and measurement boundaries are in [performance.md](docs/performance.md).

A policy `DONE` choice cannot finish a task by itself. The agent separately assesses current result evidence without action history and requires fulfilled probability of at least 0.70 plus a stable one-second observation. Unknown or contradictory evidence blocks a proposed `DONE`. These model judgments do not prove arbitrary goals; independently observed outcomes remain the basis for validation. The DOM reader handles common HTML and ARIA controls and sampled visible scroll regions, not the full accessible-name specification. Shadow roots, frames, canvas, uploads, pop-up tabs, obscured scroll containers, and arbitrary keyboard widgets remain outside this MVP. Owned tabs share the existing Chrome profile.

## Development

A failed model call reports the HTTP status plus a short provider code such as `max_tokens_exceeded`, never the response body or credentials. A connection failure names the exception type, such as `ReadTimeout`. No browser action runs after a failed model call.

```bash
uv run ruff check .
uv run pytest
node --check jev_ultrafast/static/app.js
node --check jev_ultrafast/snapshot.js
uv build
```

Runs stop as `done` or `blocked`; `stop_reason` distinguishes missing or contradictory result evidence, no supported progress, no effect, and exhausted model-call or action budgets. Normal steps use one operation/target request; only a claimed completion or final budget/cycle stop receives a history-free result check. There are no candidate, region or form-preparation classifiers. Each observation allows at most four operation offers: a NONE target excludes that operation's candidates before the remaining offer is considered. A run permits at most 60 browser actions and 120 actual HTTP requests by default, including provider retries and text-helper calls.

The old footage and timing measurements describe the earlier policy; they are not performance or reliability measurements of the current loop.

Tests are offline. `uv run python scripts/check_guards.py` checks real controls in a local browser without model calls. `uv run python scripts/check_toggle_values.py` checks toggle state, retained submission tokens, and read-only facts without model calls. `uv run python scripts/check_hittest.py` checks that clipped and covered controls are not offered and that a wrapped link is clicked on a visible fragment. Live examples and recording scripts make paid API calls. `scripts/record_flights.py <new-folder>` captures original browser timestamps; `scripts/render_demo.py <recording-folder>` renders that verified run at 1× and crops out the Google account strip. Credentials and raw traces stay ignored.

---

[Browser Use](https://github.com/browser-use/browser-use) · [Browser Harness](https://github.com/browser-use/browser-harness) · [TypeSafe speculative fan-out](https://docs.typesafe.ai/patterns/fan-out)

The initial page and each activating input receive a bounded quiet window (one unchanged second, up to ten seconds). A second quiet window and freshness check gate completion. An observation is assessed once for each identical goal/result/baseline input: operation DONE reuses that verdict. This cannot guarantee that a server will never reject later. A preservation baseline records each control on its first observed URL, including pages reached by navigation. Exact repeated semantic state/action pairs stop as `cycle` instead of repeating a submit; changing text can distinguish legitimate carousel steps. Twenty stale ticks bound navigation churn. Model, text-helper, partial-delivery, and final-observation failures remain explicit terminal states with the last available observation.

The reader retains at most 100 visible non-select actions, 100 select-option actions, 20 offscreen reveal candidates, 120 stateful control facts. Disabled/readonly facts are observed without becoming targets. Boolean, pressed, selected, and expanded state remain distinct from submission tokens; named checkboxes do not send their submission tokens; radio tokens remain separate to distinguish options. Link destinations and model page URLs omit query strings, fragments and userinfo. Strings and request bytes are capped, omissions are exposed to the judgments, and omitted control facts prevent completion. Provider size errors remain failures; local byte caps are not tokenizer guarantees. Raw local traces can contain observed page content and current URLs; keep them private.

`Agent(..., model_call_budget=20)` caps both logical TypeSafe judgments and actual HTTP requests (including provider retries and text-helper calls) for a test run. `wire_calls` reports the actual request count. Operation selections and completion verdicts are reused when their observation input is identical; target heads can choose NONE instead of being forced to select a satisfied or unusable control. An exhausted paid-request cap returns `paid_request_budget` without sending another request.

First-observation preservation baselines are recorded only after a witnessed quiet window. New baselines carry `after_mutating_inputs`; a baseline first seen after a possible write cannot establish the original value. Observed anchor navigation is distinguished from field writes and button activation.

Preservation can remain unverified when a write redirects to a newly observed URL; post-write values alone cannot establish the originals.
