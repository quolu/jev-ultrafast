# Dynamic operation + target

The input is a natural-language goal. Every page observation builds an indexed table of accessible elements and their current values. One node receives one index, even when it supports both clicking and typing.

One TypeSafe request asks which operation to perform and which target would be appropriate for each available operation. The executor consumes only the target head corresponding to the selected operation. This avoids serial operation-then-target calls and rejects targets incompatible with the operation. Dropdown targets include a code-owned option index.

Operation and target questions receive the same next-step rules. Target criteria include current values and checked/selected state. The questions run independently: a target cannot read the operation answer, so its premise explicitly names the operation it assumes.

TYPE_TEXT sends the goal, selected field, visible page context, and recent actions to a small LLM. Its JSON must contain exactly one valid `text` value. The code does not extract quoted literals. A value can be reused after a stale decision only while the entire helper input is identical, and is discarded after a successful mutation.

## Completion evidence

Normal steps use the existing operation/target request. A claimed DONE is checked separately against current URL/title/text and settled initial/current control facts, without action history. Choices are `fulfilled`, `unmet`, and `not_observed`; only fulfilled probability at least 0.70 with fresh evidence and an unchanged second can finish. This is a model judgment, not proof of an arbitrary goal. Saving requires observed result evidence, not just matching inputs. Selection and completion judgments cache identical observations; waiting on the same page does not reroll them.

Navigation context, owning field names and destinations are observations included in target choices. REVEAL exposes an observed offscreen control. There is no extra region, candidate or form-preparation classifier. A NONE target removes the selected operation's candidates and retries selection from the remaining offer, at most four offers per observation.

Checkbox/radio/switch primary values are observed checked states, never HTML form-submission tokens. Radio submission tokens remain separate as `submission_value`; unnamed radios with an explicit value retain it in the choice label. Separate read-only facts include CSS-visible disabled and offscreen controls, while password, file, and hidden inputs remain excluded. Disabled controls cannot execute. `REVEAL` scrolls an observed offscreen enabled control into view without activating it; the next observation determines whether it can be hit.

## Runtime

One browser-side DOM snapshot supplies common HTML/ARIA roles, names, values, visible text, and executable targets. A WeakMap gives each actual node a code-owned identity; a Map keeps the live references used for execution. Replaced elements receive new identities, disconnected references are pruned, and navigation starts a new cache. These IDs are not CDP backend node IDs. Geometry is always read again immediately before input. A control is offered only if `elementFromPoint` at its centre, or at the centre of one of its client rects, lands inside it, which is the act guard's own test: a control clipped by a scroll container or under a banner is not offered only to be refused at input time, and a link wrapped over two lines is clicked on a visible fragment.

The model sees visible text. Background focus emulation keeps animation frames running in the owned tab. Screenshots are optional and disabled in library calls by default; `screenshots=True` or `record_dir=...` enables them. The inspector enables them explicitly. A continuous screencast can record a run separately.

Freshness compares semantic state instead of counting DOM mutations. Before a click/select, guards compare the document, full URL, viewport, safe form values/states, selected target, and nearby form/dialog/row context. Text generation, typing, scrolling, waiting, and completion use a full semantic comparison. The executor rechecks target visibility, enabled state, geometry, and click occlusion. Scoped guards intentionally permit unrelated visible content to change; this is a practical heuristic, not proof that arbitrary page changes are irrelevant to the goal.

Browser mutations are not retried by transport recovery. Completed execution is logged before the next observation, including when that observation encounters a navigation. An interrupted native-select or reveal evaluation stops because its change event may already have fired. Typing uses a browser select-all command followed by CDP text insertion, so existing input contents are replaced.

The next observation waits for up to two animation frames or 50 ms after an interaction. Editable ARIA comboboxes instead wait for visible options, capped at 200 ms. This avoids paying for a prediction before autocomplete suggestions arrive. An explicit WAIT remains 100 ms; network loading is never fast-forwarded in the recording.

## What changed after the first demo

The initial prototype used five manually prepared steps and copied quoted strings. That proved finite-choice browser execution but did not demonstrate task decomposition or text generation. The current policy removes that shortcut and uses the original goal throughout. Operation/target distributions replace the old flat-choice/lookahead/Noul arrangement.

The audit also found that treating every INPUT as editable misclassified checkboxes. Editable roles now control TYPE_TEXT availability. Tests cover checkbox/radio/button distinction, invalid operation/target outputs, stale decisions, text-cache invalidation, missing credentials, waits, and final-route verification.

## Boundaries

Sixty browser actions and 120 logical TypeSafe requests (including completion checks) bound a run. Budget exhaustion returns terminal `blocked` with a `stop_reason`; it does not raise a demo-budget exception. Up to 100 visible non-select candidates, 100 select-option candidates, and 20 offscreen reveal candidates are retained; truncated candidates cannot be selected. The service stays loopback-only, serializes inspector actions, and checks Host, Origin, and a local request token. Credentials remain server-side. Tabs share the existing Chrome profile.

The policy is generic, but two websites do not establish broad reliability. Name resolution covers common labels, ARIA references, and text; it is not the browser's full accessibility algorithm. Sampled visible nested scroll regions are supported; shadow roots, frames, canvas, uploads, obscured or unsampled scroll containers, pop-ups, and complex keyboard interactions can block progress. A valid action can still be wrong. Independent checks, rather than the model's DONE choice, determine whether the demonstrated task succeeded.

## Settlement, failures, and evidence reuse

Initial and post-input observations receive a one-second quiet interval, capped at ten seconds and twenty rereads. Completion requires that interval, a fresh assessment observation, and another unchanged second after the model call. A quiet interval is a bounded heuristic, not a guarantee about all future network activity. An unstable page can still offer a guarded action, but cannot complete. Result assessments are cached by their complete evidence input; DONE cannot reroll an unchanged result judgment. Baselines retain the first observation of each control on its URL, including controls first reached after navigation, capped at 500. Missing baseline/control evidence does not establish preservation.

Live target/control guards still bind clicks, selects and reveals; result freshness also gates completion. Semantic state/action pairs exclude transient node IDs and geometry and stop repeated writes as cycle. New visible result text distinguishes carousel steps. Model/action budgets remain the backstop.

The last logical TypeSafe call is reserved for assessment of the final observed state. Model and helper failures return terminal blocked; only their exception type is retained, never provider messages. Input interrupted after possible delivery is logged as uncertain and never retried. A stale post-input observation preserves the executed action; twenty stale ticks bound re-observation. Commands are serialized, including library predict/act/tick calls.

The reader retains 120 stateful facts, 100 visible non-select actions, 100 select-option actions, and 20 reveals, plus scroll/wait controls. Common ARIA pressed/selected/expanded and editable state is observed alongside native fields. All strings and model request bytes are bounded, truncation flags reach the model, and missing control facts prohibit done. Link query/fragment/userinfo is withheld; raw link changes remain bound by a browser-local revision. Current raw URLs and page text remain private trace data. These byte bounds do not claim an exact provider token count.

`Agent(..., model_call_budget=20)` caps both logical TypeSafe judgments and actual HTTP requests (including provider retries and text-helper calls) for a test run. `wire_calls` reports the actual request count. Operation selections and completion verdicts are reused when their observation input is identical; target heads can choose NONE instead of being forced to select a satisfied or unusable control. An exhausted paid-request cap returns `paid_request_budget` without sending another request.

First-observation preservation baselines are recorded only after a witnessed quiet window. New baselines carry `after_mutating_inputs`; a baseline first seen after a possible write cannot establish the original value. Observed anchor navigation is distinguished from field writes and button activation.
