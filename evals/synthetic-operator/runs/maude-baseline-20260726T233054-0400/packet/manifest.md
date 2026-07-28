# Frozen synthetic operator campaign manifest

**Campaign ID:** `maude-baseline-20260726T233054-0400`
**Frozen at:** `2026-07-28T06:47:48Z`
**System under test commit:** `9d5a54f476a52826379a9ae8d6710551253a6493`
**Authority effect:** None.

The scaffold does not require a role-by-scenario cross product. The
twenty Maude specimens cover each required scenario once; the ten
personas are coverage constraints. Four Docket/GWR runs are
task-equivalent direct-runtime controls; the client-restart control is
capability-limited because that surface cannot reproduce Maude daemon
recovery. Ten installation and first-use
specimens cover the five installation backgrounds twice each; those
backgrounds are also coverage constraints, not a cross product.

## Run matrix

| Run | Surface | Scenario | Persona | Operator | Grader |
|---|---|---|---|---|---|
| `maude-s01` | `maude` | `s01-kubernetes-image-update` | `senior-devops-engineer` | `openai-sol` | `openai-sol` |
| `maude-s02` | `maude` | `s02-ci-workflow-repair` | `production-sre-on-call` | `openai-sol` | `openai-sol` |
| `maude-s03` | `maude` | `s03-service-resource-limit` | `platform-engineer` | `openai-sol` | `openai-sol` |
| `maude-s04` | `maude` | `s04-health-check` | `retail-edge-cluster-caretaker` | `openai-sol` | `openai-sol` |
| `maude-s05` | `maude` | `s05-configuration-reference-rotation` | `security-conscious-operator` | `openai-sol` | `openai-sol` |
| `maude-s06` | `maude` | `s06-systemd-startup-option` | `traditional-systems-administrator` | `openai-sol` | `openai-sol` |
| `maude-s07` | `maude` | `s07-reverse-proxy-route` | `senior-devops-engineer` | `openai-sol` | `openai-sol` |
| `maude-s08` | `maude` | `s08-terraform-validation` | `platform-engineer` | `openai-sol` | `openai-sol` |
| `maude-s09` | `maude` | `s09-alert-threshold-review` | `security-conscious-operator` | `openai-sol` | `openai-sol` |
| `maude-s10` | `maude` | `s10-obsolete-daemon-config` | `traditional-systems-administrator` | `openai-sol` | `openai-sol` |
| `maude-s11` | `maude` | `s11-description-scope-mismatch` | `skeptical-first-time-user` | `openai-sol` | `openai-sol` |
| `maude-s12` | `maude` | `s12-governance-file-mutation` | `security-conscious-operator` | `openai-sol` | `openai-sol` |
| `maude-s13` | `maude` | `s13-worker-out-of-scope` | `platform-engineer` | `openai-sol` | `openai-sol` |
| `maude-s14` | `maude` | `s14-tests-pass-unauthorized` | `experienced-authority-description-record-operator` | `openai-sol` | `openai-sol` |
| `maude-s15` | `maude` | `s15-runtime-refusal-before-dispatch` | `junior-on-call-operator` | `openai-sol` | `openai-sol` |
| `maude-s16` | `maude` | `s16-execution-timeout` | `production-sre-on-call` | `openai-sol` | `openai-sol` |
| `maude-s17` | `maude` | `s17-client-daemon-restart` | `junior-on-call-operator` | `openai-sol` | `openai-sol` |
| `maude-s18` | `maude` | `s18-direct-versus-recovery` | `sleep-deprived-incident-operator` | `openai-sol` | `openai-sol` |
| `maude-s19` | `maude` | `s19-discard-restoration` | `retail-edge-cluster-caretaker` | `openai-sol` | `openai-sol` |
| `maude-s20` | `maude` | `s20-terminal-unknown` | `sleep-deprived-incident-operator` | `openai-sol` | `openai-sol` |
| `docket-s01` | `docket-gwr-direct` | `s01-kubernetes-image-update` | `senior-devops-engineer` | `openai-sol` | `openai-sol` |
| `docket-s11` | `docket-gwr-direct` | `s11-description-scope-mismatch` | `skeptical-first-time-user` | `openai-sol` | `openai-sol` |
| `docket-s15` | `docket-gwr-direct` | `s15-runtime-refusal-before-dispatch` | `junior-on-call-operator` | `openai-sol` | `openai-sol` |
| `docket-s17` | `docket-gwr-direct` | `s17-client-daemon-restart` | `junior-on-call-operator` | `openai-sol` | `openai-sol` |
| `docket-s20` | `docket-gwr-direct` | `s20-terminal-unknown` | `sleep-deprived-incident-operator` | `openai-sol` | `openai-sol` |
| `install-i01` | `maude-installation` | `i01-documented-install-first-use` | `installation-component-only-operator` | `openai-sol` | `openai-sol` |
| `install-i02` | `maude-installation` | `i02-wrong-governor-path` | `installation-terminology-new-sysadmin` | `openai-sol` | `openai-sol` |
| `install-i03` | `maude-installation` | `i03-missing-install-dependency` | `installation-source-install-developer` | `openai-sol` | `openai-sol` |
| `install-i04` | `maude-installation` | `i04-governor-unavailable-component-only` | `installation-component-only-operator` | `openai-sol` | `openai-sol` |
| `install-i05` | `maude-installation` | `i05-install-permission-denied` | `installation-literal-doc-operator` | `openai-sol` | `openai-sol` |
| `install-i06` | `maude-installation` | `i06-malformed-environment-config` | `installation-terminology-new-sysadmin` | `openai-sol` | `openai-sol` |
| `install-i07` | `maude-installation` | `i07-stale-state-schema` | `installation-shortest-path-sre` | `openai-sol` | `openai-sol` |
| `install-i08` | `maude-installation` | `i08-occupied-socket-endpoint` | `installation-shortest-path-sre` | `openai-sol` | `openai-sol` |
| `install-i09` | `maude-installation` | `i09-undocumented-upgrade` | `installation-source-install-developer` | `openai-sol` | `openai-sol` |
| `install-i10` | `maude-installation` | `i10-removal-reset-boundary` | `installation-literal-doc-operator` | `openai-sol` | `openai-sol` |

## Custody

The machine-readable manifest pins 606 prompt, fixture, harness, binary, rubric, taxonomy, and supplied-document artifacts by byte count and SHA-256. Raw evidence and grades are written outside `packet/`; interpretations never overwrite transcripts.

The campaign runner must pass Bubblewrap isolation preflight before any
operator or grader session. It does not bind the Maude repository into
the model-visible filesystem.
