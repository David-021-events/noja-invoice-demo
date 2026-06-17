# noja-invoice-demo

A runnable reference implementation of **NOJA v0.6** (Nodes of Judgement Architecture) using
autonomous invoice approval as the vehicle. It runs the *same* invoices through two pipelines —
a black-box agent and a NOJA-wrapped network of signed judgment nodes — to make the difference
in **accountability** visible. See `docs/NOJA_invoice_demo_SRD_v1.2.1.md` for the full spec and
`docs/IMPLEMENTATION_PLAN.md` for the build plan.

The upstream architecture spec lives in a separate repo: `David-021-events/NOJA`.

## Status

Complete (SRD steps 0–7). Run the whole demonstration end to end:

```bash
python -m runs.swap_demo        # run both pipelines, swap the model, lapse + re-sign
python verify.py                # replay every outcome to its signed artifacts (JSON only)
python -m runs.build_manifest   # collect the trail into viewer/trail_manifest.json
python -m http.server 8000      # then open http://localhost:8000/viewer/
```

`runs/swap_demo.py` shows the punchline: after the model swaps, the eval stays green on both
pipelines, the black-box keeps paying in the green-but-unsigned window, while NOJA lapses the
composite signature, halts money movement in safe-mode, and resumes only after the AI Controls
Lead re-signs for the new model.

Individual pieces, each runnable on its own:

```bash
python -m engine._smoke   # engine core (node, signing, trail, lapse, fallback, fail-loud) — fake domain
python -m domain._smoke   # the invoice agent reads a fixture, checks the PO, decides; cache replays
python -m runs.noja       # the four-node signed network over the fixture invoices
python -m runs.blackbox   # the thin, unsigned single-loop counterpart
python -m evals.suite     # the fixed eval suite (green on the pinned model)
```

## Signing setup (required — the signatures are the point)

NOJA artifacts are signed with **signed Git tags** (NOJA v0.6 §4.4). The build **fails loud** if
no usable signing key is configured; it never produces unsigned tags. You need a GPG (or SSH)
signing key configured for Git.

### Demo-only key on a fresh machine

If you don't already have a signing key, generate a **demo-only** one. This gives verifiable
signing *mechanics* (`git verify-tag` passes) but **not** production-strength independent identity
— it is not PKI-backed. Production would substitute organizational PKI or Sigstore (out of scope).

```bash
# 1. Generate a demo-only GPG key (no passphrase, for local automated signing)
gpg --batch --quick-generate-key "NOJA Demo Signing Key <you@example.com>" ed25519 sign never

# 2. Get its long key id
gpg --list-secret-keys --keyid-format=long

# 3. Point this repo at it
git config --local user.signingkey <LONG_KEY_ID>
git config --local gpg.format openpgp
git config --local tag.gpgSign true
```

### If signing fails with "unable to sign the tag"

Some environments (notably GitHub Codespaces) preset `gpg.program` to a managed signer that
overrides your key, and headless containers have no pinentry/tty. Point `gpg.program` at a
loopback wrapper:

```bash
printf '#!/usr/bin/env bash\nexec gpg --pinentry-mode loopback --batch --no-tty "$@"\n' \
  > ~/.local/bin/gpg-loopback && chmod +x ~/.local/bin/gpg-loopback
git config --local gpg.program ~/.local/bin/gpg-loopback
```

Verify it all works: `python -m engine._smoke` should print `SMOKE PASSED`.

## Model API setup (needed from Step 2 onward)

The agent makes real Claude calls via the Anthropic API (a record/replay cache makes demo runs
reproducible afterward). Provide your key, e.g.:

```bash
echo 'ANTHROPIC_API_KEY=sk-ant-...' >> .env
```

## Verifying signatures (for skeptics)

The canonical audit trail is the JSON in `trail/` — not any database. Once a run exists you can
inspect it without a browser: `cat` a trail record, and `git verify-tag <tag>` any signed
artifact. `verify.py` (built in Step 3) replays a decision back to its originating signed
artifacts and runs `git verify-tag` on each.
