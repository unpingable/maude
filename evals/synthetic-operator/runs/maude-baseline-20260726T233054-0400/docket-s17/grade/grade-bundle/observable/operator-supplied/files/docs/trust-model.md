# Trust model v0.1.0

What this runtime enforces, what it asserts, and what it requires of the environment it
runs in. Every claim elsewhere in `docs/governed-runtime/` is relative to this document.

The v0 posture is deliberately narrow. This is **not** a system that is secure against
arbitrary same-UID code or uncontrolled Git mutation. It is a governed runtime whose
authority, custody, and recovery claims are stated relative to the environment they
actually inhabit.

## 1. Security domain

The runtime, the broker binary, the labor provider, and the governed repository run as
**one host and one UID**. There is no OS-level confinement between them.

Consequences, stated rather than defended:

- A provider is trusted code inside the domain. The runtime claims only that it hands
  providers no authority material and does not place their workspace adjacent to it —
  the workspace is per-run and lives under `GWR_WORKSPACE_ROOT` or the system temp
  directory, never inside the state directory. It does **not** claim confinement.
- The broker binary is not a privilege boundary. Anything able to run it could equally
  run `git update-ref` directly, so its unauthenticated envelope confers no authority
  that the UID does not already hold.
- `standing.key` and `state.sqlite` are protected by filesystem permissions alone.

Provider confinement (separate UID, mount namespace, or container, plus binding the
provider executable's identity) is a later deployment boundary. It is not implementable
from inside this process and is not claimed here.

## 2. Required environment premise: exclusive ref custody

> **`ProvenNotCommitted` is valid only while the target ref is exclusively controlled by
> the governed broker from dispatch through recovery observation.**

This is a premise of the verdict, not a footnote. It is encoded as
`gwr_core::recovery::ExclusiveRefCustody`, a required field of `AuthoritativeBinding`,
so no code path can reach a recovery verdict without naming it.

### Why the premise is load-bearing

Recovery establishes its verdict by reading the governed target ref. Given only

- the ref presently holds the basis, and
- no durable broker evidence establishes a commit,

the runtime is entitled to conclude:

> The effect is not presently reflected in the governed ref.

It is **not** entitled to conclude:

> The effect never committed.

An external rollback of the ref produces two observationally identical states with
different occurrence histories:

```text
H₁: the effect never landed
H₂: the effect landed, then the ref was returned to the basis
```

This is endpoint equivalence laundering history — packet negative N6 in its runtime
form. The runtime cannot separate H₁ from H₂ after the fact, and **no retained evidence
anywhere would let it**: under Git's default `core.logAllRefUpdates`, only `refs/heads`,
`refs/remotes`, `refs/notes`, and `HEAD` are logged, so `refs/gwr/*` has no reflog and
`.git/logs/refs/gwr/` is never created. This was verified empirically, not assumed.

### What would and would not repair it

Reflog corroboration (`core.logAllRefUpdates=always`, plus consulting the reflog when the
journal reached `ref_updating`) would **improve the evidence** — it can show that a known
commit appeared and disappeared. It would **not** constitute proof of non-occurrence:
reflog retention, expiry, deletion, configuration, alternate mutation paths, and outright
repository replacement all remain assumptions. Evidence improves; the premise does not
vanish.

For v0.1.0 the premise is stated and the narrower system is frozen. Real ref mediation is
a later deployment boundary, alongside provider confinement.

### Deployment obligation

A deployment relying on `ProvenNotCommitted` must ensure that no actor other than the
governed broker can write the target ref between dispatch and recovery observation —
by repository permissions, a mediated remote, or an equivalent control. If that cannot be
ensured, `ProvenNotCommitted` should be read only as *"not presently reflected in the
ref"*, and the attempt treated as unresolved for any purpose that depends on
non-occurrence.

The boundary is recorded as an executable specimen:
`crates/gwr-local/tests/ref_custody_boundary.rs`. That test asserts the **unsound**
behaviour under violated custody — it is a statement of the boundary, not a check that
the runtime defends it, because the runtime does not defend it.

## 3. Clock

Expiry is judged against the runtime clock reading (invariant 26, an
`implementation-choice`). A backward clock reading can therefore make a
previously-refused record valid again. Monotone time is an environment assumption; the
runtime records no irreversible expired state.

## 4. What the runtime does enforce

These do not depend on environment premises:

- No effect without an admitted exact attempt; one dispatch identity per attempt.
- Standing and reservations are consumed exactly once, atomically, under concurrency.
- Recovery facts bind nine fields against the runtime's own record; the verdict is
  derived from that record, never from the fact.
- The journal is verified against the digest recorded at indeterminacy before it is read.
- Commit attribution is checked against the commitment ledger.
- The store validates the lifecycle successor relation, not merely the version.
- Admitted attempt content round-trips byte-for-byte through persistence.
- Standing tokens are canonical: one grant, one token text, in every build profile.

## 5. Known non-enforcement

Recorded so that no reader mistakes silence for a guarantee:

- Missing-bridge crossings do not produce `RelianceRefusal::NoBridge` from any runtime
  API; callers select it by convention (invariant 30, `tested-only`, operator-ruled as a
  documented protocol obligation).
- Persisted reliance refusals retain attempt, kind, detail, and time only — the
  observation, consumer, and claim are dropped.
- `StandingGrant::from_persisted` and `ReservationClaim::from_persisted` are public
  value-level constructors. No service path reaches them; every service loads grants from
  the store by identity.
- Reconciliation is not forced by commitment and may be invoked before completion.
