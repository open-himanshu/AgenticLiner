# Pre-Submission & Live Demo Checklist — AgenticLiner

## 1. Environment & Secret Hygiene
- [ ] Confirm `.env` is **excluded from git** (`.gitignore`) and never shown in slides, terminal dumps, or screenshots.
- [ ] For **offline deterministic demo** (recommended if campus/Wi-Fi blocks or throttles external LLM endpoints): leave `PROVIDER` unset (`""`) in shell/environment or set `TEST_CONSOLE=0`.
- [ ] For **live LLM demo**: set `PROVIDER=gemini` (ensure active quota / network connectivity) and keep `ALLOW_DEMO_LOGIN=1` only for demo environments.

## 2. Database & Server Startup Sequence
Run on a clean demo database before presenting:
```powershell
python -m backend.core.database.init_db --seed-demo
python -m backend.services.seed_users --force
$env:ALLOW_DEMO_LOGIN="1"
python -m uvicorn backend.api.main:app --host 127.0.0.1 --port 8000
```
*(Verify `init_db` includes `--seed-demo`, otherwise campus rooms/resources/speakers tables are empty.)*

## 3. Verified Demo Credentials (Seeded Accounts via Demo Login Modal or CLI Printout)
- **Supervisor (Dean):** `admin@galgotias.edu`
- **Organiser:** `organiser@galgotias.edu`
- **Data Manager:** `datamanager@galgotias.edu`
- **Participant:** `student@galgotias.edu`

## 4. Recommended Live Demo Flow (All Verified Working)
1. **Organiser -> `/autopilot`:** Run `"Dance performance, 150 students, next Friday 6 PM, budget 20000"`. Show adaptive intake (`budget=20000`), venue allocation, Kavach commit (`0` orphan resources), and held outbox dispatch.
2. **Organiser -> `/organiser/planner` & `/schedule`:** Submit an event in `Main Auditorium A` (triggers `pending_dean_approval`), then run **OR-Tools CP-SAT Solve** and **Hero Speaker Cancellation** cascade on `/schedule`.
3. **Supervisor -> `/supervisor`:** Inspect the **Campus Events Directory** table displaying all active, auto-approved, and pending events across campus with venue locations, headcount, and department organizers. Click **Details** on any event to inspect full logistics, requisitions, schedule agenda, and attendee counts. Filter by "Pending" to approve the pending Auditorium event -> verify status flips to `approved` and held notices release.
4. **Participant -> `/register` & `/participant`:** Register student, inspect QR gate pass & TF-IDF session/peer/mentor recommendations, ask `/api/assistant/ask` (`"What time is the Opening Keynote?"`), and submit a review in the fixed **Feedback Modal** (`0` console errors).
5. **Supervisor -> `/analytics` & `/verify/{cert_id}`:** View real DB sentiment percentages (`Lexicon + Hinglish Sentiment Engine`), switch events, download **Executive Report PDF**, issue a certificate, and open `/verify/{cert_id}` to show online verification count increment.

## 5. Honest Judge Q&A Disclosures
- Fixed-pipeline Autopilot records event `budget` cleanly; automated line-item `estimated_cost` calculation (`0.0`) and payment gateway/wallet tables are outside current scope.
- Sentiment & theme extraction uses a deterministic lexicon + negation + Hinglish classifier (no VADER dependency), while resource demand uses Scikit-Learn `Ridge` regression and participant matching uses `TfidfVectorizer` + cosine similarity.
- Final `pytest` suite and E2E verification passed cleanly against isolated databases while leaving `agenticliner.db` untouched.
