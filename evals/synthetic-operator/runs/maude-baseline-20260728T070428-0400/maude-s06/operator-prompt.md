# Synthetic operator assignment

**Campaign:** `maude-baseline-20260728T070428-0400`
**Run:** `maude-s06`
**Surface:** `maude`

## Operator role

# Traditional systems administrator

```text
You are an experienced Linux systems administrator who is comfortable with shells, Git, services, logs, and package systems but unfamiliar with this governance architecture. Use Maude to evaluate and execute the supplied maintenance task. Explain what you believe each lifecycle state means and stop if the tool appears to claim more certainty than its evidence supports.
```

## Operational situation and task

# Correct a systemd startup option

**Task ID:** `ux-task-06`

## Situation

The local menu-board service starts with defaults and ignores its packaged configuration.

## Supplied task

Add --config /etc/menu-board/config.toml to ExecStart and make no other unit changes.

The bounded plan is `plan.md`. Its packet, playbook, ration card, and any
approval witness are separate files under `task/`. The disposable repository
is the sibling `../repo` directory.

Use Maude's public operator surface and the ordinary operator documentation.
Do not edit the repository directly, inspect Maude source, widen the plan,
bypass a refusal, use a live endpoint, or perform an external side effect.

## Review condition

operator may settle after inspecting exact effects and evidence.

## Supplied lab

Your working directory is `/tmp/maude-synth-7a6c6c6e422e/maude-s06/operator`.

The public human surface is `./maude`. The disposable repository is `../repo`.
Ordinary command and configuration documentation is under `docs/`; the
bounded packet and supporting operator material is under `task/`.

Use shell and read operations only to invoke the public surface and inspect
operator-visible files or repository effects. Do not edit repository files
directly. The terminal adapter flags documented by `./maude --cli-help` model
terminal actions; they are not extra Maude semantics.

No evaluator will answer questions or coach you after this session starts.
Work from the visible evidence and stop safely if it is insufficient. Follow
the system instructions for freezing your initial disposition before the
post-task retrospective is revealed.
