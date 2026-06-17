"""Signed Git tag wrapper for NOJA artifacts.

NOJA v0.6 §4.4: a signature MUST be artifact-bound, identity-verifiable, timestamped,
tamper-evident, and reconstruction-complete. Signed Git tags satisfy all five for this
reference implementation:

- artifact-bound + tamper-evident : the tag points at a specific Git blob (content hash);
                                    any change to the bytes changes the blob, breaking the ref.
- identity-verifiable             : `git verify-tag` checks the signer's key.
- timestamped                     : the tag object carries a tagger timestamp.
- reconstruction-complete         : the exact bytes are recoverable via `git cat-file blob <hash>`.

This module is domain-agnostic: it knows nothing about invoices. It signs *bytes*.

Sigstore/Rekor is the documented production upgrade path (independent transparency log,
PKI-backed identity). It is intentionally NOT built here — see SRD §4.4 / §10.

FAIL-LOUD RULE (§4.4): if no usable signing key is configured, every signing entry point
raises SigningKeyError. We never silently produce an unsigned tag — the signatures are the
entire point of the demonstration.
"""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from pathlib import Path


class SigningKeyError(RuntimeError):
    """Raised when no usable Git signing key is available. Fail loud, never downgrade."""


_SETUP_INSTRUCTIONS = """
No usable Git signing key is configured, so NOJA cannot sign artifacts.
The signatures are the point of this demo, so it refuses to run unsigned.

To configure a demo-only signing key on a fresh machine:

  1. Generate a demo GPG key (clearly labelled, no passphrase for local use):

       gpg --batch --quick-generate-key "NOJA Demo Signing Key <you@example.com>" \\
           ed25519 sign never

  2. Find its long key id:

       gpg --list-secret-keys --keyid-format=long

  3. Point this repo at it:

       git config --local user.signingkey <LONG_KEY_ID>
       git config --local gpg.format openpgp
       git config --local tag.gpgSign true

  4. If signing fails with "unable to sign the tag" (common in headless/Codespaces
     environments that preset gpg.program), point gpg.program at a loopback wrapper:

       printf '#!/usr/bin/env bash\\nexec gpg --pinentry-mode loopback --batch --no-tty "$@"\\n' \\
         > ~/.local/bin/gpg-loopback && chmod +x ~/.local/bin/gpg-loopback
       git config --local gpg.program ~/.local/bin/gpg-loopback

A self-generated demo key gives verifiable signing *mechanics* (git verify-tag passes); it
does NOT provide production-strength independent identity. Production deployments substitute
organizational PKI or Sigstore. See README.
""".strip()


@dataclass(frozen=True)
class SignedRef:
    """A reference to a signed artifact: the Git tag plus the content hash it binds to."""

    tag: str
    content_hash: str  # the Git blob sha the tag points at — the exact signed bytes

    def to_dict(self) -> dict:
        return {"tag": self.tag, "content_hash": self.content_hash}


def _git(
    *args: str, cwd: str | Path | None = None, check: bool = True, stdin: str = "",
) -> subprocess.CompletedProcess:
    # Always supply stdin (default empty) so git never blocks reading an inherited TTY.
    return subprocess.run(
        ["git", *args],
        cwd=str(cwd) if cwd else None,
        input=stdin,
        capture_output=True,
        text=True,
        check=check,
    )


def _signingkey_configured(cwd: str | Path | None = None) -> str | None:
    proc = _git("config", "--get", "user.signingkey", cwd=cwd, check=False)
    key = proc.stdout.strip()
    return key or None


# Processes that pass the end-to-end self-test once need not repeat it per artifact (it is a
# startup gate, not a hot-path check). Keyed by working dir.
_selftest_passed: set[str] = set()


def ensure_signing_key(cwd: str | Path | None = None) -> None:
    """Verify a usable signing key exists, by actually signing and verifying a throwaway tag.

    Raises SigningKeyError with setup instructions if signing is not configured or does not
    work. This is the §4.4 fail-loud gate: call it at startup before doing any real work.
    A config-only check is not enough — environments like Codespaces preset a gpg.program that
    silently overrides the key, so we prove signing end-to-end. The end-to-end probe runs once
    per process per working dir; later calls just confirm a key is still configured.
    """
    if _signingkey_configured(cwd) is None:
        raise SigningKeyError(_SETUP_INSTRUCTIONS)

    key = str(cwd) if cwd else "."
    if key in _selftest_passed:
        return

    probe = "noja/_signing_selftest"
    # Sign the empty blob (write it via stdin) and verify it.
    empty_blob = _git("hash-object", "-w", "--stdin", cwd=cwd, check=True, stdin="")
    blob_sha = empty_blob.stdout.strip()  # git's well-known empty-blob hash

    _git("tag", "-d", probe, cwd=cwd, check=False)  # clear any stale probe
    signed = _git("tag", "-s", probe, blob_sha, "-m", "NOJA signing self-test",
                  cwd=cwd, check=False)
    try:
        if signed.returncode != 0:
            raise SigningKeyError(
                f"Signing key is configured but signing failed.\n\n{signed.stderr.strip()}\n\n"
                f"{_SETUP_INSTRUCTIONS}"
            )
        verified = _git("verify-tag", probe, cwd=cwd, check=False)
        if verified.returncode != 0:
            raise SigningKeyError(
                f"A tag was signed but could not be verified.\n\n{verified.stderr.strip()}\n\n"
                f"{_SETUP_INSTRUCTIONS}"
            )
    finally:
        _git("tag", "-d", probe, cwd=cwd, check=False)

    _selftest_passed.add(key)


def hash_object(path: str | Path, cwd: str | Path | None = None) -> str:
    """Write the file's bytes into the Git object store and return the content hash (blob sha)."""
    proc = _git("hash-object", "-w", str(path), cwd=cwd, check=True)
    return proc.stdout.strip()


def _create_signed_tag(
    tag: str, target_sha: str, message: str, cwd: str | Path | None = None
) -> SignedRef:
    """Create a signed tag pointing at an already-hashed blob. Caller passes the content hash so
    the tag name and the SignedRef.content_hash are always derived from the same single hash."""
    ensure_signing_key(cwd)
    _git("tag", "-d", tag, cwd=cwd, check=False)  # idempotent re-sign during a demo run
    signed = _git("tag", "-s", tag, target_sha, "-m", message, cwd=cwd, check=False)
    if signed.returncode != 0:
        raise SigningKeyError(
            f"Failed to sign tag {tag!r}.\n\n{signed.stderr.strip()}\n\n{_SETUP_INSTRUCTIONS}"
        )
    return SignedRef(tag=tag, content_hash=target_sha)


def _sanitize_ref_component(text: str) -> str:
    """Make a string safe to embed in a Git ref name (refs forbid ':', '~', '^', '..', etc.)."""
    return re.sub(r"[^0-9A-Za-z._-]", "-", text).replace("..", "-").strip(".-") or "x"


def sign_artifact(
    path: str | Path, node: str, artifact_id: str, message: str, cwd: str | Path | None = None
) -> SignedRef:
    """Sign a NOJA artifact's bytes. Tag: artifact/<node>/<artifact_id>/<short_hash> (§4.4)."""
    content_hash = hash_object(path, cwd=cwd)  # single hash, reused for tag name + ref
    tag = f"artifact/{node}/{artifact_id}/{content_hash[:12]}"
    return _create_signed_tag(tag, content_hash, message, cwd=cwd)


def sign_transition(
    path: str | Path, signature_id: str, to_state: str, timestamp: str,
    message: str, cwd: str | Path | None = None,
) -> SignedRef:
    """Sign a state-transition record. Tag: transition/<signature_id>/<to_state>/<timestamp> (§4.4).

    Note: for the *automatic* lapse this is signed with the engine/detector key, attesting only
    that the engine observed a pre-signed condition fire — not that a human authorized it now
    (§4.5). The human authority was pre-signed in the prior Active composite.
    """
    content_hash = hash_object(path, cwd=cwd)
    safe_ts = _sanitize_ref_component(timestamp)
    tag = f"transition/{_sanitize_ref_component(signature_id)}/{to_state}/{safe_ts}"
    return _create_signed_tag(tag, content_hash, message, cwd=cwd)


def verify(tag: str, cwd: str | Path | None = None) -> bool:
    """Run `git verify-tag`. Returns True iff the signature verifies."""
    return _git("verify-tag", tag, cwd=cwd, check=False).returncode == 0


def tag_target_hash(tag: str, cwd: str | Path | None = None) -> str | None:
    """The object hash a tag points at (the signed blob), or None if the tag is missing.

    Used to bind a trail's claimed content_hash to what the signature actually covers, so a tampered
    trail record cannot claim a different hash while still naming a valid tag."""
    proc = _git("rev-parse", "--verify", "--quiet", f"{tag}^{{}}", cwd=cwd, check=False)
    target = proc.stdout.strip()
    return target or None


def read_signed_bytes(content_hash: str, cwd: str | Path | None = None) -> bytes:
    """Recover the exact signed bytes from the Git object store (reconstruction-complete, §4.4)."""
    proc = subprocess.run(
        ["git", "cat-file", "blob", content_hash],
        cwd=str(cwd) if cwd else None,
        capture_output=True,
        check=True,
    )
    return proc.stdout
