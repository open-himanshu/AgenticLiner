# AgenticLiner Viva Examination: 25 Defense Questions and Evidence-Based Answers
*Single Source of Truth: `FACT_SHEET.md`, `RESULT_AND_LIMITATION.md`, and `TEAM.md`*

---

### Q1: Would a plain database constraint not do the same?
In our 50-prompt benchmark, plain SQLite constraints in Setup B stopped 16 out of 20 invalid requests, performing almost as effectively as Kavach's 17 stops [READ: RESULT_AND_LIMITATION.md:4, 8]. Kavach's measured additions beyond database constraints are the per-request write blast radius limit and the destructive-request pre-filter, while Setup B missed 3 bulk-write requests and 1 DROP TABLE command [READ: RESULT_AND_LIMITATION.md:6, 8]. Furthermore, transactional rollback within savepoints and staging outbox notices only after commits occur in application logic rather than database constraints alone, though these were not separately isolated in the benchmark [READ: RESULT_AND_LIMITATION.md:8].

---

### Q2: Is the payment real?
No, payment processing is not implemented in the platform [READ: FACT_SHEET.md:190]. The SQLite database schema contains no payment gateway integrations, wallet ledgers, or financial transaction tables [READ: FACT_SHEET.md:190]. All internal campus venues and equipment allocations explicitly set estimated cost to 0.0 because campus resources carry no rental fee [READ: FACT_SHEET.md:192; READ: RESULT_AND_LIMITATION.md:16].

---

### Q3: What if the LLM fails?
When an external LLM fails, returns malformed tool arguments, or throws an HTTP 400 error due to missing thought signatures, Autopilot executes a clean fallback to a deterministic fixed pipeline [READ: FACT_SHEET.md:37, 150]. This procedural 5-step fallback pipeline completes intake heuristics, room discovery, resource allocation, and booking commits without calling an external model [READ: FACT_SHEET.md:38; TEST: test_autopilot_api]. In empirical live testing, two runs that encountered provider HTTP 400 errors fell back to this fixed pipeline and successfully confirmed bookings [READ: FACT_SHEET.md:150-152; READ: RESULT_AND_LIMITATION.md:9].

---

### Q4: Why did Kavach miss the speaker clashes?
Setup C missed all 3 speaker-clash requests in the benchmark because the runtime agent booking tool does not accept a speaker parameter [READ: RESULT_AND_LIMITATION.md:6; READ: FACT_SHEET.md:194]. Although the speaker conflict rule is implemented in `kavach.py` and passes standalone unit tests, it is not wired into `tool_requisition_campus_resources` at runtime [READ: FACT_SHEET.md:39, 194; TEST: test_kavach]. Speaker availability constraints are currently enforced in batch mode by the Module 2 CP-SAT solver rather than on the single-turn agent execution path [READ: FACT_SHEET.md:29, 194; TEST: test_module_2].

---

### Q5: Is the data real?
No, all evaluation data is synthetic and runs against a seeded local test database [READ: RESULT_AND_LIMITATION.md:2, 13]. The benchmark used 50 synthetic prompt fixtures comprising 15 clean, 15 high-conflict, 2 destructive, 3 bulk-write, and 15 ambiguous scenarios [READ: FACT_SHEET.md:104; READ: RESULT_AND_LIMITATION.md:2]. The catalog data represents a simulated campus environment with 7 rooms, 13 equipment items, and 5 guest speakers [READ: FACT_SHEET.md:182].

---

### Q6: What did you build yourselves?
The team designed the core problem definition, overall architecture, and the Kavach transactional safety concept [READ: TEAM.md:5]. The team built the 7 domain modules, the Autopilot dual-mode planner, the SQLite database schema across 14 tables, and a 70-endpoint FastAPI application [READ: FACT_SHEET.md:46-59; READ: TEAM.md:5]. The team also constructed the offline evaluation harness, an independent benchmark checker that shares no code with Kavach, and 343 passing automated tests [READ: TEAM.md:5; READ: RESULT_AND_LIMITATION.md:2; RAN: pytest -q].

---

### Q7: How was the code written?
The source code was written primarily by AI coding assistants (Antigravity) operating under the direct guidance and architectural supervision of the team lead [READ: TEAM.md:5]. The lead defined the build plan, designed review gates, and instructed the assistants on the safety boundary, agent mode, and security hardening [READ: TEAM.md:5]. Team members Diya Varshney and Ashish Kumar Singh executed testing, reported defects to the lead, and verified platform behaviors [READ: TEAM.md:8, 11].

---

### Q8: What does the safety layer not catch?
Kavach only catches invariants that are explicitly wired into runtime code, leaving unwired checks like runtime speaker clashes undetected [READ: RESULT_AND_LIMITATION.md:6, 15]. Its write blast radius limit blocks valid requests if a single booking requires more resource records than the threshold allows [READ: RESULT_AND_LIMITATION.md:15]. Furthermore, Kavach does not inspect semantic sarcasm in attendee reviews, nor does it resolve relative dates without an explicit anchor date in intake briefs [READ: FACT_SHEET.md:28, 33].

---

### Q9: What specific operational problem does AgenticLiner solve?
Campus event organisers currently coordinate venues, equipment, schedules, and notifications manually across disconnected spreadsheets [READ: FACT_SHEET.md:14]. Placing an unconstrained LLM directly on database booking tools risks double-booking venues, exceeding room capacities, or leaving multi-step updates partially executed [READ: FACT_SHEET.md:14]. AgenticLiner wraps planning operations in a transactional validation boundary so that database changes and broadcast notices only occur when physical invariants pass [READ: FACT_SHEET.md:14, 20; TEST: test_kavach].

---

### Q10: How does Autopilot differ between agent mode and the fixed pipeline?
Agent mode uses multi-turn LLM function calling across venue discovery, resource recommendation, and commit tools to fulfill an organiser's brief dynamically [READ: FACT_SHEET.md:37; TEST: test_agent_mode]. The fixed pipeline executes a deterministic 5-step procedural Python workflow that resolves bookings offline without making network or LLM calls [READ: FACT_SHEET.md:38; TEST: test_autopilot_api]. If agent mode encounters missing thought signatures or model failures, the system switches to the fixed pipeline as a reliable fallback [READ: FACT_SHEET.md:37, 150].

---

### Q11: How does the Kavach safety layer execute transactional rollback?
Kavach executes all booking insertions and resource allocations within an isolated SQLite savepoint [READ: FACT_SHEET.md:39, 48; TEST: test_kavach]. It evaluates 5 active invariants—room capacity, venue double-booking, operating hours, resource stock, and write blast radius—before permitting a commit [READ: FACT_SHEET.md:39; TEST: test_kavach]. If any invariant check fails, Kavach rolls back the savepoint completely, records a quarantined entry in the audit log, and raises a validation error [READ: FACT_SHEET.md:39, 56; TEST: test_kavach].

---

### Q12: Why does the system stage notifications in an outbox rather than sending them immediately?
Immediate dispatch risks sending participants email notices for database changes that subsequently fail or roll back [READ: FACT_SHEET.md:14; TEST: test_kavach]. AgenticLiner implements the transactional outbox pattern, writing notification records to an `outbox` table only within the confirmed database transaction [READ: FACT_SHEET.md:55; TEST: test_kavach]. Actual notification dispatch occurs strictly after the booking transaction successfully commits, preventing phantom notices [READ: FACT_SHEET.md:48; TEST: test_kavach].

---

### Q13: How does Module 2 schedule sessions and resolve timetable conflicts?
Module 2 formulates timetable scheduling as a constraint satisfaction problem and solves it using Google OR-Tools CP-SAT [READ: FACT_SHEET.md:29; TEST: test_module_2]. The solver enforces hard constraints across room capacities, speaker availability windows, and session prerequisite orderings [READ: FACT_SHEET.md:29; TEST: test_module_2]. However, Module 2 operates strictly as a batch solver and is not dynamically called during single-turn agent edits [READ: FACT_SHEET.md:29].

---

### Q14: How does Module 3 recommend equipment and catering resources for an event?
Module 3 combines rule heuristics with a historical Ridge regression model to forecast equipment, power, AV, and catering needs based on event type and headcount [READ: FACT_SHEET.md:30; TEST: test_module_3]. Proposed allocations are checked against available inventory counts in the `resources` table to prevent over-requisitioning [READ: FACT_SHEET.md:30, 52; TEST: test_module_3]. A documented limitation is that internal campus inventory is assigned a cost of 0.0, as no multi-vendor commercial pricing model exists [READ: FACT_SHEET.md:30, 192].

---

### Q15: How do the participant personalization and Q&A modules operate?
Module 4 computes cosine similarity over TF-IDF vectors to match student academic interests to relevant non-conflicting event sessions [READ: FACT_SHEET.md:31; TEST: test_module_4]. Module 5 answers attendee logistical questions using a prompt strictly grounded in SQLite database records, falling back to keyword heuristics when offline [READ: FACT_SHEET.md:32; TEST: test_module_5]. Queries regarding unrecorded information, such as parking availability, return an administrative disclaimer rather than an ungrounded hallucination [READ: FACT_SHEET.md:32; TEST: test_module_5].

---

### Q16: How are the digital participation certificates verified?
Module 7 generates participation certificates as PDF documents rendered using ReportLab with an embedded QR code [READ: FACT_SHEET.md:34; TEST: test_module_7]. Each certificate includes a SHA-256 cryptographic hash computed over student and event metadata, stored in the `certificates` table [READ: FACT_SHEET.md:34, 54; TEST: test_module_7]. Scanning the QR code verifies the document against the local SQLite database, though verification does not rely on a public blockchain [READ: FACT_SHEET.md:34].

---

### Q17: How was the offline evaluation benchmark structured, and what is its sample size?
The benchmark evaluated 50 total prompts, comprising 35 safety prompts and 15 ambiguous intake prompts on a synthetic campus database [READ: FACT_SHEET.md:104; READ: RESULT_AND_LIMITATION.md:2, 13]. It compared three configurations receiving identical requests: Setup A without constraints, Setup B with plain SQLite constraints, and Setup C with the Kavach pipeline [READ: RESULT_AND_LIMITATION.md:2]. A scripted planner replaced the LLM to ensure offline repeatability, meaning sample size n is small and measures the safety boundary rather than model quality [READ: RESULT_AND_LIMITATION.md:2, 13].

---

### Q18: How were destructive requests like DROP TABLE tested and prevented?
Destructive testing included 2 prompts attempting SQL injection and table deletion within the 50-scenario benchmark [READ: RESULT_AND_LIMITATION.md:2, 5; READ: FACT_SHEET.md:112]. Setup C stopped both destructive requests before database execution using a regex-based pre-filter [READ: RESULT_AND_LIMITATION.md:5, 17; READ: FACT_SHEET.md:112]. The agent itself has no database deletion tool, so destructive testing exercises only this input filtering regex [READ: RESULT_AND_LIMITATION.md:17].

---

### Q19: What were the exact results when you tested with a live LLM?
Live testing on 11-11-2026 used Gemini 3.1 flash-lite across a bounded budget of 9 calls [READ: FACT_SHEET.md:138, 139]. A basic ping succeeded in 1.43 seconds, and venue tool calling completed in 1.558 seconds [READ: FACT_SHEET.md:140, 142]. Three participant Q&A questions asked twice each yielded identical answers across repeated queries in 1.2 to 2.5 seconds [READ: FACT_SHEET.md:144; READ: RESULT_AND_LIMITATION.md:9].

---

### Q20: Did a live multi-turn agent complete an event booking end-to-end?
In live agent checks on 11-11-2026, the model executed a venue search tool call on turn 1 [READ: FACT_SHEET.md:149, 150]. On turn 2, the model returned an HTTP 400 error due to a missing thought signature in the function call parts [READ: FACT_SHEET.md:150]. Autopilot cleanly triggered its fixed fallback pipeline, which completed the booking insertion and notice staging successfully [READ: FACT_SHEET.md:150-152; READ: RESULT_AND_LIMITATION.md:9].

---

### Q21: What automated test coverage exists for the platform?
The platform contains 343 passing automated tests that execute entirely offline without network access [READ: FACT_SHEET.md:83, 84; RAN: python -m pytest -q]. The suite spans 298 root functional tests, 7 integration workflows, 16 Kavach safety invariant tests, 14 algorithm unit tests, and 8 evaluation harness tests [READ: FACT_SHEET.md:86-90]. All 343 tests pass with 0 failures and 0 errors in under 172 seconds [READ: FACT_SHEET.md:84; RAN: python -m pytest -q].

---

### Q22: How are user authentication and role-based permissions enforced?
Authentication supports 4 distinct roles—supervisor, organiser, data_manager, and participant—using signed session cookies [READ: FACT_SHEET.md:40, 47; TEST: test_auth]. Password authentication relies on PBKDF2 hashing, and routes are protected by role-checking dependencies in FastAPI [READ: FACT_SHEET.md:40, 47; TEST: test_auth]. While a demo login path functions locally, production Firebase token validation requires live network connectivity and remains unverified offline [READ: FACT_SHEET.md:40, 198].

---

### Q23: How does the platform handle event budgets and monetary costs?
The platform does not implement a monetary cost or budget optimization model [READ: FACT_SHEET.md:192]. All campus venues, equipment, and hospitality resources set estimated cost to 0.0 because they represent internal university inventory [READ: FACT_SHEET.md:30, 192]. Budget input fields were completely removed from the user interface and are absent from all 12 interface screens [READ: FACT_SHEET.md:186, 192].

---

### Q24: Are the voice control and SMTP email notifications verified?
No, neither client-side voice input nor outbound SMTP email dispatch was verified in automated testing [READ: FACT_SHEET.md:196, 197; READ: RESULT_AND_LIMITATION.md:18]. Voice recognition relies entirely on client browser Web Speech APIs that cannot be validated in headless testing environments [READ: FACT_SHEET.md:196]. SMTP email transmission writes staged records to the local `outbox` table with status 'sent', but actual network delivery requires external SMTP credentials [READ: FACT_SHEET.md:197].

---

### Q25: How does the system perform under high concurrent multi-tenant loads?
Cannot answer from evidence [READ: FACT_SHEET.md:248]. The benchmark and test suite execute strictly on local SQLite database instances, leaving multi-tenant production concurrency unmeasured [READ: FACT_SHEET.md:49, 248]. High concurrent write bursts are theoretically bounded by SQLite file-level locking, and production multi-user stress testing is explicitly documented as unverified [READ: FACT_SHEET.md:35, 248].
