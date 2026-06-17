# Implementation Plan — NOJA Invoice Approval Reference Demo

Derived from `NOJA_invoice_demo_SRD_v1.2.1.md`. This plan does **not** re-decide anything
in the SRD; it concretizes the build sequence (§8) into runnable steps with the exact data
shapes, signing mechanics, and verification each step must produce.

## 0. Guiding constraints (read once, hold throughout)

These are the failure modes that silently break the demo. Every step is checked against them.

- **`engine/` is domain-pure.** No invoice logic, no imports from `domain/`. Dependency arrow is `domain/ → engine/` only (§5.2). Enforced by review + one CI-ish import check.
- **Node 3 is a real judgment node.** Its judgment is *operational/execution-envelope authorization* ("this config is authorized to execute, with these tools, under this pinned model, within this envelope"), not "what happens to the invoice" (§3.1, MUST-FIX-FIRST). Its signature must be able to *lapse*.
- **Signing is real or the build halts.** `git tag -s` / `git verify-tag`, fail-loud if no key, never silently unsigned (§4.4, MUST-FIX-FIRST).
- **Lapse is engine-detected from pre-signed scope.** No human signs at lapse instant; the live human signature appears only at re-authorization (§4.5, MUST-FIX-FIRST).
- **JSON trail is canonical.** SQLite (if any) is a disposable index; the verifier reads JSON (§5.1, §6).
- **Anti-overbuild.** No backend, no auth, no registry/config-language, no frontend build toolchain, no role/permission machinery (role names are data strings). Stop if the viewer grows into a product (§5.3, §10).

A `PAY` decision = writing a `payment_authorized` trail event. Nothing else (§2.1).

---

## Step 0 — Repo scaffold + signing prerequisite (no domain code)

**Goal:** the skeleton exists and signing works (or fails loud) before any logic.

- Create the directory tree exactly as §5.2 (`engine/`, `domain/`, `artifacts/{anomaly,approval_policy,agent_composite,hitl_decisions,transitions}/`, `llm/`, `evals/`, `runs/`, `fixtures/`, `viewer/`, `trail/`).
- `requirements.txt`: resolve and pin exact versions of `pydantic-ai`, `pydantic`, `anthropic` at build time; commit. This file is later *named* as an environmental scope condition of the node-3 composite (§5.1) — no hash-checking machinery.
- `README.md`: add the **demo signing-key setup path** (§4.4) — instructions to generate a GPG key labelled "NOJA Demo Signing Key" and `git config` it, with the explicit caveat that this is verifiable-mechanics-only, not PKI-backed identity.
- `.gitignore`: add `viewer/trail_manifest.json` (regenerated working copy), `trail/`, `artifacts/` output bytes as appropriate, `.venv`, SQLite index file.

**Runnable proof:** `python -c "from engine.sign import ensure_signing_key; ensure_signing_key()"` either passes (key present) or exits non-zero with setup instructions.

---

## Step 1 — `engine/` against a trivial fake domain (no LLM, no invoices)

This isolates and proves the **novel** work (node abstraction + network signature lifecycle) before any domain/model complexity. SRD §8.1.

### `engine/sign.py` — signed Git tag wrapper
- `ensure_signing_key()` — checks `git config user.signingkey` + key availability; raises with setup instructions if absent. **Never downgrades to unsigned.**
- `sign_artifact(path, node, artifact_id) -> SignedRef` — commits the artifact bytes, computes content hash, creates `git tag -s artifact/<node>/<artifact_id>/<short_hash> -m <msg>`. Returns `{tag, content_hash}`.
- `sign_transition(record, signature_id, to_state, ts) -> SignedRef` — tag `transition/<signature_id>/<to_state>/<timestamp>`.
- `verify(tag) -> bool` — wraps `git verify-tag`.
- Sigstore/Rekor mentioned in a comment as the upgrade path; not built.

### `engine/signature.py` — state machine + scope + lapse + fallback
- `State` enum: `Drafted, Provisional, Active, Suspended, Lapsed, Revoked, Superseded, Archived` (all defined; only Drafted→Active and Active→Lapsed exercised, §4.1).
- `Scope` dataclass: four axes — `domain`, `temporal`, `condition` (with `environmental` incl. lockfile ref, and `behavior_envelope` incl. `model_id`), `volume`. All representable; only behavior-envelope monitored (§4.2).
- `FallbackSet`: subset of `{Halt, Safe-mode, Drain-then-halt, Cut-over}`; demo pre-signs `Safe-mode` (§4.3).
- `Signature`: holds scope, fallback set, current state, `prior_signature_ref`.
  - `detect_lapse(live_model_id) -> bool` — compares live model id to pinned `behavior_envelope.model_id`.
  - `lapse(live_model_id, attestor="engine-detector") -> TransitionRecord` — generates Active→Lapsed record drawn from pre-signed scope + fallback; **no human sign**.
- Transition record matches §6 schema exactly (`from_state`, `to_state`, `trigger`, `previous_scope_condition`, `observed_condition`, `fallback_selected`, `transition_attestor`, `prior_signature_ref`, `transition_artifact_hash`).

### `engine/trail.py` — canonical JSON writer
- `write_event(record) -> event_id` — one JSON file per event in `trail/`. Fields per §6 (event_id, timestamp, pipeline, invoice_id, node, function, decision/output; NOJA-only: accountable_role, signed_artifact_ref, scope, signature_state, upstream_ref).
- Optional SQLite index generated *from* JSON, clearly disposable; skip unless it visibly helps (lean toward skipping for a ~dozen records).

### `engine/node.py` — `JudgmentNode`
- Holds the four NOJA functions (prediction / judgment / execution / accountability) bounded by one `accountable_role` string.
- `run(prediction_input, upstream_ref) -> ExecutionOutput` — runs functions, writes trail records carrying `upstream_ref` so edges are reconstructible (§3.3).

**Runnable proof (the gate for Step 2):** a `engine/_smoke.py` exercising a fake one-node domain that (a) runs a node, (b) signs an artifact via a real Git tag, (c) writes a traceable JSON record, (d) transitions Active→Lapsed as an engine-detected transition with fallback drawn from the pre-signed set, (e) shows `sign.py` failing loud when the signing key is unset. `git verify-tag` passes on the produced tags.

---

## Step 2 — `llm/` + `domain/` (real Pydantic AI agent, real Claude)

SRD §8.2. Model: Claude via Anthropic API, model-agnostic through Pydantic AI so the swap is one line.

### `llm/client.py`
- Thin wrapper exposing the **single** place the model id is set (so the swap in Step 6 is one line). Model A pinned here initially.

### `llm/cache.py` (~40–60 lines, rip-out-able)
- `key = hash(model_id + prompt)` → stored response JSON. Real call on miss, replay on hit. Real calls in dev, cached replay for reproducible demos.

### `fixtures/`
- `invoices.json` + `purchase_orders.json`: hand-authored, the **8-row minimum matrix** (§2.2) INV-001..INV-008 with the exact cases/expected outcomes. INV-002 is the near-match ($4,800 vs $5,000 PO) that powers the latent-policy contrast. At least one PAY fixture must stay PAY under both models.

### `domain/` nodes (knows nothing the engine needs)
- `anomaly.py` (node 1): anomaly scoring; signed artifact = anomaly threshold policy; role = Finance Controls Lead.
- `approval_policy.py` (node 2): design-time approval policy; **the 5% tolerance band lives here**; role = Head of AP.
- `agent.py` (node 3): Pydantic AI agent + tool defs; produces the **composite artifact** (policy text + system prompt + tool defs + pinned model id + behavior envelope); role = AI Controls Lead.
- `escalation.py` (node 4): HITL escalation decision capture; per-instance signed decision; role = AP Manager.

**Runnable proof:** agent reads a fixture invoice, checks the PO, returns a decision; cache replays deterministically.

---

## Step 3 — `runs/noja.py` + `verify.py` (wire the four-node network)

SRD §8.3. Wire node1→node2→node3→(node4 on escalate) end-to-end on the fixture set, each producing a signed artifact and traceable trail records with `upstream_ref` chaining.

### `verify.py` (the proof artifact for skeptics)
- From any final PAY/HOLD/ESCALATE outcome, replay the chain back through every node's prediction → judgment artifact → signature → role, reading **JSON only**, running `git verify-tag` on each signed ref. Fails on any gap (§3.3, §6).

**Runnable proof:** `python verify.py` reconstructs every final outcome to signed artifacts + named roles with **no gaps**, and all tags verify.

---

## Step 4 — `runs/blackbox.py` (the thin unsigned counterpart)

SRD §8.4 / §3.4. Single Pydantic AI agent, same model, same tools, same invoices, all four functions in one loop.

- Writes a **deliberately thin** trail: decision + free-text rationale only. No signed artifacts, roles, scope, fallback, or upstream chain. Do not enrich it.
- System prompt contains the tolerance as **latent natural language**: e.g. *"Invoices within 5% of an approved PO may be paid unless anomalous."* — matching node 2's actual tolerance, so both pipelines reach the same outcomes. Same policy, one signed, one latent (the §3.4 crux).

**Runnable proof:** black-box processes the same fixtures, produces comparable decisions, and `verify.py` finds **nothing to reconstruct** — faithfully.

---

## Step 5 — `evals/` (genuinely green on both models)

SRD §8.5 / §7.1.

- `evals/cases.json`: small, stable, unambiguous cases spanning the coverage categories (clean match, near match, mismatch, duplicate, no PO, high-value escalation). Not a benchmark.
- `evals/suite.py`: runs cases against the currently pinned model, returns per-case pass/fail + aggregate green/red.
- **Verify during build** that it is green on model A *and* model B. If a case fails on model variance, replace it only with another in the same coverage category — never tune to a result (§7.1 honesty requirement).

**Runnable proof:** suite is green on both model A and model B; result surfaced into the trail.

---

## Step 6 — `runs/swap_demo.py` (the primary punchline)

SRD §8.6 / §7.2. Orchestrates the exact six-step sequence:

1. Both pipelines run under model **A** (pinned). Eval green on both. NOJA composite **Active**, scoped to model A.
2. Pinned model → **B** (one-line change in `llm/client.py`).
3. Eval re-runs under model B — **green on both sides**. Surface prominently, do not hide.
4. **Black-box:** keeps writing `payment_authorized` events (green ⇒ fine). Every such event in this window is the demonstrated harm — `grep`-able in the trail.
5. **NOJA:** lapse detection fires (behavior-envelope scope = model A no longer holds). Composite transitions **Active → Lapsed** via engine-attested transition record referencing the pre-signed scope + fallback. **Safe-mode** selected from the pre-signed set; invoices above the low threshold **held**; no further `payment_authorized` events.
6. **NOJA re-authorization (shown explicitly):** fresh green model-B eval presented to the **AI Controls Lead**, who **signs** a new composite authorizing model B. New signature **Active**, scoped to model B. Execution resumes. This is the **only** live human signature in the swap sequence.

**Runnable proof:** trail shows black-box payments in the unsigned window; NOJA lapse → safe-mode hold → re-eval → human re-sign → resume. Lapse record names `engine-detector` attestor + `prior_signature_ref`; re-auth record names a human `accountable_role`.

---

## Step 7 — `viewer/index.html` + manifest generation

SRD §8.7 / §7.3 / §5.1. Single static HTML, no backend, no build step, no framework.

- A small generator (part of the run) collects `trail/` records into one `viewer/trail_manifest.json`.
- `viewer/index.html` reads **only** that manifest. Holds **no** decision/verification/reconstruction logic — only filtering/grouping/sorting/rendering.
- **Brand (corrected against the real `/diagrams` assets — see note below):** warm "paper" aesthetic, **not** the dark blue→pink the SRD prose names. Match the diagrams' CSS variables exactly:
  ```css
  --paper:#f4ede1; --paper-2:#e8dfce; --ink:#1c1814; --ink-soft:#4a3f33;
  --ink-faint:#8a7d6c; --accent:#a8421f; /* rust */ --rule:#c9bca7;
  ```
  Fonts: **Fraunces** (serif, headings/captions, italic for emphasis), **IBM Plex Mono** (meta bars, labels, uppercase tracked), **IBM Plex Sans** (body). The three `diagrams/*.html` files are the canonical brand template — reuse their meta-bar / heading / legend / caption structure for the viewer.
- Renders both pipelines **side by side**: same green eval badge post-swap on both; black-box's growing payment list in the unsigned window; NOJA's lapse → safe-mode hold → re-eval → human signature → resume. Caption frames the punchline (§7.3).
- Serve with `python -m http.server 8000` (browsers block `file://` sibling reads). **No npm/bundler/framework.**
- GitHub Pages `site/` publishing is **out of build scope** (§7.3 note) — do not build a deploy pipeline.

**Runnable proof:** `python -m http.server` + open viewer shows the full side-by-side narrative from the manifest alone.

---

## Acceptance checklist (mirrors SRD §9)

Track these as the definition of done:

- [ ] Both pipelines process the same fixtures and record decisions.
- [ ] Node 3 has a real operational/execution-envelope judgment + a composite signature that can lapse.
- [ ] NOJA final outcomes reconstruct to role + signed artifact + scope, no gaps, from JSON alone.
- [ ] Black-box trail is faithfully thin (no reconstruction possible); tolerance present as unsigned prompt text.
- [ ] Tolerance band is a signed artifact (Head of AP) on NOJA, prompt-resident on black-box.
- [ ] `sign.py` fails loud with no key; never unsigned. `git verify-tag` passes for every NOJA artifact.
- [ ] Model swap fires engine-detected lapse; transition names engine-detector + references pre-signed composite; safe-mode drawn from pre-signed set.
- [ ] Eval genuinely green on both models, categories preserved, surfaced on both pipelines post-swap.
- [ ] Black-box writes `payment_authorized` in the unsigned window (grep-able); NOJA stops on lapse and shows the AI Controls Lead re-signing before resuming.
- [ ] Viewer reads only the manifest, no decision/verify/reconstruct logic, no frontend build stack.
- [ ] Pinned deps committed and named in node-3 composite scope (no drift machinery).
- [ ] `engine/` has zero invoice code and zero `domain/` imports.

## Source-spec grounding (NOJA v0.6)

Read the upstream spec at `David-021-events/NOJA` (`noja_v0_6.md`). The demo is effectively a
**Level-3 conformant** (§6.3) reference implementation of one small network:

- §2 four-function node (prediction/judgment/execution/accountability), one accountable role each — maps to `engine/node.py`.
- §3.2 edge traceability (gap-free reconstruction) — the hard requirement `verify.py` proves.
- §4.1 state machine, §4.2 fallback set, §4.3 four scope axes, §4.4 five mechanics properties, §4.5 composite artifact — map to `engine/signature.py` + `engine/sign.py`.
- §5 granularity rule — *why* the network is four nodes, not one. The SRD's split (anomaly / approval-policy / agent-composite / escalation-HITL) is exactly the §5 + §3.1 decomposition (judgment type changes; cosigners decompose to upstream nodes). The black-box pipeline is the §5 "End-to-End Agency" anti-pattern made visible.
- §4.5 version-pin + behavior envelope — the lapse trigger. Honor the spec's own caveat (§4.5 commentary): a hosted version id is a *contract*, not byte-identity, and the provider attestation policy is itself an environmental scope condition. Reflect this in the composite scope; don't overclaim.

## ⚠️ Resolved conflict — viewer brand

The SRD §5.1 prose says the viewer brand is "dark-first, blue-to-pink gradient." **The actual
`diagrams/*.html` assets are the opposite** — a light warm *paper* palette (cream `#f4ede1`,
dark ink `#1c1814`, **rust** accent `#a8421f`), Fraunces + IBM Plex Mono/Sans. All three diagrams
agree. Since the SRD's binding instruction is "**matching the author's existing `/diagrams`
aesthetic**," I'm treating the diagrams as ground truth and the "dark/blue-pink" wording as stale.
The viewer will use the paper palette. **Confirm if a dark theme was actually intended.**

## Open items to confirm before/at build time

1. **Signing key** — confirmed *not* configured on this machine (`user.signingkey` unset, no GPG secret keys). Step 0 halts until the demo-key setup path (§4.4) is run. **Blocker for the whole build.**
2. **Anthropic API access** — confirmed `ANTHROPIC_API_KEY` *not* set. Needed for the real Claude calls in Step 2+; the record/replay cache covers reproducible runs afterward. **Blocker for Step 2 onward.**
3. **Brand** — resolved to the paper palette from the real diagrams (see conflict note above); confirm if a dark theme was actually intended.
