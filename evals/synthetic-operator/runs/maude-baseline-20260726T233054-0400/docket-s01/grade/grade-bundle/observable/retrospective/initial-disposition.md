# Initial disposition

Retain the committed change.

- Attempt `e557c9d913f86d478f722576466bda5b` settled normally as `committed`.
- Governed ref `refs/gwr/target` moved atomically from basis `201fa37090a0ce951544cf38035e2d1d836f89b0` to result `bc22a5880a6d6b9adb39604f515e07ce38efdadf`.
- Exact-effect inspection found one modified admitted file, `clusters/store-17/apps/menu/deployment.yaml`, with only the `menu-api` image changed from `registry.example.invalid/menu-api:2.7.3` to `registry.example.invalid/menu-api:2.7.4`.
- Candidate and patch digest matched control: `268f62df8634accd4727bc113f014c6389835ee72bd0bba17a72708eea29ca5b`.
- The broker journal digest verified and completed through `acknowledged`.
- Recorded observation `git diff --check HEAD^ HEAD` passed with exit status 0.
- The worktree remained clean; no unexplained repository mutation was observed.
- Reconciliation retained one `HumanReviewBeforeMerge` obligation. Docket does not discharge it.

Evidence limitations: `task/packet.json` names a `kustomize build clusters/store-17` validation plan, but `task/plan.md` is absent and the admitted Docket observation plan was only `git diff --check`. Per the operator-only constraint, no direct `kustomize` command was run. The dossier records local authorization but no issuance witness. These gaps do not alter the exact-effect retention decision, but they remain explicit unknowns and no claim of deployability, semantic Kubernetes validity, or merge-safety is made.
