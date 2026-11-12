[RAN] # Live LLM Bounded Check
[RAN] Budget: 9 / 15 provider calls used (Step 2: 1, Step 3: 1, Step 4: 1, Step 5: 0, Step 6: 6). Halted on 429/quota/timeout: no.
[RAN] ## 1. Environment Check
[RAN] - PROVIDER: unset (`None`)
[RAN] - GEMINI_MODEL: `gemini-3.1-flash-lite`
[RAN] - GEMINI_API_KEY set: yes (length: 53)
[RAN] - Note on unset PROVIDER: `backend/core/planner/call_llm.py:get_provider_config` defaults `PROVIDER` to `"gemini"` when unset, whereas `backend/core/planner/agent_mode.py:run_autopilot_with_fallback` checks `not os.getenv("PROVIDER", "").strip()` and selects offline `mode="fixed"` when `PROVIDER` is unset.
[RAN] ## 2. Ping via `call_llm` ("Say OK", `tools=[]`)
[RAN] - Status: ok
[RAN] - Seconds: 1.43
[RAN] - Provider: gemini
[RAN] - Model configured (`res["model"]`): `gemini-3.1-flash-lite`
[RAN] - Model actually used (`response.model_version`): `gemini-3.1-flash-lite`
[RAN] - Tokens: prompt_tokens=4, completion_tokens=1, total_tokens=5
[RAN] - Response text: `OK`
[RAN] ## 3. Provider Model List (`google.genai.Client.models.list(config={"page_size": 100})`)
[RAN] - Provider: gemini (62 models returned on single page; `has_next_page=False`)
[RAN] - Models containing `"flash"` (27):
[RAN]   - `models/gemini-2.5-flash`
[RAN]   - `models/gemini-2.5-flash-preview-tts`
[RAN]   - `models/gemini-flash-latest`
[RAN]   - `models/gemini-flash-lite-latest`
[RAN]   - `models/gemini-2.5-flash-lite`
[RAN]   - `models/gemini-2.5-flash-image`
[RAN]   - `models/gemini-3-flash-preview`
[RAN]   - `models/gemini-3.1-flash-lite-preview`
[RAN]   - `models/gemini-3.1-flash-lite`
[RAN]   - `models/gemini-3.1-flash-image-preview`
[RAN]   - `models/gemini-3.1-flash-image`
[RAN]   - `models/gemini-3.1-flash-lite-image`
[RAN]   - `models/gemini-3.5-flash`
[RAN]   - `models/gemini-3.5-flash-lite`
[RAN]   - `models/gemini-omni-flash-preview`
[RAN]   - `models/gemini-omni-1.1-flash`
[RAN]   - `models/gemini-omni-1.2-flash`
[RAN]   - `models/gemini-3.6-flash`
[RAN]   - `models/gemini-3.7-flash`
[RAN]   - `models/gemini-3.8-flash`
[RAN]   - `models/gemini-3.1-flash-tts-preview`
[RAN]   - `models/gemini-3.8-flash-tts`
[RAN]   - `models/gemini-3.8-flash-lite-tts`
[RAN]   - `models/gemini-2.5-flash-native-audio-latest`
[RAN]   - `models/gemini-2.5-flash-native-audio-preview-09-2025`
[RAN]   - `models/gemini-2.5-flash-native-audio-preview-12-2025`
[RAN]   - `models/gemini-3.1-flash-live-preview`
[RAN] - Is `GEMINI_MODEL` (`gemini-3.1-flash-lite`) in the list?: yes (`models/gemini-3.1-flash-lite`)
[RAN] ## 4. Tool-Calling Call via `call_llm` (Single Dummy Tool: `get_venue_status`)
[RAN] - Status: ok
[RAN] - Seconds: 1.558
[RAN] - Tool call returned?: yes
[RAN] - Tool call returned details: `[{"name": "get_venue_status", "arguments": {"venue_name": "Main Auditorium A"}}]`
[RAN] - Tokens: prompt_tokens=76, completion_tokens=22, total_tokens=98
[RAN] ## 5. Agent-Mode Run (`run_autopilot_with_fallback`, Temp DB with `init_db --seed-demo`, `TEST_CONSOLE=0`)
[RAN] - Prompt: `"Dance performance, 150 students, next Friday 6 PM, budget 20000"`
[RAN] - mode: `fixed`
[RAN] - provider: `""`
[RAN] - model: `""`
[RAN] - success: `False`
[RAN] - fallback_reason: `""` (not present in `fixed` mode response)
[RAN] - Timeline:
[RAN]   - Step 1 | tool: `adaptive_intake` | status: `completed` | summary: `Extracted: Event Type='Cultural', Headcount=150 students, Slot=2026-11-25 (09:00:00 - 17:00:00).`
[RAN]   - Step 2 | tool: `find_free_venues` | status: `rolled_back` | summary: `No hall on campus satisfies requested capacity of 150 students on 2026-11-25. Proposing alternative hall or date.`
[RAN] - tokens_used: `{"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}`
[RAN] - total_seconds: 0.004
[RAN] ## 6. Q&A Assistant Check (`CommunicationAgent.answer_query("ev_001", ...)` on Seeded Temp DB)
[RAN] ### Question 1: `"Where can I park my car?"`
[RAN] - Call 1: mode=`llm` (provider=`gemini`, model=`gemini-3.1-flash-lite`), seconds=1.341, answer=`I apologize, but I do not have information regarding parking facilities in the event schedule. Please check with the university security or campus administration for guidance on parking areas.`
[RAN] - Call 2: mode=`llm` (provider=`gemini`, model=`gemini-3.1-flash-lite`), seconds=1.211, answer=`I apologize, but I do not have information regarding parking facilities in the event schedule. Please check with the university security or campus administration for guidance on parking areas.`
[RAN] - Same facts?: yes (verbatim identical; both state no parking information exists in the event schedule and refer to university security/administration).
[RAN] ### Question 2: `"Robotics workshop kis hall mein hai?"`
[RAN] - Call 1: mode=`llm` (provider=`gemini`, model=`gemini-3.1-flash-lite`), seconds=1.606, answer=`SparkX 3.0 ke schedule mein 'Robotics' naam ka koi workshop nahi hai. Aap upar diye gaye sessions mein se kisi aur workshop ke baare mein jaankari chahte hain toh bataiye.`
[RAN] - Call 2: mode=`llm` (provider=`gemini`, model=`gemini-3.1-flash-lite`), seconds=1.273, answer=`SparkX 3.0 ke schedule mein 'Robotics' naam ka koi workshop nahi hai. Aap upar diye gaye sessions mein se kisi aur workshop ke baare mein jaankari chahte hain toh bataiye.`
[RAN] - Same facts?: yes (verbatim identical; both state there is no workshop named `'Robotics'` in the SparkX 3.0 schedule).
[RAN] ### Question 3: `"Keynote kitne baje hai?"`
[RAN] - Call 1: mode=`llm` (provider=`gemini`, model=`gemini-3.1-flash-lite`), seconds=1.282, answer=`Opening Keynote & Welcome session 25 November 2026 ko subah 09:30 baje se 11:00 baje tak Main Auditorium A (Block C, Ground Floor) mein hoga.`
[RAN] - Call 2: mode=`llm` (provider=`gemini`, model=`gemini-3.1-flash-lite`), seconds=2.479, answer=`Opening Keynote & Welcome session 25 November 2026 ko subah 09:30 baje se 11:00 baje tak Main Auditorium A (Block C, Ground Floor) mein hoga.`
[RAN] - Same facts?: yes (verbatim identical; both state `Opening Keynote & Welcome`, `25 November 2026`, `09:30` to `11:00`, `Main Auditorium A (Block C, Ground Floor)`).
