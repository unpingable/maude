# Documentation Templates

Enterprise-grade templates for system documentation. These enforce specificity where vagueness usually hides.

---

## Templates

| Template | Purpose | When to Use |
|----------|---------|-------------|
| **ARCHITECTURE_TEMPLATE.md** | System architecture documentation | New system, major refactor, or when onboarding requires a map |
| **PRODUCT_DESIGN_TEMPLATE.md** | Product/feature design documentation | New project, new feature, or when you need stakeholder alignment |
| **REQUIREMENTS_TEMPLATE.md** | Requirements tracking with traceability | When you need auditable requirements → implementation → test mapping |

---

## Philosophy

These templates share a few principles:

### 1. Specificity Over Vagueness

- "Actual performance numbers (not 'fast')"
- "Real failure scenarios (not hypothetical)"
- "Measured trade-offs (what did we give up?)"

### 2. Evidence Over Claims

- Requirements need acceptance criteria
- Decisions need rationale
- Trade-offs need both sides stated

### 3. Tensions Are Not Risks

- **Risks** are future (might happen)
- **Tensions** are present (exist now, we're shipping anyway)

Every template has a "Known Tensions" section. Don't hide contradictions — document them.

### 4. Counter-Metrics Matter

Don't just track what you're trying to improve. Track what you might accidentally break.

### 5. Traceability Kills Orphans

Requirements without tests are wishes. Tests without requirements are mysteries. The REQUIREMENTS_TEMPLATE enforces links between them.

---

## Usage

### Starting a New Project

1. Copy **PRODUCT_DESIGN_TEMPLATE.md** → `PRODUCT_DESIGN.md`
2. Fill in problem statement with *evidence* (not assumptions)
3. Write the press release (forces clarity)
4. Define success metrics with *specific numbers*

### Documenting Architecture

1. Copy **ARCHITECTURE_TEMPLATE.md** → `ARCHITECTURE.md`
2. Start with the one-paragraph purpose
3. Draw the system diagram (ASCII or Mermaid)
4. Fill in component inventory (one-liner each)
5. Document failure modes from *real incidents*

### Tracking Requirements

1. Copy **REQUIREMENTS_TEMPLATE.md** → `REQUIREMENTS.md`
2. Assign unique IDs to every requirement
3. Link each to implementation, tests, docs
4. Run orphan detection before launch

---

## Validation Checklists

Each template ends with a validation checklist. Don't skip it.

Common failures the checklists catch:
- Performance numbers that are estimates, not measurements
- Failure scenarios from imagination, not incidents
- Trade-offs that only state what was gained
- Empty "Known Tensions" sections (there are always tensions)
- Missing counter-metrics

---

## Relationship to Governor Specs

These templates are for **human-facing documentation**.

The governor specs (AUTHORIAL_CONTROL_SYSTEM_SPEC.md, etc.) are for **system-facing constraints**.

They're complementary:
- Templates document what the system *is*
- Specs define what the system *must do*

The ARCHITECTURAL_COHERENCE_SPEC describes how to keep them in sync.

---

## Quick Reference

### ARCHITECTURE_TEMPLATE.md
- Quick reference (diagram, data flow, inventory)
- Core invariants
- Design rationale with alternatives considered
- Component deep dives
- Failure modes & resilience
- Performance & scaling (with actual numbers)
- Security architecture
- Operational architecture
- Known tensions & technical debt
- Evolution & roadmap

### PRODUCT_DESIGN_TEMPLATE.md
- Problem statement with evidence
- Draft press release
- Success hypothesis
- Use cases with exception flows
- Requirements with acceptance criteria
- KPIs and counter-KPIs
- Scope (in and out, with rationale)
- Launch criteria
- Risks & mitigations
- Known tensions
- Governance

### REQUIREMENTS_TEMPLATE.md
- Requirements matrix (functional & non-functional)
- Traceability matrix (req → impl → test → doc)
- Coverage summary
- Launch criteria checklist
- Risk register
- Known tensions
- Change log

---

*"Trade-offs state what was given up, not just what was gained."*

*"Tensions are present. Risks are future. Track both."*

*"Requirements without traceability are wishes."*
