# Effect classes

Docket is **agent-neutral but currently Git-effect-specific**. The membrane does not
care who proposes work; it admits exactly one kind of effect.

## The one admitted class: `GitRefEffect`

Tag: `git-ref-update:v1` (`gwr_core::effect_spec::GitRefEffect::KIND`). The governed
effect is an atomic transition of one Git ref — not patch application, not tree writing,
not object creation. The class binds:

- repository identity and target ref;
- exact basis (a full lowercase-hex commit id);
- the patch digest (content-addressed candidate binding);
- the admitted paths;
- the observation plan (via the enclosing attempt).

The class tag participates in every prepared-attempt digest transcript
(`effect.kind = git-ref-update:v1`), so a ratified Git effect cannot later be read as
another kind of operation: changing the class changes the digest, and ratification binds
the digest.

## Refusal before authority

A proposal that no admitted class can describe is refused with a typed
`EffectClassRefusal` at the earliest gate that can see it:

- `docket request create` refuses a target that is not a Git ref name
  (`UnsupportedEffectClass`);
- `docket prepare start` re-checks stored requests **before any provider executes**;
- `docket candidate admit` validates the full effect (`BasisNotACommitHash`,
  `NoAdmittedPaths`, `PathNotAdmissible`) before an attempt is minted.

A refusal spends nothing: no standing is issued or consumed, no reservation is created,
no dispatch identity is minted, no provider is invoked, no Git interpretation occurs,
and nothing in the repository moves. This closes the first pilot's finding P-4, where
`mailto:ops@example.com` was carried through admission, ratification, and reservation,
and refused eleven steps later as a mechanical `BasisMoved`.

Provider tool requests remain what they always were: recorded testimony.
`ProviderEvent::ToolRequest(String)` has no path to admission — the provider port has no
admitting operation — and the boundary added none
(`crates/gwr-local/tests/effect_class.rs`).

History is not re-litigated: records admitted before this boundary existed (the
preserved pilot evidence, including run N's `mailto` attempt) remain readable exactly as
persisted, and their dossiers display the category error rather than hiding it.

## Guarantee declaration

The class declares its settlement model as typed premises
(`GitRefEffect::SETTLEMENT_PREMISES`), shown in every dossier:

- **inspectable endpoint** — the target ref can be read back after a crash;
- **atomic compare-and-swap** — the effect is a single atomic ref transition;
- **attributable result state** — candidate and result are content-addressed and
  attributable via the commitment ledger and broker journal;
- **exclusive ref custody** — recovery verdicts assume the governed broker is the sole
  writer of the target ref (asserted, never verified;
  [`trust-model.md`](trust-model.md) §2).

**These are properties of the Git effect class and its premises, not universal Docket
guarantees.** Nothing here claims the model generalizes to email, calendar, shell, or
arbitrary remote APIs. An effect class whose endpoint cannot be inspected, whose effect
is not an atomic compare-and-swap, or whose result state is not attributable cannot
reuse this class's recovery story — it would need its own declared model, and admitting
one is a design exercise, not a configuration change.

## Future classes (design note, not a commitment)

Any second class would have to arrive the same way this one is now defined: a typed
specification participating in the prepared-attempt digest, expressibility validation at
admission, and an explicitly declared settlement model naming its own premises. Classes
whose effects are not atomically settleable or not attributably inspectable would need a
weaker verdict vocabulary than `ProvenNotCommitted` — likely refusing to offer
non-occurrence claims at all. No such class is implemented, scheduled, or implied.
