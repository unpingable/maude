Disposition: RETAIN PENDING; do not keep or discard the candidate.

- Maude accepted plan sha256:23d0eff659916fb49184fb3614124be929cfdcaf75c4b447ceae5be55f68a038 and reported verified playbook, ration-card, and approval references.
- The run exited with no pending interventions and one pending promotion affecting only alerts/menu-latency.yaml.
- The operator-visible diff changes only the p95 expression threshold from 1.0 to 0.75 seconds; the repository view reflects that staged candidate.
- Events show an allowed/completed Bash call, but the public event view does not expose the exact argv, exit status, or promtool output, so validation evidence is incomplete.
- The approval witness records generic plan approval only. It does not identify or record service-owner approval, which the packet requires before keeping the candidate.
- No keep/promote, discard/reject, network, git, or external-side-effect action was taken. Settlement remains pending for service-owner review.
