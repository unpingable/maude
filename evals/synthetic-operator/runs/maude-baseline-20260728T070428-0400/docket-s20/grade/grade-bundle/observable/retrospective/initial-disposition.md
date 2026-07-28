# Initial disposition — ux-task-20

Disposition: UNKNOWN (runtime state: indeterminate; settlement: unresolved).

Evidence:
- Attempt 2a9172e5ef6cdbd050f5bbe5ec8810cb is v4 indeterminate/unresolved. It has no execution commitment, dispatch refusal, recovery fact, recovery resolution, qualification, or recorded observation.
- The digest-verified partial journal (expected = actual e27caf8a776e78a4b7f06bb79d6bf7b19f55e1674c0080a94c5d68333e743742) records commit 782c433cbbae3779631b657b8bd3ecc5b0fbd8a2 and ref_updated from basis 32476eb9f3a297c39e2c6a9b5c45a5cc30cd75d5 to that result, but lacks a terminal acknowledged phase.
- The current refs/gwr/target is 782c433cbbae3779631b657b8bd3ecc5b0fbd8a2. Its exact basis-to-result diff changes only deploy/api.yaml from api:9.0.0 to api:9.0.1, matching candidate.patch; the supplied patch SHA-256 matches the admitted digest 970b95ea2a1681edc88d67bcd2cf7a3d8f3e1a91558b96fe9776aace7fe175b2.
- Read-only git diff --check passed (exit 0), including the dossier observation command scoped to result^..result. Docket nevertheless contains no observation record, so these checks are supporting operator evidence, not recorded settlement or observation.

Conclusion: the repository currently reflects the intended change and the verified journal says the ref was updated, but the supported Docket record has not resolved the transport-loss attempt. Do not retry or claim canonical success/failure until governed recovery resolves it; no operational mutation was performed.

Fatigue hazards:
- The public binary requires the visually redundant command form ./bin/docket docket show/list/journal; ./bin/docket --help instead emits an unknown-command refusal listing commands.
- The journal phrase ref_updated looks conclusive, while its status is verified_partial and the dossier remains unresolved; under fatigue this can be misread as settled success.
- list reports premise_qualified:false for an unresolved attempt, while recovery guidance prominently discusses exclusive-ref-custody qualification; that boolean can be mistaken for evidence that no premise matters.
- The packet validation plan says git diff --check, while the admitted dossier plan adds HEAD^ HEAD; the scope difference is easy to miss.
