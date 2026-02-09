# Product Design Documentation Template

## Usage

This template produces PRODUCT_DESIGN.md for a new project or feature. Fill in bracketed sections with specifics. Delete instructional comments before finalizing.

---

# [PROJECT NAME] Product Design

**Version**: [X.Y]  
**Last Updated**: [YYYY-MM-DD]  
**Owner**: [Product Owner]  
**Status**: [Draft | Review | Approved | Shipped]

---

## 1. Problem Statement

### 1.1 The Problem (One Paragraph)

[What's broken, for whom, and why it matters. No solutions here — just the pain. If you can't state the problem without mentioning your solution, you don't understand the problem yet.]

### 1.2 Evidence the Problem Exists

| Evidence Type | Source | Data |
|---------------|--------|------|
| Customer incident | [Ticket/Case ID] | [What happened, impact] |
| Support volume | [Metric source] | [X tickets/month about this] |
| Churn/NPS signal | [Survey/analysis] | [Specific feedback] |
| Competitor gap | [Analysis] | [What others do that we don't] |
| Internal friction | [Team/process] | [Time/cost wasted] |

[Minimum 3 evidence items. "We think customers want this" is not evidence.]

### 1.3 Who Has This Problem

| Persona | Context | Frequency | Severity |
|---------|---------|-----------|----------|
| [Role] | [When/where they hit this] | [How often] | [Impact when it happens] |

### 1.4 What Happens If We Don't Solve It

[Concrete consequences of inaction. Revenue, churn, operational cost, competitive position. Numbers where possible.]

---

## 2. Solution Overview

### 2.1 The Solution (One Paragraph)

[What we're building, in plain language. A customer should be able to understand this.]

### 2.2 Draft Press Release

[Write this as if announcing the shipped feature. Forces clarity about what customers actually get.]

---

**FOR IMMEDIATE RELEASE**

**[Company] Announces [Feature Name]: [One-Line Value Prop]**

[City, Date] — [Company] today announced [Feature Name], which [what it does] for [who]. 

[Customer problem paragraph: What was hard before.]

[Solution paragraph: How this makes it better.]

"[Quote from fictional customer about the benefit]," said [Fictional Customer Name], [Title] at [Company Type].

[Key capabilities: 2-3 bullet points of what's included]

[Feature Name] is available [when] for [who]. Learn more at [link].

---

### 2.3 Success Hypothesis

**We believe that** [solution]  
**For** [target users]  
**Will result in** [measurable outcome]  
**We'll know this is true when** [specific metric hits specific threshold]

### 2.4 What This Is NOT

[Explicit anti-goals. What are we intentionally not solving?]

| Not Solving | Why Not | Future Consideration |
|-------------|---------|---------------------|
| [Thing] | [Reason] | [Never / V2 / If X happens] |

---

## 3. Use Cases

### 3.1 Primary Use Case: [Name]

| Aspect | Detail |
|--------|--------|
| **Actor** | [Who performs this] |
| **Goal** | [What they're trying to accomplish] |
| **Preconditions** | [What must be true before this can happen] |
| **Trigger** | [What initiates this use case] |

**Main Flow:**

| Step | Actor | System |
|------|-------|--------|
| 1 | [What user does] | [What system does] |
| 2 | ... | ... |
| ... | ... | ... |

**Postconditions:**
- [What's true after successful completion]
- [State changes, notifications, etc.]

**Exception Flows:**

| Exception | Trigger | Handling |
|-----------|---------|----------|
| [Name] | [What goes wrong] | [What happens] |

### 3.2 Secondary Use Case: [Name]

[Repeat structure from 3.1]

### 3.3 Edge Case: [Name]

[Repeat structure — but these are the weird ones that matter]

---

## 4. Requirements

### 4.1 Functional Requirements

| ID | Requirement | Priority | Rationale | Acceptance Criteria |
|----|-------------|----------|-----------|---------------------|
| FR-001 | [System shall...] | P0/P1/P2 | [Why needed] | [How to verify] |
| FR-002 | ... | ... | ... | ... |

**Priority definitions:**
- **P0**: Launch blocker. Cannot ship without this.
- **P1**: Important. Ship is degraded without this.
- **P2**: Nice to have. Can ship without, plan for fast-follow.

### 4.2 Non-Functional Requirements

| ID | Category | Requirement | Target | Rationale |
|----|----------|-------------|--------|-----------|
| NFR-001 | Performance | [Requirement] | [Specific number] | [Why this target] |
| NFR-002 | Reliability | ... | ... | ... |
| NFR-003 | Security | ... | ... | ... |
| NFR-004 | Scalability | ... | ... | ... |
| NFR-005 | Usability | ... | ... | ... |

### 4.3 Constraints

| Constraint | Source | Impact |
|------------|--------|--------|
| [Constraint] | [Why it exists] | [How it shapes solution] |

Example:
| Must use existing auth system | Security policy | Cannot add new identity provider |

---

## 5. KPIs & Success Metrics

### 5.1 Business Outcomes

| Outcome | Metric | Baseline | Target | Timeline |
|---------|--------|----------|--------|----------|
| [What we want] | [How measured] | [Current state] | [Goal] | [When] |

Example:
| Reduce support burden | Tickets about X per month | 450 | <100 | 90 days post-launch |

### 5.2 Product Metrics

| Metric | Definition | Target | Measurement Method |
|--------|------------|--------|-------------------|
| Adoption | [What counts as adoption] | [X% of eligible users] | [How tracked] |
| Engagement | [What counts as engagement] | [Frequency/depth] | [How tracked] |
| Satisfaction | [CSAT/NPS for feature] | [Score] | [Survey method] |
| Task success | [Completion rate] | [%] | [How tracked] |

### 5.3 Operational Metrics

| Metric | Target | Alert Threshold |
|--------|--------|-----------------|
| Availability | [X%] | [Below Y%] |
| Latency p99 | [X ms] | [Above Y ms] |
| Error rate | [<X%] | [Above Y%] |

### 5.4 Counter-Metrics

[What we're watching to make sure we don't break something else]

| Counter-Metric | Acceptable Range | Action if Breached |
|----------------|------------------|-------------------|
| [Metric] | [Range] | [What we do] |

Example:
| Overall system latency | <5% increase | Rollback or optimize |

---

## 6. Scope

### 6.1 In Scope

| Item | Description |
|------|-------------|
| [Feature/capability] | [What's included] |

### 6.2 Out of Scope

| Item | Rationale | Future Consideration |
|------|-----------|---------------------|
| [Feature/capability] | [Why not now] | [When to reconsider] |

### 6.3 Scope Boundaries

[Where does this feature end and another begin? What's explicitly someone else's problem?]

---

## 7. Launch Criteria

### 7.1 Functional Completeness

| Criterion | Verification Method | Status |
|-----------|--------------------| -------|
| [ ] All P0 requirements implemented | [Test/demo] | ⬜ |
| [ ] All P0 requirements pass acceptance | [Test results] | ⬜ |
| [ ] Primary use case works end-to-end | [Demo] | ⬜ |
| [ ] Exception flows handled | [Test results] | ⬜ |

### 7.2 Quality Gates

| Gate | Criterion | Status |
|------|-----------|--------|
| [ ] Performance | Meets NFR targets under load | ⬜ |
| [ ] Security | Passes security review | ⬜ |
| [ ] Reliability | Chaos testing passed | ⬜ |
| [ ] Accessibility | Meets [standard] | ⬜ |

### 7.3 Operational Readiness

| Item | Criterion | Status |
|------|-----------|--------|
| [ ] Monitoring | Dashboards and alerts configured | ⬜ |
| [ ] Runbooks | Created and reviewed | ⬜ |
| [ ] Rollback | Tested and documented | ⬜ |
| [ ] On-call | Team briefed, rotation updated | ⬜ |

### 7.4 Go-to-Market Readiness

| Item | Criterion | Status |
|------|-----------|--------|
| [ ] Documentation | User docs published | ⬜ |
| [ ] Support | Team trained, FAQs ready | ⬜ |
| [ ] Communication | Announcement drafted | ⬜ |
| [ ] Feedback | Collection mechanism in place | ⬜ |

---

## 8. Risks & Mitigations

### 8.1 Risk Register

| ID | Risk | Likelihood | Impact | Mitigation | Owner | Status |
|----|------|------------|--------|------------|-------|--------|
| R-001 | [What could go wrong] | H/M/L | H/M/L | [How we prevent/reduce] | [Who] | [Open/Mitigated/Accepted] |

### 8.2 Dependencies

| Dependency | Owner | Risk if Delayed | Mitigation |
|------------|-------|-----------------|------------|
| [What we need] | [Who provides] | [Impact] | [Backup plan] |

### 8.3 Open Questions

| Question | Needed By | Owner | Status |
|----------|-----------|-------|--------|
| [What we don't know yet] | [When we need answer] | [Who's finding out] | [Open/Resolved] |

---

## 9. Known Tensions

[Contradictions we're shipping with. Not risks (might happen) — tensions (exist now).]

| Tension | Trade-off Made | Rationale | Revisit Trigger |
|---------|----------------|-----------|-----------------|
| [X vs Y] | [What we chose] | [Why] | [When to reconsider] |

Example:
| Speed vs completeness | Shipping without bulk import | 80% of users don't need it; can add in V1.1 | >20% of users request it |

---

## 10. Governance

### 10.1 Decision Rights

| Decision Type | Who Decides | Who's Consulted | Who's Informed |
|---------------|-------------|-----------------|----------------|
| Scope change | [Role] | [Roles] | [Roles] |
| Launch/no-launch | [Role] | [Roles] | [Roles] |
| Rollback | [Role] | [Roles] | [Roles] |

### 10.2 Review Cadence

| Review | Frequency | Attendees | Purpose |
|--------|-----------|-----------|---------|
| [Review type] | [How often] | [Who] | [What's covered] |

### 10.3 Escalation Path

| Situation | Escalate To | Timeline |
|-----------|-------------|----------|
| [Condition] | [Who] | [How fast] |

---

## 11. Appendices

### 11.1 Terminology

| Term | Definition |
|------|------------|
| [Term] | [What it means in this context] |

### 11.2 Related Documents

| Document | Purpose | Link |
|----------|---------|------|
| [Name] | [What it covers] | [URL] |

### 11.3 Revision History

| Version | Date | Author | Changes |
|---------|------|--------|---------|
| [X.Y] | [Date] | [Who] | [What changed] |

---

## Validation Checklist

Before marking this document Approved:

- [ ] Problem statement has evidence, not assumptions
- [ ] Solution can be explained without jargon
- [ ] Press release would make sense to a customer
- [ ] Success metrics have specific numbers and timelines
- [ ] Requirements have acceptance criteria
- [ ] Out of scope has rationale, not just list
- [ ] Launch criteria are verifiable, not vibes
- [ ] Risks have owners and mitigations
- [ ] Known tensions are acknowledged honestly
- [ ] Counter-metrics are defined (what we might break)

---

*"If you can't state the problem without mentioning your solution, you don't understand the problem yet."*

*"'We think customers want this' is not evidence."*

*"Tensions are what we're shipping with. Risks are what might happen. Don't confuse them."*
