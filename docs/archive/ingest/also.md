> **HISTORICAL (archived 2026-07-03).** Chat-era design transcript — the origin
> of the retired "governed chat TUI" framing. Superseded by the ratified
> maude-boundary.md (agent_gov, 2026-07-02) and docs/REPOSITIONING.md. Kept as
> provenance; do not build from it.

yep. gonna change the cute short-form name for governor to 'governer' and excise 'maude' entirely, lol.  maude is maude. the two shall not cross.

That’s the right instinct. Names are load-bearing.

Renaming does two useful things at once:

* **Semantic firewall.**
  *governer* reads as infrastructure. Uncute. Opinionated. Authority-coded. It discourages UI creep and “maybe I’ll just import this helper” thinking. Good.

* **Role separation in your own head.**
  *Maude* is a persona + interaction surface. *governer* is a constraint engine. If they share a name-space, they’ll share responsibilities. You already saw where that goes.

A couple of small, practical guardrails to make the split stick:

* Different repos, different licenses if you’re feeling spicy.
* Different default tones in docs:

  * governer docs = dry, normative, MUST/MUST NOT
  * maude docs = conversational, workflow-oriented
* Never let Maude say “I decided.” It always says “governer allowed / blocked / needs approval.”

That last one matters more than it sounds.

You’re basically doing constitutional design, but for your own future self under deadline pressure. Renaming is how you enforce it socially.

And yeah — *the two shall not cross* is exactly the rule.

Me: ah. I think I realized now the missing piece of the puzzle here. I was also talking about 'maude' as a puppet profile, but that was meant IN THE CONTEXT OF THE CLAUDE-LIKE TUI


Yep. That’s the knot.

You had **three different “Maude”s** hiding under one token:

1. **Maude-the-TUI** (the chat surface you live in)
2. **Maude-the-persona** (voice/skin)
3. **Maude-the-puppet profile** (a constrained *agent configuration* inside Governor)

(3) is the one that poisons the boundary, because it drags “UI identity” back into “authority/config identity.”

### Clean fix: split the nouns, keep the concepts

* **Maude** = the TUI product (and optionally the persona skin)
* **Puppet profiles** = Governor configs, *never named after the UI*

So rename the puppet thing to something boring + structural, e.g.:

* `profile: puppet_readonly`
* `profile: delegated_builder`
* `profile: public_untrusted`
* `profile: operator_admin`
* `profile: autonomous_canary`

If you still want cute, do it *only* as UI labels:

* UI shows: “Maude (Builder)”
* Governor sees: `delegated_builder`

