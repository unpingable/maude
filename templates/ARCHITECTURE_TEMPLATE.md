# Architecture Documentation Template

## Usage

This template produces ARCHITECTURE.md for a system. Fill in bracketed sections with specifics. Delete instructional comments before finalizing.

---

# [SYSTEM NAME] Architecture

**Version**: [X.Y]  
**Last Updated**: [YYYY-MM-DD]  
**Owner**: [Team/Person]  
**Status**: [Draft | Review | Canonical]

---

## 1. Quick Reference

### 1.1 One-Paragraph Purpose

[What this system does, for whom, and why it exists. One paragraph max. If you can't say it in one paragraph, you don't understand it yet.]

### 1.2 System Diagram

```
[ASCII or Mermaid diagram showing components and their connections]
[What talks to what. External systems on the edges.]

Example:
┌─────────────┐     ┌─────────────┐     ┌─────────────┐
│   Client    │────▶│   Gateway   │────▶│   Service   │
└─────────────┘     └─────────────┘     └──────┬──────┘
                                               │
                                               ▼
                                        ┌─────────────┐
                                        │   Database  │
                                        └─────────────┘
```

### 1.3 Data Flow

```
[Request → Response flow through the system]
[Show the happy path first, then note where errors diverge]

Example:
1. Client sends request to Gateway
2. Gateway validates auth, forwards to Service
3. Service queries Database
4. Database returns result
5. Service transforms, returns to Gateway
6. Gateway returns to Client

Errors:
- Auth failure at step 2 → 401 to Client
- Database timeout at step 3 → retry 2x, then 503
```

### 1.4 Component Inventory

| Component | Responsibility | Key Dependencies | Owner |
|-----------|---------------|------------------|-------|
| [Name] | [One-liner: what it does] | [What it needs] | [Team] |
| ... | ... | ... | ... |

---

## 2. Core Invariants

[What must ALWAYS be true about this system. These are the constraints that cannot be violated without architectural review.]

- **[Invariant 1]**: [Statement]. Violated when: [condition]. Consequence: [what breaks].
- **[Invariant 2]**: [Statement]. Violated when: [condition]. Consequence: [what breaks].
- ...

Example:
- **Single source of truth for user state**: User record lives only in UserDB. Violated when: caching introduces stale reads > 5s. Consequence: billing errors, support escalations.

---

## 3. Design Rationale

### 3.1 Why These Components

| Component | Why This | Alternatives Considered | Why Not Alternative |
|-----------|----------|------------------------|---------------------|
| [Name] | [Reason] | [Option A, Option B] | [Specific trade-off] |
| ... | ... | ... | ... |

### 3.2 Technology Choices

| Technology | Purpose | Trade-off Accepted |
|------------|---------|-------------------|
| [Tech] | [Why chosen] | [What we gave up] |
| ... | ... | ... |

Example:
| PostgreSQL | ACID compliance for financial data | Gave up horizontal write scaling; mitigated with read replicas |

### 3.3 Architectural Patterns

| Pattern | Where Used | Why |
|---------|------------|-----|
| [Pattern name] | [Components] | [Specific benefit] |
| ... | ... | ... |

Example:
| CQRS | Order processing | Write path needs strong consistency; read path needs speed. Separated to optimize independently. |

---

## 4. Data Model

### 4.1 Entity Relationships

```
[ER diagram or table relationships]
[Show cardinality: 1:1, 1:N, N:M]

Example:
User (1) ──────< (N) Order (N) >────── (M) Product
                      │
                      └──< (N) LineItem
```

### 4.2 Key Entities

| Entity | Purpose | Key Fields | Mutability |
|--------|---------|------------|------------|
| [Name] | [What it represents] | [Important fields] | [Immutable / Append-only / Mutable] |
| ... | ... | ... | ... |

### 4.3 Data Design Decisions

| Decision | Rationale | Trade-off |
|----------|-----------|-----------|
| [Decision] | [Why] | [What we gave up] |
| ... | ... | ... |

Example:
| Orders are append-only | Audit trail, no lost data | Storage grows indefinitely; mitigated with archival after 2 years |

### 4.4 Data Flow

[Where data originates, how it transforms, where it lands]

```
Source → Ingestion → Validation → Storage → Serving
         │                        │
         └─► Dead letter queue    └─► Cache layer
```

---

## 5. Component Deep Dives

### 5.1 [Component Name]

**Purpose**: [One sentence]

**Responsibilities**:
- [Responsibility 1]
- [Responsibility 2]
- ...

**Does NOT do**:
- [Anti-responsibility 1 — what's explicitly out of scope]
- ...

**Dependencies**:
| Dependency | Type | Failure Impact |
|------------|------|----------------|
| [Name] | [Sync/Async, Required/Optional] | [What happens if unavailable] |

**Key Design Decisions**:

| Decision | Rationale | Trade-off |
|----------|-----------|-----------|
| [Decision] | [Why] | [Cost] |

**Integration Points**:
- Upstream: [Who calls this, how]
- Downstream: [What this calls, how]

**Known Limitations**:
- [Limitation 1]: [Why it exists, mitigation if any]
- ...

**Future Improvements**:
- [Improvement 1]: [Why deferred, trigger for revisiting]
- ...

[Repeat 5.1 for each major component]

---

## 6. Integration Patterns

### 6.1 External System Integrations

| External System | Integration Type | Data Exchanged | Owner |
|-----------------|------------------|----------------|-------|
| [System] | [REST/gRPC/Queue/etc] | [What flows] | [Who maintains] |

### 6.2 API Contracts

| Endpoint/Topic | Request Format | Response Format | Error Format |
|----------------|----------------|-----------------|--------------|
| [Endpoint] | [Schema or example] | [Schema or example] | [Error codes] |

### 6.3 Error Handling

| Error Class | Detection | Response | Recovery |
|-------------|-----------|----------|----------|
| [Error type] | [How detected] | [What returns] | [Auto/Manual, steps] |

Example:
| Upstream timeout | 30s deadline exceeded | 504 to caller | Auto-retry 2x with backoff, then circuit break for 60s |

### 6.4 Retry & Circuit Breaker Policies

| Integration | Retry Policy | Circuit Breaker | Fallback |
|-------------|--------------|-----------------|----------|
| [Name] | [N retries, backoff strategy] | [Threshold, duration] | [What happens when open] |

---

## 7. Failure Modes & Resilience

### 7.1 Failure Scenarios

| Component | Failure Mode | Blast Radius | Detection | Mitigation |
|-----------|--------------|--------------|-----------|------------|
| [Name] | [How it fails] | [What's affected] | [How we know] | [What happens automatically] |

Example:
| Database | Primary down | All writes fail | PgBouncer health check, alerts in <30s | Automatic failover to replica, 30-60s downtime |

### 7.2 Degraded Operation Modes

| Scenario | Degraded Behavior | User Impact | Recovery Trigger |
|----------|-------------------|-------------|------------------|
| [Scenario] | [What still works] | [What users see] | [How we return to normal] |

### 7.3 Recovery Procedures

| Failure | RTO | RPO | Recovery Steps | Runbook Link |
|---------|-----|-----|----------------|--------------|
| [Failure type] | [Time to recover] | [Data loss tolerance] | [High-level steps] | [Link] |

### 7.4 Chaos Testing Results

| Test | Date | Result | Issues Found | Remediation |
|------|------|--------|--------------|-------------|
| [Test name] | [Date] | [Pass/Fail] | [What broke] | [What we fixed] |

---

## 8. Performance & Scaling

### 8.1 Current Performance

| Metric | Current Value | Target | Measured When |
|--------|---------------|--------|---------------|
| p50 latency | [X ms] | [Y ms] | [Date, conditions] |
| p99 latency | [X ms] | [Y ms] | [Date, conditions] |
| Throughput | [X rps] | [Y rps] | [Date, conditions] |
| Error rate | [X%] | [<Y%] | [Date, conditions] |

### 8.2 Bottlenecks

| Bottleneck | Impact | Mitigation | Status |
|------------|--------|------------|--------|
| [What] | [Effect on performance] | [How addressed] | [Done/Planned/Accepted] |

### 8.3 Caching Strategy

| Cache | What's Cached | TTL | Invalidation | Hit Rate |
|-------|---------------|-----|--------------|----------|
| [Name] | [Data type] | [Duration] | [How/when] | [%] |

### 8.4 Database Strategy

| Table/Index | Purpose | Size | Growth Rate | Maintenance |
|-------------|---------|------|-------------|-------------|
| [Name] | [Why exists] | [Current] | [Per month] | [Vacuum, archival, etc] |

### 8.5 Scaling Limits

| Dimension | Current Capacity | Scaling Approach | Known Ceiling |
|-----------|------------------|------------------|---------------|
| [Users/Requests/Data] | [Current] | [Horizontal/Vertical/Shard] | [What breaks first] |

---

## 9. Security Architecture

### 9.1 Authentication Flow

```
[Diagram showing auth flow]

Example:
Client → Gateway (JWT validation) → Service (claims extraction) → Database (row-level security)
```

### 9.2 Authorization Model

| Resource | Who Can Access | How Enforced | Audit |
|----------|----------------|--------------|-------|
| [Resource] | [Roles/conditions] | [Where checked] | [What's logged] |

### 9.3 Data Protection

| Data Class | At Rest | In Transit | Access Logging |
|------------|---------|------------|----------------|
| [PII/Financial/etc] | [Encryption method] | [TLS version] | [What's captured] |

### 9.4 Vulnerability Surface

| Surface | Risk | Mitigation | Residual Risk |
|---------|------|------------|---------------|
| [Attack vector] | [What could happen] | [How prevented] | [What remains] |

### 9.5 Secrets Management

| Secret Type | Storage | Rotation | Access |
|-------------|---------|----------|--------|
| [API keys/certs/etc] | [Where stored] | [How often, how] | [Who/what can read] |

---

## 10. Operational Architecture

### 10.1 Deployment

| Component | Deployment Method | Rollback | Canary |
|-----------|-------------------|----------|--------|
| [Name] | [How deployed] | [How to rollback] | [% and duration] |

### 10.2 Observability

| Signal | Tool | Retention | Alert Threshold |
|--------|------|-----------|-----------------|
| Logs | [Tool] | [Duration] | [When alerts fire] |
| Metrics | [Tool] | [Duration] | [Key thresholds] |
| Traces | [Tool] | [Duration] | [Sampling rate] |

### 10.3 Key Dashboards

| Dashboard | Purpose | Link |
|-----------|---------|------|
| [Name] | [What it shows] | [URL] |

### 10.4 Alerting

| Alert | Condition | Severity | Response |
|-------|-----------|----------|----------|
| [Name] | [When fires] | [P1-P4] | [What to do] |

### 10.5 Backup & Recovery

| Data | Backup Frequency | Retention | Recovery Tested |
|------|------------------|-----------|-----------------|
| [What] | [How often] | [How long kept] | [Last test date, RTO achieved] |

### 10.6 Runbooks

| Scenario | Runbook | Last Updated | Last Used |
|----------|---------|--------------|-----------|
| [Failure type] | [Link] | [Date] | [Date] |

---

## 11. Known Tensions & Technical Debt

### 11.1 Unresolved Tensions

[Contradictions that exist and we're shipping anyway. Not risks (future) — tensions (present).]

| Tension | Components | Current State | Mitigation | Resolution Path |
|---------|------------|---------------|------------|-----------------|
| [X vs Y] | [What's affected] | [How we're living with it] | [Short-term fix] | [Long-term plan or "accepted"] |

Example:
| Consistency vs Availability | Order service, Inventory service | Eventual consistency with 5s window | Compensating transactions | Accepted — cost of strong consistency exceeds business value |

### 11.2 Technical Debt Register

| Debt Item | Impact | Severity | Incurred | Resolution Plan |
|-----------|--------|----------|----------|-----------------|
| [What] | [Effect] | [High/Med/Low] | [When/why] | [When/how to fix, or "accepted"] |

### 11.3 Architecture Decision Records

| ADR | Decision | Date | Status |
|-----|----------|------|--------|
| [ADR-NNNN] | [One-liner] | [Date] | [Accepted/Superseded/Deprecated] |

---

## 12. Evolution & Roadmap

### 12.1 Planned Changes

| Change | Rationale | Target Date | Dependencies |
|--------|-----------|-------------|--------------|
| [What] | [Why] | [When] | [What must happen first] |

### 12.2 Scaling Triggers

| Trigger | Threshold | Response |
|---------|-----------|----------|
| [Metric] | [Value] | [Architecture change needed] |

Example:
| Daily active users | >1M | Shard user database by region |

### 12.3 Deprecation Plans

| Component | Deprecated | Replacement | Removal Date | Migration Path |
|-----------|------------|-------------|--------------|----------------|
| [What] | [When deprecated] | [What replaces it] | [When removed] | [How to migrate] |

---

## 13. Appendices

### 13.1 Terminology

| Term | Definition |
|------|------------|
| [Term] | [What it means in this system] |

### 13.2 External Documentation

| Document | Purpose | Link |
|----------|---------|------|
| [Name] | [What it covers] | [URL] |

### 13.3 Revision History

| Version | Date | Author | Changes |
|---------|------|--------|---------|
| [X.Y] | [Date] | [Who] | [What changed] |

---

## Validation Checklist

Before marking this document Canonical:

- [ ] All bracketed placeholders filled with specifics
- [ ] All "Example:" sections replaced with real data
- [ ] Performance numbers are measured, not estimated
- [ ] Failure scenarios are from incidents, not imagination
- [ ] Trade-offs state what was given up, not just what was gained
- [ ] Known tensions section is honest, not empty
- [ ] Technical debt is registered, not hidden
- [ ] Runbooks exist and are linked
- [ ] Last updated date is current
- [ ] Owner is assigned and aware

---

*"If you can't say it in one paragraph, you don't understand it yet."*

*"Trade-offs state what was given up, not just what was gained."*

*"Tensions are present. Risks are future. Don't confuse them."*
