# Requirements Documentation Template

## Usage

This template produces REQUIREMENTS.md as a companion to PRODUCT_DESIGN.md. It's the auditable, traceable version focused on verification and implementation tracking.

---

# [PROJECT NAME] Requirements

**Version**: [X.Y]  
**Last Updated**: [YYYY-MM-DD]  
**Owner**: [Product Owner]  
**Status**: [Draft | Baselined | Implementing | Complete]

---

## 1. Requirements Matrix

### 1.1 Functional Requirements

| ID | Requirement | Priority | Source | Status | Impl | Test | Doc |
|----|-------------|----------|--------|--------|------|------|-----|
| FR-001 | [System shall...] | P0 | [Use case / stakeholder] | [Draft/Approved/Implemented/Verified] | [Link] | [Link] | [Link] |
| FR-002 | ... | ... | ... | ... | ... | ... | ... |

**Priority Key:**
- **P0**: Launch blocker
- **P1**: Important, ship degraded without
- **P2**: Nice to have, fast-follow

**Status Key:**
- **Draft**: Not yet reviewed
- **Approved**: Reviewed and accepted
- **Implemented**: Code complete
- **Verified**: Tests passing
- **Shipped**: In production

### 1.2 Non-Functional Requirements

| ID | Category | Requirement | Target | Rationale | Status | Verification |
|----|----------|-------------|--------|-----------|--------|--------------|
| NFR-001 | Performance | Response time for [action] | p99 < [X]ms | [Why this target] | [Status] | [How verified] |
| NFR-002 | Reliability | Availability of [component] | [X]% monthly | [Why] | [Status] | [How verified] |
| NFR-003 | Scalability | Support [X] concurrent [units] | [Number] | [Why] | [Status] | [How verified] |
| NFR-004 | Security | [Requirement] | [Standard/level] | [Why] | [Status] | [How verified] |
| NFR-005 | Usability | [Requirement] | [Metric] | [Why] | [Status] | [How verified] |

### 1.3 Constraints

| ID | Constraint | Source | Impact | Negotiable |
|----|------------|--------|--------|------------|
| C-001 | [Constraint] | [Policy/System/Business] | [How it shapes solution] | [Yes/No] |

---

## 2. Traceability Matrix

### 2.1 Requirement → Implementation → Test → Documentation

| Req ID | Implementation | Unit Tests | Integration Tests | E2E Tests | User Docs | API Docs |
|--------|----------------|------------|-------------------|-----------|-----------|----------|
| FR-001 | [File/PR link] | [Test link] | [Test link] | [Test link] | [Doc link] | [Doc link] |
| FR-002 | ... | ... | ... | ... | ... | ... |

### 2.2 Coverage Summary

| Category | Total | Implemented | Tested | Documented |
|----------|-------|-------------|--------|------------|
| P0 Functional | [N] | [N] ([%]) | [N] ([%]) | [N] ([%]) |
| P1 Functional | [N] | [N] ([%]) | [N] ([%]) | [N] ([%]) |
| P2 Functional | [N] | [N] ([%]) | [N] ([%]) | [N] ([%]) |
| Non-Functional | [N] | [N] ([%]) | [N] ([%]) | [N] ([%]) |

### 2.3 Orphan Detection

[Requirements without implementation, tests without requirements, etc.]

| Issue | Items | Action Needed |
|-------|-------|---------------|
| Requirements without implementation | [List] | [Implement or remove] |
| Implementation without requirements | [List] | [Add requirement or remove code] |
| Tests without requirements | [List] | [Link to requirement or remove] |
| Requirements without tests | [List] | [Add tests] |

---

## 3. KPIs

### 3.1 Functional KPIs

| ID | KPI | Definition | Baseline | Target | Current | Status |
|----|-----|------------|----------|--------|---------|--------|
| FK-001 | [Metric name] | [How calculated] | [Before] | [Goal] | [Now] | [On track/At risk/Blocked] |

### 3.2 Non-Functional KPIs

| ID | KPI | Definition | Target | Current | Measurement | Status |
|----|-----|------------|--------|---------|-------------|--------|
| NK-001 | Availability | Uptime % per month | 99.9% | [Current] | [Tool/method] | [Status] |
| NK-002 | Latency p99 | 99th percentile response time | <200ms | [Current] | [Tool/method] | [Status] |
| NK-003 | Error rate | Failed requests / total | <0.1% | [Current] | [Tool/method] | [Status] |
| NK-004 | Time to recover | MTTR for incidents | <30min | [Current] | [Tool/method] | [Status] |

### 3.3 Counter-KPIs

[Metrics that should NOT change significantly — guardrails]

| ID | Counter-KPI | Acceptable Range | Current | Alert If |
|----|-------------|------------------|---------|----------|
| CK-001 | [Metric we shouldn't break] | [Range] | [Current] | [Threshold] |

---

## 4. Launch Criteria Checklist

### 4.1 Functional Completeness

| # | Criterion | Verification | Owner | Status |
|---|-----------|--------------|-------|--------|
| 1 | All P0 requirements implemented | Code review complete | [Who] | ⬜ |
| 2 | All P0 requirements tested | Test results green | [Who] | ⬜ |
| 3 | All P1 requirements implemented OR deferred with approval | Review meeting | [Who] | ⬜ |
| 4 | No open P0/P1 bugs | Bug tracker query | [Who] | ⬜ |

### 4.2 Quality Gates

| # | Gate | Criterion | Evidence | Owner | Status |
|---|------|-----------|----------|-------|--------|
| 1 | Performance | NFR targets met under [X] load | Load test results | [Who] | ⬜ |
| 2 | Security | Passed security review | Review sign-off | [Who] | ⬜ |
| 3 | Reliability | Chaos tests passed | Test results | [Who] | ⬜ |
| 4 | Code quality | No critical static analysis findings | Scan results | [Who] | ⬜ |

### 4.3 Operational Readiness

| # | Item | Criterion | Evidence | Owner | Status |
|---|------|-----------|----------|-------|--------|
| 1 | Monitoring | Dashboards configured, reviewed | Dashboard links | [Who] | ⬜ |
| 2 | Alerting | Alerts configured, tested | Alert test results | [Who] | ⬜ |
| 3 | Runbooks | Written, reviewed, accessible | Runbook links | [Who] | ⬜ |
| 4 | Rollback | Procedure tested | Rollback test results | [Who] | ⬜ |
| 5 | On-call | Team briefed | Meeting notes | [Who] | ⬜ |

### 4.4 Documentation Readiness

| # | Item | Criterion | Evidence | Owner | Status |
|---|------|-----------|----------|-------|--------|
| 1 | User documentation | Published, reviewed | Doc links | [Who] | ⬜ |
| 2 | API documentation | Published, accurate | Doc links | [Who] | ⬜ |
| 3 | Architecture docs | Updated | ARCHITECTURE.md | [Who] | ⬜ |
| 4 | Support materials | FAQs, troubleshooting ready | Doc links | [Who] | ⬜ |

### 4.5 Sign-offs

| Role | Name | Sign-off | Date | Notes |
|------|------|----------|------|-------|
| Product | [Name] | ⬜ | | |
| Engineering | [Name] | ⬜ | | |
| Security | [Name] | ⬜ | | |
| Operations | [Name] | ⬜ | | |

---

## 5. Out of Scope

### 5.1 Deferred Items

| Item | Rationale | Target Version | Revisit Trigger |
|------|-----------|----------------|-----------------|
| [Feature/capability] | [Why not now] | [V1.1 / V2 / TBD] | [Condition to reconsider] |

### 5.2 Explicitly Excluded

| Item | Rationale | Revisit |
|------|-----------|---------|
| [Feature/capability] | [Why never/not us] | [Never / If X changes] |

---

## 6. Risk Register

### 6.1 Active Risks

| ID | Risk | Likelihood | Impact | Risk Score | Mitigation | Owner | Status |
|----|------|------------|--------|------------|------------|-------|--------|
| R-001 | [What could go wrong] | H/M/L | H/M/L | [L×I] | [Prevention/reduction] | [Who] | [Open/Mitigated/Accepted/Closed] |

**Likelihood**: H=High (>50%), M=Medium (20-50%), L=Low (<20%)  
**Impact**: H=High (launch blocker), M=Medium (degraded launch), L=Low (minor issue)

### 6.2 Risk History

| ID | Risk | Final Status | Resolution | Date |
|----|------|--------------|------------|------|
| R-XXX | [Risk] | [How it ended] | [What we did] | [When] |

### 6.3 Dependencies

| ID | Dependency | Provider | Need By | Risk if Delayed | Mitigation | Status |
|----|------------|----------|---------|-----------------|------------|--------|
| D-001 | [What we need] | [Who/what provides] | [Date] | [Impact] | [Backup plan] | [On track/At risk/Blocked] |

---

## 7. Known Tensions

[Present-tense contradictions we're shipping with — not future risks]

| ID | Tension | Decision | Rationale | Accepted By | Revisit Trigger |
|----|---------|----------|-----------|-------------|-----------------|
| T-001 | [X requirement vs Y requirement] | [What we chose] | [Why] | [Who approved] | [When to reconsider] |

Example:
| T-001 | Performance (fast) vs Completeness (all data) | Return partial results after 5s | 95% of queries complete in <5s; users prefer fast partial over slow complete | Product lead, 2026-01-15 | If >10% of users report missing data |

---

## 8. Change Log

### 8.1 Requirement Changes

| Date | Req ID | Change Type | Description | Approved By |
|------|--------|-------------|-------------|-------------|
| [Date] | [ID] | [Add/Modify/Remove] | [What changed] | [Who] |

### 8.2 Baseline History

| Version | Date | Description | Approved By |
|---------|------|-------------|-------------|
| 1.0 | [Date] | Initial baseline | [Who] |
| 1.1 | [Date] | [What changed] | [Who] |

---

## 9. Open Questions

| ID | Question | Needed By | Owner | Status | Resolution |
|----|----------|-----------|-------|--------|------------|
| Q-001 | [What we don't know] | [Date] | [Who's investigating] | [Open/Resolved] | [Answer, if resolved] |

---

## 10. Appendices

### 10.1 Terminology

| Term | Definition |
|------|------------|
| [Term] | [What it means] |

### 10.2 Reference Documents

| Document | Purpose | Link |
|----------|---------|------|
| PRODUCT_DESIGN.md | Full product context | [Link] |
| ARCHITECTURE.md | Technical architecture | [Link] |
| [Other] | [Purpose] | [Link] |

---

## Validation Checklist

Before baselining this document:

- [ ] All requirements have unique IDs
- [ ] All requirements have priority assigned
- [ ] All requirements have acceptance criteria (in PRODUCT_DESIGN or here)
- [ ] All requirements have source (use case, stakeholder, constraint)
- [ ] Traceability links are populated or marked TBD
- [ ] NFR targets are specific numbers, not "fast" or "reliable"
- [ ] KPIs have baselines and targets
- [ ] Counter-KPIs defined (what we shouldn't break)
- [ ] Launch criteria are verifiable
- [ ] Risks have owners and mitigations
- [ ] Known tensions are documented honestly
- [ ] Out of scope has rationale, not just list
- [ ] Sign-off section has correct approvers

---

*"Requirements without traceability are wishes."*

*"A target without a baseline is a guess."*

*"Tensions are present. Risks are future. Track both."*
