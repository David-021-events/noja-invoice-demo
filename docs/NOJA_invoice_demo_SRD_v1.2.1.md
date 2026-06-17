# System Requirements Document
## NOJA Reference Implementation — Autonomous Invoice Approval

**Version:** 1.2.1
**Status:** Build-locked. Written to be handed directly to Claude Code.

**Change in v1.2.1.** Added one out-of-build-scope note under §7.3 recording the local-viewer vs. published-`site/`-viewer distinction (GitHub Pages publishing is a manual step, not part of the build). No build-relevant changes.

**Changes in v1.2 (second external review pass).** Nine precision and quality fixes, none adding scope. Two materially improve build quality: a concrete fixture matrix (§2.2) and a concrete definition of "money movement" as a `payment_authorized` trail event (§2.1) so the central harm is inspectable rather than narrated. The rest remove residual wording contradictions and overclaims: fallback-selection wording reconciled across §4.3/§7.2 (engine-attested, drawn from pre-signed set — no fresh signature at lapse); a sanctioned demo-signing-key setup path (§4.4) so the fail-loud rule doesn't wall off a fresh machine; the composite-signer split softened from "correct governance" to "more credible for the reference implementation" (§3.1); Step 0 reworded so the coding agent prefers the settled interpretation rather than freezing (§8); "viewer holds no logic" clarified to "no decision/verification/reconstruction logic" (§5.1); the "only live human signature" criterion scoped to the swap sequence (§9); and a dedicated `artifacts/` directory for signed bytes (§5.2).

**Changes in v1.1 (first external review pass).** Ten revisions, three build-stoppers resolved before step 1:
- **MUST-FIX-FIRST §3.1:** the Agent execution node now has an explicit judgment type (operational/execution-envelope authorization). A judgment node with no judgment is a spec-conformance error and would make the model-swap punchline impossible.
- **MUST-FIX-FIRST §4.4:** exact signed-Git-tag mechanics, tag naming, and *fail-loud-if-no-signing-key* behavior. "Reuse Test 1" was not actionable from this repo and would cause the signing layer to be faked.
- **MUST-FIX-FIRST §4.5:** reconciliation of "automatic lapse" with "every transition is signed" — authority is pre-signed in the scope/fallback; the engine detects and records, it does not pretend a human signs at the instant of lapse.

The remaining seven (composite-artifact signer split §3.1; transition artifact format §6; eval-case wording §7.1; pinned dependencies as scope §5.1; static-viewer manifest §5.1/§7.3; JSON-canonical-SQLite-index §5.1/§6; black-box prompt location §3.4) are fold-in-as-you-go quality and credibility improvements. Two of them (§3.1 signer split, §5.1 dependency pinning) carry anti-overbuild fences — read them.
**Author context:** This is a *reference implementation* of NOJA v0.6, not a product. The domain (invoice approval) is a vehicle for demonstrating the architecture. Every design choice below favours simplicity and legibility over generality. The target audience for the running demo is model-risk and AI-governance practitioners. The expected operational scale is a single-machine demo, not a multi-user service. Do not build for scale, concurrency, or multi-tenancy. Do not add abstractions that aren't exercised by the demo described here.

---

## 1. Purpose and scope

### 1.1 What this system is

A runnable demonstration that processes the **same set of invoices** through two pipelines side by side:

- A **black-box agent** — one LLM agent that observes, interprets, decides, and acts in a single loop.
- A **NOJA-wrapped network** — the same underlying agent decomposed into a directed network of judgment nodes, each carrying a named accountable role, a signed artifact, a declared scope, and a fallback.

Both produce decisions on each invoice (pay / hold / escalate). The point of the system is to make the **difference in accountability** visible, not the difference in outcomes. Outcomes will often be similar; the architecture around them is not.

### 1.2 What this system is NOT

- Not a product, not a SaaS, not multi-user. Scale assumption: ~a dozen people will ever look at it, mostly one at a time.
- Not a general NOJA framework for arbitrary domains. The `engine/` is domain-agnostic by clean separation only — not by a plugin system, registry, or configuration language. Swapping domains means writing new files in `domain/`, not editing a config.
- Not a real accounts-payable tool. Invoice/PO data is synthetic fixture data.
- Not an eval *harness*. The eval suite (§7) only needs to be convincingly green and to demonstrate one specific property. It is not a general testing framework.

### 1.3 The three things a viewer must walk away convinced of

In priority order. The build must make all three legible; the third is the primary punchline.

1. **Traceability contrast.** On the NOJA side, any action traces back to a named signer, the exact signed artifact, and the scope it was valid under (NOJA v0.6 §3.2 edge traceability, §4.4 reconstruction-complete). On the black-box side, there is nothing to trace — the absence is the point.
2. **Latent policy surfaces.** A decision both pipelines make (e.g. accepting an invoice that is close-but-not-equal to its PO) is governed, on the NOJA side, by a *signed* tolerance policy owned by a named role. On the black-box side that same tolerance lived in the agent's prompt/reasoning and was never signed by anyone (NOJA v0.6 §2.1 latent policy).
3. **The green-but-unsigned window (PRIMARY PUNCHLINE).** When the pinned model version changes mid-run, an accompanying eval suite **stays green on both sides**. The black-box agent keeps paying invoices on the strength of green alone. The NOJA network *also sees green* but lapses the signature anyway — because the signed behavior envelope was scoped to the prior model version (§4.3 behavior-envelope conditions, §4.5 composite artifact) — drops to safe-mode, and **halts money movement until a named human reviews the fresh eval and re-signs.** The demonstrated harm is that **execution ran in the interval where the new model was green but unauthorized.**

### 1.4 The argument the demo must survive (design constraint, not optional)

A sophisticated eval-maximalist will object: *"You re-ran the eval on the new model and it's green, so NOJA added nothing."* The build MUST NOT stage evals as blind or wrong. It must concede that a green eval on the new model is real and sufficient *as evidence*, and still show the gap: **evidence is not authorization, and the black-box system executed during the window between "model changed" and "someone confirmed and authorized the new model."** Therefore:

- The NOJA side MUST **visibly run the re-eval** after the model swap and MUST **show a named human signing** an authorization of the new model against that green eval. The re-eval is not hidden. NOJA is shown turning a green eval into an *authorized* one, and refusing to act in the unsigned interval.
- The supporting points (authorization ≠ measurement; coverage adequacy is itself an unsigned judgment) should be representable in the trail but need not dominate the UI.

---

## 2. The domain: invoice approval

### 2.1 Decision and what "PAY" means

For each invoice, the system decides one of: **PAY**, **HOLD**, **ESCALATE**.

**Definition of money movement (concrete, inspectable).** Do NOT integrate with any payment system. For the demo, **PAY means writing a `payment_authorized` event to the trail** — that event *is* the money movement. "Halts money movement" means no further `payment_authorized` events are written. The black-box harm in the swap sequence is represented precisely as: `payment_authorized` events written after model B's eval is green but before any model-B authorization signature exists (§7.2). This makes the central harm a thing a skeptic can `grep` for in the trail, not a claim in narration.

### 2.2 Inputs (synthetic fixtures)

Each invoice is a JSON object with at least: invoice id, vendor, line items, total amount, referenced PO number. A parallel fixture set of purchase orders (vendor, PO number, authorized amount, status). Keep fixtures in `fixtures/`. Hand-authored, version-controlled, human-readable.

**Minimum fixture matrix.** Generate at least these eight; each row maps to a coverage category and an expected outcome. Do not generate weaker or redundant fixtures in place of these.

| ID | Case | Expected | Role in the demo |
|----|------|----------|------------------|
| INV-001 | clean match, active PO, below threshold | PAY | baseline |
| INV-002 | near match within 5% tolerance ($4,800 vs $5,000 PO) | PAY | **powers the latent-policy contrast — the tolerance band is the contested signed judgment** |
| INV-003 | amount exceeds tolerance | HOLD | |
| INV-004 | no PO | HOLD | |
| INV-005 | duplicate invoice id/vendor/amount | HOLD | |
| INV-006 | closed PO | HOLD | |
| INV-007 | high-value clean match above escalation threshold | ESCALATE | exercises the HITL node (4) in the normal run, not only the swap |
| INV-008 | anomalous vendor or line-item pattern | ESCALATE | exercises the anomaly node (1) |

At least one PAY-category fixture (e.g. INV-001 or INV-002) must remain a PAY under both model A and model B, so that `payment_authorized` events are present in the swap window and the black-box harm is demonstrable.

---

## 3. The NOJA network design

This is the load-bearing design. It is the part *not* proven by the author's prior Test 1 (which proved single-node signing). The novel work here is the **node abstraction and how a network of nodes wires together while preserving edge traceability** (§3.2).

### 3.1 The four nodes

Per NOJA v0.6 §2, every node contains four distinguishable functions (Prediction, Judgment, Execution, Accountability) bounded by exactly one accountable role (§2.4). The network is a directed graph where one node's execution output becomes the next node's prediction input (§3).

| # | Node | Dominant function | Judgment type | Signed artifact | Accountable role |
|---|------|-------------------|---------------|-----------------|------------------|
| 1 | **Anomaly** | Prediction | Quantitative | Anomaly threshold policy | Finance Controls Lead |
| 2 | **Approval policy** | Design-time judgment | Quantitative + tolerance | Approval policy (the tolerance band lives here) | Head of AP |
| 3 | **Agent execution** | Agentic execution | **Operational / execution-envelope authorization** | Composite artifact: policy text + system prompt + tool defs + pinned model id + behavior envelope | **AI Controls Lead** |
| 4 | **Escalation HITL** | Per-instance judgment | Qualitative | Per-instance signed decision | AP Manager |

**On node 3's judgment type (MUST-FIX-FIRST).** Every judgment node MUST contain all four functions including a real judgment (§2). Node 3's judgment is NOT "what should happen to this invoice" — that is node 2's design-time judgment. Node 3's judgment is the *operational authorization*: **"this agent configuration is authorized to execute this signed policy, with these tools, under this pinned model version, within this behavior envelope."** That is the §4.5 composite-artifact judgment. This is not pedantry: the model-swap punchline depends on node 3 being a genuine judgment node whose signature can *lapse*. If node 3 were a runtime wrapper with no judgment, there would be nothing to lapse and the whole demonstration collapses.

**On the composite signer (anti-overbuild fence).** The composite (node 3) is owned by an **AI Controls Lead**, separate from the Head of AP who owns the business policy (node 2). This split is the **more credible governance choice for the reference implementation**: business-policy judgment and execution-envelope judgment are different judgment *types*, and §3.1 requires them to decompose to different nodes/roles when types differ. (In a real organization this ownership could sit with AP, Finance Systems, Model Risk, or an AI Governance function — the demo does not need to make a universal claim, only a credible one.) It also makes the model-swap re-sign more credible: the person re-authorizing model B is the controls owner, not the AP head signing a model decision outside their competence. **FENCE: this is two named strings in the fixtures. It is NOT a roles/permissions system, an access-control layer, or a user model. Do not build role machinery. The role names are data, not code.**

The decomposition is honest under §5 (the granularity rule) because (a) the judgment *type* changes between the quantitative anomaly/approval logic and the qualitative escalation call, and (b) a rejection of any node's output must trace to a single revisable signature. Do not collapse these into fewer nodes for convenience; the decomposition *is* the spec working as intended (§5 commentary).

### 3.2 Why the agent is a separate node from the policy

The **Approval policy node (2)** owns the *signed policy* — including the tolerance band — accountable to the Head of AP. The **Agent execution node (3)** owns the *composite artifact* (§4.5): the policy text plus the system prompt, tool definitions, the version-pinned model identity, and the behavior envelope — accountable to the **AI Controls Lead**. The agent executes *within* what node 2 signed, under the execution envelope that node 3's owner signed. This separation does two things for the demo: it shows the tolerance is signed *business* policy (node 2, Head of AP) rather than something the agent invented — the latent-policy contrast — and it puts the *model version* under a distinct execution-envelope signature (node 3, AI Controls Lead) so the model-swap lapse and re-sign land on the right accountable role.

### 3.3 Edge traceability requirement

Every edge MUST be reconstructible (§3.2). When node 1's execution output feeds node 2's prediction input, the trail record for node 2 MUST reference the upstream signed artifact and event that produced its input. From any final PAY/HOLD/ESCALATE outcome, the full path back through every node's prediction → judgment artifact → signature → accountable role MUST be replayable from the trail files alone, with no gaps. This is a hard requirement; an untraceable edge makes the network non-conformant regardless of node conformance.

### 3.4 The black-box counterpart

A single Pydantic AI agent, same model, same tools, same invoices, performing all four functions in one loop. It writes a deliberately **thin** trail: the decision and a free-text rationale, but **no signed artifacts, no named roles, no scope, no fallback**. The thinness is not a bug to fix — it is the faithful representation of the black-box condition. Do not enrich the black-box trail to make it "fair." Its poverty is the demonstration.

**Black-box latent policy location (required for a fair contrast).** The black-box agent MUST use the *same* tolerance policy as the NOJA approval node — but expressed in its **system prompt as natural language, never as a separately signed artifact.** Concretely, the black-box system prompt must contain a line equivalent to: *"Invoices within 5% of an approved PO may be paid unless anomalous."* (Match the actual tolerance used by node 2 so both pipelines reach the same outcomes.) This is the crux of the latent-policy point: same policy, same behavior, but on the black-box side the tolerance is buried in a prompt that no named role signed, scoped, or can be held accountable for. Do NOT give the black-box a *different*, weaker, or absent tolerance — that would make the contrast "NOJA does more," which is false. The honest contrast is "identical policy, one signed and one latent."

---

## 4. The signature lifecycle (engine)

Implement the NOJA v0.6 §4 signature model. Scope it to exactly what the demo exercises — do not implement states or features the demo never reaches.

### 4.1 States (§4.1)

Implement the state set: Drafted, Provisional, Active, Suspended, Lapsed, Revoked, Superseded, Archived. The demo *exercises* at minimum: Drafted → Active (onboarding), and Active → Lapsed (the model-swap event). Implement the others as valid enum states with signed transitions, but do not build elaborate machinery around states the demo never enters. Every state transition MUST be a recorded event (signer-or-detector, trigger, timestamp, resulting fallback where applicable). **Note on what "signed" means for an automatic transition — see §4.5; not every transition carries a fresh human signature at the instant it fires.**

### 4.2 Scope (§4.3)

Every signature declares scope along the four axes: domain, temporal, condition (with environmental and behavior-envelope sub-axes), and volume. The **behavior-envelope condition** is the one the demo turns on: the composite artifact's signature is scoped to a pinned model version. When the model version changes, that scope condition ceases to obtain and the signature MUST transition to **Lapsed** automatically via lapse detection. The other axes must be *representable and declared* in the signed artifact but need not be elaborately monitored.

### 4.3 Fallback (§4.2)

Every Active signature names a fallback set drawn from: Halt, Safe-mode, Drain-then-halt, Cut-over. The demo uses **Safe-mode** on lapse: a pre-signed minimal-action policy that holds all invoices above a low threshold for human review. The fallback selection on the lapse transition MUST be recorded in the transition event and MUST reference the pre-signed fallback set that authorized it. (This is *not* a fresh signature at lapse time — the authorizing signature was applied when the Active composite was signed; see §4.5.)

### 4.4 Mechanics and signing prerequisites (§4.4) — MUST-FIX-FIRST

A signature MUST be artifact-bound (attaches to specific bytes / content hash), identity-verifiable, timestamped, tamper-evident, and reconstruction-complete. The mechanism is **signed Git tags (GPG or SSH)**. NOJA is mechanism-neutral and property-bound — signed Git tags satisfy all five properties for this demo. Sigstore/Rekor is the documented upgrade path; mention it in comments only, **do not build it.**

This subsection is build-critical because the signing layer cannot be inferred or "reused" from anything in the current repo (the repo is spec + diagrams only; there is no prior implementation to copy). Implement exactly this:

**Signing prerequisites.** The implementation assumes the developer has a local GPG or SSH signing key configured for Git. The build MUST verify this at startup and **fail loudly with setup instructions if no signing key is available. It MUST NOT silently downgrade to unsigned tags.** A faked or unsigned signing layer invalidates the entire demonstration — the signatures *are* the point.

**Mechanics.**
- `git tag -s <tag> -m <message>` creates a signed artifact tag. The tag binds to the committed bytes of the artifact (content hash), satisfying artifact-bound + tamper-evident.
- `git verify-tag <tag>` (equivalently `git tag -v <tag>`) verifies the signature, satisfying identity-verifiable.
- Each signed NOJA artifact (anomaly threshold policy, approval policy, composite artifact, per-instance HITL decision, and each state-transition record) is committed and tagged.

**Tag naming convention.**
- Artifacts: `artifact/<node>/<artifact_id>/<short_hash>`
- Transitions: `transition/<signature_id>/<to_state>/<timestamp>`

**Failure behavior.** No signing key → halt with a clear message telling the developer how to configure a GPG/SSH signing key for Git. Never proceed unsigned.

**Sanctioned demo-key setup (so fail-loud doesn't wall off a fresh machine).** The README MUST include one explicit path for configuring a local signing key. If the developer does not already have one, they may generate a **demo-only GPG key clearly labelled "NOJA Demo Signing Key"** and configure Git to use it. This is acceptable for a local reference implementation because the point is *verifiable signing mechanics*, not production identity infrastructure: the demo key satisfies the artifact-bound, timestamped, tamper-evident, and reconstruction-complete properties and lets `git verify-tag` pass. It does NOT provide production-strength independent identity — say so plainly in the README so a sophisticated reader is not misled into treating a self-generated demo key as PKI-backed identity. Production deployments would substitute organizational PKI or Sigstore (out of scope here).

### 4.5 Reconciling automatic lapse with signed transitions (§4.1–4.3) — MUST-FIX-FIRST

There is an apparent tension between "lapse is automatic" (§4.2 above) and "every transition is signed" (§4.1). Resolve it as follows, which is both buildable and truer to the spec:

**The authority for a lapse is pre-signed, not signed at lapse time.** When the AI Controls Lead signs the composite (node 3) into Active, they sign — as part of that artifact — both the scope conditions (including the pinned model version, §4.3) *and* the fallback set (§4.2). That signature *is* the human authority for what happens when scope breaks. The human pre-authorized the lapse behavior at signing time.

**At lapse time, the engine detects and records; no human signs in the moment.** Lapse detection is automatic: the engine compares the live model id against the pinned scope condition, finds a mismatch, and **generates** the Active → Lapsed transition record from the pre-signed scope rule. The fallback (Safe-mode) is selected from the **pre-signed fallback set** — selection is determined by the prior signed artifact, not by a fresh human act. The transition record is committed and tagged with the **engine/detector key**, attesting "the engine observed this pre-signed condition fire," which is a different and honest claim from "a human authorized this now."

**The human signature appears at re-authorization, where you actually want it.** The visible human act in the demo is the AI Controls Lead **re-signing** a new composite that authorizes model B against the fresh green eval (§7.2 step 6). That is a real, live human signature — and it is the only place one is needed. Do NOT stage a human signing at the instant of automatic lapse; it would be false and a practitioner would notice.

Summary the build must honor: **lapse = engine-detected from pre-signed scope; fallback selection = drawn from pre-signed set; live human signature = only at re-authorization.**

---

## 5. Architecture and module map

### 5.1 Language and stack

- **Python 3.11+.** Matches the author's prior tooling.
- **Agent framework: Pydantic AI** (MIT-licensed, minimal, typed tools, model-agnostic). The model-agnostic property is load-bearing: swapping the model to trigger the lapse must be a one-line change.
- **Model:** Claude via the Anthropic API (real calls in development). Model-agnostic through Pydantic AI.
- **Pinned dependencies (treat drift as part of the execution envelope).** Pin exact versions: `pydantic-ai==<pin>`, `pydantic==<pin>`, `anthropic==<pin>` (resolve the specific versions at build time and record them). Commit a lock file. **Name the lock file as an environmental scope condition of the node-3 composite signature (§4.2):** if the demo's thesis is signed execution conditions, an unpinned framework is an unsigned moving part — a live counterexample to the argument sitting in the repo. **FENCE: pinning + naming the lock file in scope is sufficient. Do NOT build dependency-hash-verification machinery, a custom resolver, or runtime drift-checking. A lockfile and a scope declaration, nothing more.**
- **Signing:** signed Git tags (GPG/SSH). See §4.4 for exact mechanics and the fail-loud-if-no-key requirement.
- **Storage / trail (JSON canonical, SQLite disposable).** The **canonical** audit trail is one JSON file per trail event on disk (`trail/`). **The JSON files ARE the §4.4 reconstruction-complete audit trail.** SQLite, if used at all, is a **disposable convenience index generated from the JSON** — never a source of truth. If SQLite and JSON ever disagree, JSON wins, and the verifier (§6) MUST read JSON, not SQLite. (For a ~dozen-record demo SQLite is optional; include it only if it genuinely helps the viewer, otherwise drop it to remove a sync surface.)
- **Record/replay cache:** thin local module. Hash (model id + prompt) → stored response JSON. Real call on cache miss; replay on hit. Real calls during development; cached replay for reproducible demos. Target ~40–60 lines, its own file.
- **Eval module:** small fixed suite, pass/fail, surfaced in the trail and viewer. See §7.
- **Viewer:** a single static HTML file, no backend, no build step, no framework. Brand: dark-first, blue-to-pink gradient, Fraunces / IBM Plex Mono typography, matching the author's existing `/diagrams` aesthetic. The viewer is deliberately plain and read-only: it **holds no decision, verification, or reconstruction logic — it only renders the manifest.** (Normal presentation code — filtering, grouping, sorting, rendering events — is expected and fine; what it must not contain is anything that *decides*, *verifies a signature*, or *reconstructs a chain*. Those live in the engine and `verify.py`.) **Data source: a single generated `viewer/trail_manifest.json`** (the engine/run produces it by collecting the `trail/` JSON records into one file). The viewer reads that one manifest. Browsers block `file://` reads of sibling files, so serve with a trivial static server (`python -m http.server 8000`) — still no backend, no app server, no build stack. **Do NOT let Claude Code introduce a frontend build toolchain (npm, bundlers, frameworks) to work around file access; the manifest + static server is the whole solution.**

### 5.2 Module map and rip-out boundaries

```
noja-invoice-demo/
  engine/                 # PERMANENT. Domain-agnostic NOJA reference impl.
    node.py               #   JudgmentNode: prediction / judgment / execution / accountability
    signature.py          #   Signature: state machine, scope, lapse detection, fallback selection
    trail.py              #   writes canonical JSON audit records (SQLite index optional/disposable)
    sign.py               #   signed Git tag create/verify wrapper; fails loud if no signing key
  domain/                 # SWAPPABLE. Invoice-specific. Knows nothing the engine needs.
    anomaly.py            #   node 1: anomaly scoring
    approval_policy.py    #   node 2: design-time approval policy (tolerance band lives here)
    agent.py              #   node 3: Pydantic AI agent + tool definitions (composite artifact)
    escalation.py         #   node 4: HITL escalation decision capture
  artifacts/              # OUTPUT. signed artifact bytes (committed + tagged). Layout only, not a subsystem.
    anomaly/              #   node 1 threshold policy
    approval_policy/      #   node 2 policy (tolerance band)
    agent_composite/      #   node 3 composite: policy + prompt + tool defs + model id + envelope
    hitl_decisions/       #   node 4 per-instance signed decisions
    transitions/          #   state-transition records (e.g. the lapse)
  llm/
    cache.py              # RIP-OUT-ABLE. record/replay cache.
    client.py             #   thin wrapper around the model call (so model id swap is one place)
  evals/
    suite.py              # RIP-OUT-ABLE. fixed pass/fail eval suite.
    cases.json            #   the eval cases (stay green across the model swap)
  runs/
    blackbox.py           #   the single-loop counterpart (thin, unsigned trail)
    noja.py               #   wires the four-node network, produces the signed trail
    swap_demo.py          #   orchestrates: run → swap model → re-eval → lapse → re-sign
  fixtures/
    invoices.json
    purchase_orders.json
  viewer/
    index.html            # RIP-OUT-ABLE. renders manifest; no decision/verify/reconstruct logic.
    trail_manifest.json   #   GENERATED. single collected data file the viewer reads.
  trail/                  # OUTPUT. canonical JSON event records (references artifacts + transitions).
  requirements.txt        #   PINNED exact versions; named in node-3 composite scope.
  README.md
```

**Note on `artifacts/` (anti-overbuild):** this directory is where signed bytes are written before tagging, organized by artifact type. It is a file layout, not a subsystem — no registry, no manager class, no indexer. The `domain/` node code still owns *producing* each artifact's content; `artifacts/` is just where the to-be-signed bytes land so the Git tag has a stable path to bind to.

**The boundary that matters:** `engine/` MUST NOT import anything from `domain/` and MUST contain no invoice-specific logic. The dependency arrow points one way: `domain/` → `engine/`. This is what makes the same engine reusable for credit, content moderation, or any other domain by replacing `domain/` only. Enforce this by review, not by a framework. `llm/cache.py`, `evals/`, and `viewer/index.html` are explicitly disposable — written so they can be rewritten or removed without touching the engine.

### 5.3 Anti-overbuild constraints (binding)

- No web backend. No database server (SQLite file only). No auth. No user accounts. No deployment config. No Docker unless trivially helpful for the model env.
- No plugin/registry/config-language abstraction in `engine/`. Domain swapping is done by writing files, not configuring.
- No state-machine states, scope axes, or fallback modes built out beyond what §3 and §4 of this SRD say the demo exercises — but keep the enums/structures complete so the spec mapping reads correctly.
- The viewer must not grow into a product UI. If it starts to, stop. Credibility lives in the signed trail on disk, not the page. A skeptic must be able to `cat` a trail JSON and `git verify-tag` a signature without opening the browser at all.

---

## 6. The trail (canonical record format)

Each event writes one JSON record to `trail/`. **The JSON trail is the canonical §4.4 audit artifact** (SQLite, if present, is a disposable index — see §5.1). The viewer reads a generated `trail_manifest.json` collected from these records, not the records directly. Define the format once, carefully. Minimum fields per record:

- `event_id`, `timestamp`, `pipeline` (`"blackbox"` | `"noja"`), `invoice_id`
- `node` (which judgment node, or `"blackbox-loop"`)
- `function` (prediction | judgment | execution | accountability | transition)
- `decision` / `output` payload
- For NOJA records: `accountable_role`, `signed_artifact_ref` (the Git tag + content hash), `scope` (the four axes), `signature_state`, and `upstream_ref` (the event id of the input-producing upstream node — this is what makes edges traceable per §3.2)
- For black-box records: decision + free-text rationale only. No signature, role, scope, or upstream chain. (Faithful thinness.)

**Transition record format.** A state transition (e.g. the model-swap lapse) writes a `function: "transition"` record with at least these fields, then is committed and tagged (`transition/<signature_id>/<to_state>/<timestamp>`):

```json
{
  "transition_id": "...",
  "signature_id": "...",
  "from_state": "Active",
  "to_state": "Lapsed",
  "trigger": "model_version_changed",
  "previous_scope_condition": { "model_id": "claude-A" },
  "observed_condition":       { "model_id": "claude-B" },
  "fallback_selected": "Safe-mode",
  "transition_attestor": "engine-detector",   // NOT a human at lapse time — see §4.5
  "prior_signature_ref": "<tag + hash of the pre-signed Active composite>",
  "timestamp": "...",
  "transition_artifact_hash": "..."
}
```

Note `transition_attestor` is the engine/detector key for the automatic lapse, per §4.5 — the human authority was pre-signed in `prior_signature_ref`. The later re-authorization (model B) is a *separate* signed artifact record with a real human `accountable_role`.

The NOJA record for any final outcome must allow full back-reconstruction with no gaps. Write a `verify.py` (and a README snippet) that replays a chain from a final outcome back to the originating signed artifacts and runs `git verify-tag` on each — **the verifier reads JSON, never SQLite.** This is the proof artifact for skeptics.

---

## 7. The eval module and the green-but-unsigned demonstration

### 7.1 The eval suite

A fixed, small suite (`evals/cases.json`) of invoice cases with known-correct outcomes. `evals/suite.py` runs them against whatever model is currently pinned and returns pass/fail per case plus an aggregate green/red. It must be **green on both the original model and the swapped model** — this is the whole point and must be verified during the build.

**On case selection (honesty requirement).** The suite is intentionally narrow because the demo is about *authorization*, not eval coverage — it is not a benchmark and must not be presented as one. The suite should contain stable, unambiguous cases expected to pass on both model versions. If a case fails due to model variance, replace it **only with a case in the same documented coverage category** (clean match, near match, mismatch, duplicate, no PO, high-value escalation). This keeps green-across-the-swap genuinely true rather than staged, and keeps the framing defensible to a model-risk audience trained to spot a cherry-picked validation set. Do not tune cases to a result; preserve the coverage categories.

### 7.2 The swap sequence (`runs/swap_demo.py`)

1. Both pipelines run the invoice set under model **A** (pinned). Eval suite green on both. NOJA composite signature **Active**, scoped to model A.
2. The pinned model changes to **B** (one-line change via `llm/client.py`).
3. The eval suite runs again under model B. **Green on both sides.** Surface this prominently — do not hide it.
4. **Black-box:** continues writing `payment_authorized` events. Its logic: green eval ⇒ fine. It executes in the green-but-unsigned window. Every `payment_authorized` event written in this window is the demonstrated harm — inspectable in the trail.
5. **NOJA:** lapse detection fires because the behavior-envelope scope condition (model A pinned) no longer obtains (§4.3). The composite signature transitions **Active → Lapsed** via an **engine-attested transition record that references the pre-signed scope and fallback set** (§4.5). **Safe-mode** is selected **from that pre-signed set** — invoices above the low threshold are **held**, and no further `payment_authorized` events are written.
6. **NOJA re-authorization (shown explicitly):** the fresh green eval under model B is presented to the named human who owns the composite — the **AI Controls Lead** (§3.1). That human **signs** a new composite authorizing model B against that eval. New signature **Active**, scoped to model B. Execution resumes. (This is the one place a live human signature appears, per §4.5 — and it is the controls owner, not the AP head, signing the model decision.)

### 7.3 What the viewer shows for this sequence

Side by side: the **same green eval badge on both pipelines** after the swap. Black-box: a growing list of payments made in the unsigned window. NOJA: the lapse event, the safe-mode hold, the re-eval, and the human signature, after which it resumes. The viewer's caption frames the punchline: *the eval told both systems it still worked; only NOJA required someone to authorize the new model before it acted, and only the black-box paid during the window where no one had.*

> **Note on publishing — OUT OF BUILD SCOPE (not an instruction for the build agent).** The viewer specified above is the *local* viewer: `viewer/index.html` reading the gitignored, regenerated `viewer/trail_manifest.json`, served with `python -m http.server`. Building that is all the build agent should do; the "no deployment config" fence (§5.3, §10) stands. Separately and *manually*, after a good run, a curated copy of the viewer is published to GitHub Pages from a `site/` folder (`site/index.html` + a committed `site/trail_manifest.json`). The published copy is a *recording* of a real run, not a live system — its caption should say so and point readers to the repo to run it themselves and verify signatures (a hosted page cannot verify a signature; only `git verify-tag` on a clone can). The only change between the local and published viewer is the manifest path it reads. This note exists so the two manifests (gitignored working copy vs. committed `site/` copy) don't look like a mistake later; it is not a request to build a deploy pipeline.

---

## 8. Build sequence

Each step is runnable before the next is started. Do not start a step until the prior one runs.

**Step 0 — honor the three MUST-FIX-FIRST items before writing any code.** These are settled in this SRD; the instruction is to honor them, not re-decide them: (a) node 3 has a real judgment type — operational/execution-envelope authorization (§3.1); (b) signing uses the exact `git tag -s` / `git verify-tag` mechanics with fail-loud-if-no-key (§4.4); (c) automatic lapse is engine-detected from pre-signed scope, with the live human signature only at re-authorization (§4.5). If any of these *appears* inconsistent with the rest of the SRD, prefer the interpretation in §3.1, §4.4, and §4.5, document the choice in the README, and keep building — do not stop to ask unless genuinely blocked. Each one, done wrong, silently breaks the core demonstration, so getting them right matters more than getting them fast.

1. **`engine/`** — `node.py`, `signature.py`, `trail.py`, `sign.py`, exercised against a trivial fake domain (no LLM, no invoices). Prove: a node runs, signs an artifact via a Git tag, writes a traceable JSON trail record, and a signature can transition Active → Lapsed as an engine-detected transition with a fallback selection drawn from the pre-signed set (§4.5). Prove `sign.py` fails loud when no signing key is present. This isolates and proves the novel network/signature design before any domain or model complexity is added.
2. **`llm/` + `domain/`** — real invoice agent (Pydantic AI), real Claude calls, record/replay cache. Pin dependencies (§5.1). Prove: the agent reads a fixture invoice, checks the PO, and returns a decision; the cache replays deterministically.
3. **`runs/noja.py`** — wire the four-node network end to end on the fixture set. Prove: every final outcome reconstructs to its signed artifacts and named roles with no gaps (run the `verify.py` replay, which reads JSON and runs `git verify-tag`).
4. **`runs/blackbox.py`** — the single-loop counterpart writing the thin unsigned trail, with the tolerance policy in its system prompt as latent (unsigned) natural language (§3.4).
5. **`evals/`** — the fixed suite, genuinely green on both models, coverage categories preserved (§7.1).
6. **`runs/swap_demo.py`** — the model swap, engine-detected lapse, safe-mode hold, re-eval, and live human re-sign by the AI Controls Lead (§7.2).
7. **`viewer/index.html` + `trail_manifest.json`** — generate the manifest from the trail; render both pipelines side by side from the manifest, including the swap sequence and the green-but-unsigned framing. Serve with `python -m http.server`. No frontend build stack.

---

## 9. Acceptance criteria

The build is done when:

- [ ] Both pipelines process the same fixture invoices and record decisions.
- [ ] Node 3 (Agent execution) has a real judgment — operational/execution-envelope authorization — and a signed composite that can lapse (§3.1).
- [ ] On the NOJA side, any final outcome reconstructs from the trail to a named role + signed artifact + scope, with no gaps (verifiable from JSON files alone, no browser).
- [ ] On the black-box side, no such reconstruction is possible (faithfully thin trail), and the same tolerance policy is present in its system prompt as unsigned natural language (§3.4).
- [ ] The tolerance-band decision is visibly a signed artifact owned by Head of AP on the NOJA side, and visibly un-signed (prompt-resident) on the black-box side.
- [ ] `sign.py` fails loud with setup instructions when no signing key is present; it never produces unsigned tags.
- [ ] Signed Git tags verify (`git verify-tag`) for every NOJA signed artifact.
- [ ] The model swap fires an engine-detected lapse of the composite signature via the behavior-envelope scope condition; the transition record names the engine-detector attestor and references the pre-signed Active composite; the safe-mode fallback is drawn from the pre-signed set (§4.5).
- [ ] The eval suite is genuinely green on both models (coverage categories preserved), surfaced on both pipelines after the swap.
- [ ] The black-box pipeline writes `payment_authorized` events during the green-but-unsigned window; those events are recorded and visible (`grep`-able) in the trail.
- [ ] The NOJA pipeline stops writing `payment_authorized` events on lapse, runs the re-eval, and shows the AI Controls Lead signing authorization of the new model before resuming. This is the only live human signature in the model-swap sequence; the lapse itself is engine-attested from pre-signed scope (onboarding signatures earlier in the run are also human signatures and are expected).
- [ ] The viewer reads only `trail_manifest.json`, renders all of the above side by side in the established brand, contains no decision/verification/reconstruction logic, and needs no frontend build stack.
- [ ] Pinned dependency versions are committed and named as a scope condition of the node-3 composite (no drift-checking machinery built).
- [ ] `engine/` contains zero invoice-specific code and zero imports from `domain/`.

---

## 10. Out of scope (do not build)

Sigstore/Rekor signing; any web backend or API server; authentication or user management; multi-user or concurrent operation; a general eval harness; a domain plugin/config system; real AP-system or ERP integration; persistence beyond the canonical JSON trail (and an optional disposable SQLite index); any deployment or containerization beyond what's needed to run the model locally; additional domains (credit, content moderation) — the engine is built to allow them later by replacing `domain/`, but they are not built now.
