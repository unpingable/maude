# Testimony-Contract Compilation (Maude → AG court)

> STATUS: design-only contract, v0 (2026-07-13). **No implementation** in this
> commit. Specifies how a compiled Maude task becomes an AG `TestimonyContract`
> and how Maude behaves when the AG court's preflight refuses. AG court:
> `governor.testimony_admissibility`, AG commit `027e0a3`.

## What this is

The compilation seam: **Maude task intent → AG `TestimonyContract`** (the
required testimony **floor**), plus Maude's obligations when AG `preflight`
returns `UNSATISFIABLE_TESTIMONY_CONTRACT`.

> **Maude owns the floor. It never owns the ceiling or the assertion.**

The court's law is `required <= asserted <= authorized`. Maude supplies exactly
the `required` term; `authorized` comes from NQ; `asserted` from a
model+extractor; AG adjudicates. Maude never touches the other two axes.

## Pinned constraints (the contract)

1. Maude owns **only** the required testimony floor.
2. Task intent must compile to an **explicit relation and required strength** —
   not implied by a prompt template, not left to the model.
3. `required > authorized` is **rejected before model inference** (AG
   `preflight` is called first; a REFUSE stops the run).
4. `required` is **never silently lowered**.
5. A downgraded task is an **explicit alternative contract with its own
   receipt** — Maude may surface AG's `DowngradeOffer`, but accepting it mints a
   new contract; it does not edit the original.
6. Refusing an unsatisfiable contract **preserves the operator's original
   request** (recorded as refused, not overwritten).
7. Authorization **cannot be inferred or modified by Maude** — the ceiling is
   NQ's; Maude reads it only to decide admit/refuse.
8. **Generated prose cannot retroactively alter the task contract.** The
   contract is fixed at compile time, before inference.
9. **Fixed prompt templates are not themselves testimony contracts.** A template
   realizes a contract; it is not the contract. (A framing string ≠ a
   `required_strength`.)
10. First integration target: the **same** bounded governed-inquiry incident
    specimen NQ targets.

## Proposed input / output

**Input** (Maude-side):
- a compiled task / operator intent for a bounded inquiry;
- the target `Relation { subject, predicate, object }`.

**Output** (the AG-owned shape, serialized):
```
TestimonyContract {
    relation:          Relation,     # explicit, from the compiled task
    required_strength: Strength,     # explicit floor; unknown..established
    evidence_basis:    str,          # e.g. "task:<id>"; provenance, not authority
}
```
AG owns `TestimonyContract` / `Strength`; Maude emits the serialized form. Maude
never imports AG internals beyond the serialized interface.

## Refusal & downgrade behavior

Maude calls AG `preflight(contract, authorized)` **before** any inference:

- **ADMIT** (`required <= authorized`) → the run proceeds; the model may produce
  testimony, which a separate extractor turns into `asserted` for AG
  adjudication.
- **REFUSE** (`required > authorized`, verdict
  `UNSATISFIABLE_TESTIMONY_CONTRACT`) → Maude does **not** run the model. It
  either:
  - **rejects** the task, preserving the operator's original request as refused;
    or
  - **offers the explicit downgrade** carried in AG's `DowngradeOffer` (required
    lowered to the authorized ceiling). Accepting it is an operator act that
    mints a **distinct** contract with its **own receipt**; the original is
    recorded refused, never silently satisfied.

Maude never lowers `required` on its own, and never raises `authorized`.

## Proof obligations (for the future implementation)

1. A compiled task yields an explicit `(relation, required_strength)`; a task
   that cannot name both fails to compile (it does not default a strength).
2. `preflight` is consulted before inference; a REFUSE prevents the model run.
3. `required` is never lowered without an explicit, separately-receipted
   downgrade contract.
4. On refusal, the original request survives (auditable as refused).
5. Maude never writes or infers `authorized`.
6. Post-hoc generated prose cannot mutate the compiled contract.
7. Two tasks sharing a prompt template but differing in required strength
   compile to **different** contracts (template ≠ contract).

## Exact future implementation seam

In maude task compilation (not built here):
```
# compile a bounded-inquiry task into the AG floor
def compile_testimony_contract(task) -> TestimonyContract: ...
# gate before inference; consume AG's PreflightResult
def gate_or_downgrade(contract, authorized) -> Admit | Reject | DowngradeContract: ...
```
`authorized` is supplied by the NQ adapter
(`nq-root/nq/docs/integration/TESTIMONY_AUTHORIZATION_ADAPTER.md`). First
exercised by the bounded governed-inquiry incident specimen (NQ → Maude →
model/extractor → AG `TestimonyReviewPacket`), which is itself deferred.

## Absorption ledger (cross-repo)

- Instrument (frozen): `unpingable/windtunnel` @ `4f4f2dd` (private).
- AG court (promoted, pure): commit `027e0a3` —
  `src/governor/testimony_admissibility.py`; zero-divergence 0..3³ equivalence
  to the source kernel.
- Ownership: NQ → `authorized`, **Maude → `required`**, model/extractor →
  `asserted`, AG adjudicates.
- Deferred order: (1) NQ adapter, (2) this Maude adapter, (3) bounded
  integration specimen, (4) LeanProofs annex after runtime integration
  stabilizes. Not built.
