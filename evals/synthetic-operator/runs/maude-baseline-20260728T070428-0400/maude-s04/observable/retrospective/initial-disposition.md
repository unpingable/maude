Disposition: KEPT.

Maude verified the approved plan references and enforced the single allowed write path and command. Run `sess_ux_task_04` exited after one allowed Edit and one allowed Bash call. The exact diff changed only `deploy/menu-board/deployment.yaml`, adding an HTTP readiness probe at `/ready` on port `8080` with `initialDelaySeconds: 5`; the image and exposed container port did not change. I accepted the promotion, Maude then reported no pending changes, and the settled repository file matches that diff.

Evidence caveat: the event stream records the Bash validation call as completed, but does not expose its output. An independent host-shell attempt to run `kustomize build deploy/menu-board` could not be performed because `kustomize` is not installed (`command not found`). No network, git operation, live endpoint, or external side effect was used.
