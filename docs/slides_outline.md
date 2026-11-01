# AgenticLiner: Pitch & Presentation Deck Outline
**Galgotias University SparkX 3.0 30-Day Innovation Challenge**
**Track Challenge #1: Event Planning & Management Platform**

---

## Slide 1: Title & Vision
- **Header**: AgenticLiner — Event Planning and Management Platform
- **Subtitle**: Optional agent mode, Google OR-Tools CP-SAT scheduling, and the Kavach safety layer
- **Team**: Technojam / Galgotias University Student Developers
- **Key Hook**: A campus-focused workflow for event briefs, venue and resource requests, schedules, and notifications.

---

## Slide 2: The Campus Problem
- **Scheduling and logistics risks**: Competing room requests, limited equipment, and speaker changes can complicate campus event planning.
- **Campus-specific workflow**: Organizers may need to coordinate facilities, inventory, schedules, and approvals alongside registrations.

---

## Slide 3: The Solution — AgenticLiner Architecture
- **Application Architecture**:
  1. **Planning (Copilot & Autopilot)**: Brief parsing, adaptive intake, countdown boards, and optional provider-backed tool calling. Prompt parsing includes a rule-based baseline.
  2. **Scheduling and Resource Estimates**:
     - **Google OR-Tools CP-SAT Solver**: Searches for schedules subject to the constraints represented in its model.
     - **Scikit-Learn Ridge Regression**: Estimates selected resource needs when sufficient historical data is available; otherwise the module uses a rule-based baseline.
  3. **Transactional Safety Engine (Kavach)**:
     - SQLite `SAVEPOINT` isolation.
     - Application-level checks include capacity, room overlap, speaker clashes, resource stock, time windows, budget, recipient limits, and blast radius.
     - Guarded operations can stage outbox records and roll back changes if an invariant fails.

---

## Slide 4: Implemented Module Areas
| Module | SparkX Requirement | AgenticLiner Implementation |
|---|---|---|
| **Module 1** | Event Planning Copilot | Rule-based baseline brief parsing, adaptive intake, task board, logistics requisition |
| **Module 2** | Intelligent Scheduling | Google OR-Tools CP-SAT Solver, Flyer Generator, Speaker-Cancellation Demo |
| **Module 3** | Resource Optimization | Ridge regression when training data is available; otherwise a rule-based baseline, plus inventory and approval routing |
| **Module 4** | Participant Experience | TF-IDF + Cosine Similarity Recommender and peer networking |
| **Module 5** | Communication | Rule-based baseline Q&A, outbox staging, schedule-change notices |
| **Module 6** | Feedback Analysis | Rule-based baseline sentiment and keyword-based theme classification |
| **Module 7** | Post-Event Analytics | Executive PDF report and QR-linked certificate lookup |

---

## Slide 5: The "Kavach" Safety Innovation (Our Core Differentiator)
- **How Kavach is used**:
  - In agent mode, a model can request tools; resource requisitions go through the Kavach-guarded tool.
  - Kavach wraps its guarded operations in SQLite `SAVEPOINT`s.
  - Requisition checks include venue capacity and overlap, resource stock, time-window, and budget rules.
  - When a guarded operation raises an invariant violation, Kavach rolls that operation back and returns violation details.

---

## Slide 6: Mathematical Scheduling with Google OR-Tools
- **Formulation**:
  - Binary decision variables: \( x_{s, r, t} \in \{0, 1\} \) where session \( s \) is assigned to room \( r \) at slot \( t \).
  - Subject to:
    1. Single assignment per session: \( \sum_{r, t} x_{s, r, t} = 1 \)
    2. Room capacity: assignments are limited to rooms that meet the session's attendance.
    3. Room non-overlapping: at most one session is assigned to a room in a slot.
    4. Speaker non-collision: at most one session for the same speaker is assigned in a slot.
    5. Session precedence: a declared prerequisite must be placed in an earlier slot.
- **Solver behavior**: The implementation returns a feasible or optimal schedule when CP-SAT finds one within its configured time limit; otherwise it returns a failure result. The model only represents the listed constraints and does not evaluate policies that are not encoded.

---

## Slide 7: Live Hero Demo Walkthrough (3-Minute Script)
1. **Organizer Input**: Paste rough prompt: *"Organize a 2-day AI Hackathon for 150 students"*.
2. **Autopilot Execution**: Show the timeline and the venue/resource result produced for the configured test data.
3. **The Speaker Cancellation Demo**: On the Schedule screen, click **Hero Demo: Speaker Cancels** and show the schedule-service result and any staged notice.
4. **Student Portal & Verification**: Open participant view to see interest-based recommendations, then scan a certificate QR code to open its certificate-ID lookup page.

---

## Slide 8: Evaluation & Benchmark Results
- The checked-in report at `eval/benchmark/results.json` records a run dated **2026-11-01** across **50 prompts**, using the scripted provider `benchmark-planner`:
  - **Setup A (Direct planned actions)**: 36 wrong final states, 0 errors caught, 36 errors missed.
  - **Setup B (SQLite constraints only)**: 36 wrong final states, 1 error caught, 35 errors missed.
  - **Setup C (Kavach agent pipeline)**: 17 wrong final states, 35 errors caught, 0 errors missed, and 3 valid requests wrongly blocked.
  - These counts describe the saved run only. It uses expected-result labels as its evaluation oracle, and its default provider is scripted rather than a live language model.
  - The independent checker audits each final temporary database for data-level violations.

---

## Slide 9: Impact & University Scalability
- **Campus data**: The schema seed includes sample university rooms, speakers, resources, and student records.
- **PDF reporting**: The analytics module can generate an executive PDF report.
- **Deployment requirements**: The application uses Python packages and can be configured to call external model or email providers; local operation does not imply that every feature works without external services.

---

## Slide 10: Conclusion & Q&A
- **Summary**: AgenticLiner combines optional provider-backed tool calling, constraint programming, and transactional database safeguards.
- **GitHub Repository**: Complete with tests, benchmarks, and API documentation.
- **Live Demo Link**: `http://127.0.0.1:8000`
- **Thank you!** Questions from the Jury.
