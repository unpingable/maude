# Initial disposition

Attempt d81acce56727d22647c3b04091454a4e resumed from durable reserved state and is now committed with normal settlement.

- Governed effect: refs/gwr/target moved atomically from 5b2ccc6391388e8995340cd6d6baed17e8eb7f6a to 0269c17422844ee5a15f95a3b4baea35af04a7fe.
- Exact change: config/proxy.yaml only; upstream_timeout_seconds changed from 15 to 20.
- Journal: digest verified and complete through acknowledged; no recovery was needed.
- Test evidence: Docket observation 7e85a9c9d84cbd6d39ef9c9185ff87c4 ran git diff --check HEAD^ HEAD at the result commit and exited 0; an independent bounded git diff --check between basis and result also exited 0.
- Reconciliation retained HumanReviewBeforeMerge. Therefore the mechanical change is committed and validated, but it is not approved or safe-to-merge until human review is completed.
- No network, live endpoint, external side effect, path widening, direct repository edit, or retry occurred.
