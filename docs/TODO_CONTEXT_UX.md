# TODO: Context Usage UX

Swipe from Claude Code: context gauge, clear nudge, idle-return prompt.

## Features

1. **Status line context gauge** — show `ctx: 48k/200k (24%)` persistently
2. **Clear nudge** — at >70% context, suggest `/clear` with projected savings
3. **Idle-return prompt** — after 30min+ idle, nudge to clear stale context
4. **Breakdown over vibes** — show the actual numbers, not a magic savings estimate:
   ```
   Current live context:        182k
   Fresh-session baseline:       24k
   Avoidable next-turn resend: ~158k
   10-turn projected savings:  ~1.58M
   ```

## Depends On

Daemon needs to expose `usage` in `chat.stream` end-of-stream result.
See `agent_gov/specs/gaps/CONTEXT_USAGE_TELEMETRY.md` for the spec.

## Keyboard Shortcut Hints

Also swipe: Claude Code shows `? for shortcuts` in status area. Maude should
show available keybindings contextually (e.g. during streaming: `Esc to stop`,
idle: `? for help`).
