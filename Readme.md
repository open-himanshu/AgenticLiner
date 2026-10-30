# AgenticLiner

## Setup (Windows PowerShell)

1. Clone the repository and enter its folder:

   ```powershell
   git clone https://github.com/open-himanshu/AgenticLiner-manual.git
   cd AgenticLiner-manual
   ```

2. Create and activate a Conda environment with Python 3.12:

   ```powershell
   conda create --name agenticliner python=3.12 -y
   conda activate agenticliner
   ```

3. Install the project requirements:

   ```powershell
   python -m pip install -r requirements.txt
   ```

4. Create your local configuration file:

   ```powershell
   Copy-Item .env.example .env
   ```

   Edit `.env` to provide the API key and model for the provider you intend to
   use. Do not commit `.env`.

5. Run the offline self-test (it does not call a provider):

   ```powershell
   python backend\planner\test_tool_calling.py --selftest
   ```

## LLM diagnostics

Run the provider doctor to check network access, text generation, JSON output,
and function calling. It loads the repo-root `.env` at runtime and makes live
requests to the selected provider, so it is not an offline test:

```powershell
python -m backend.planner.llm_doctor --provider all
```

Use `--provider gemini`, `--provider groq`, or `--provider ollama` to check one
provider. Missing credentials or model settings are reported as skipped without
printing their values.

The deterministic fallback books without an LLM by default:

```powershell
python -m backend.planner.fixed_pipeline --event-type dance --headcount 150 --date "next Friday" --start-hour 18 --end-hour 20 --budget 20000
```

`--use-llm` is optional and only asks the configured provider to polish the
notice wording; a fixed template is used if that call fails.

## Choosing a provider

Set `PROVIDER` in `.env` to one of `ollama`, `gemini`, or `groq`.

- `ollama`: Install and start Ollama locally. Set `OLLAMA_MODEL` if you want a
  model other than the script's default.
- `gemini`: Set `GEMINI_API_KEY` and `GEMINI_MODEL`.
- `groq`: Set `GROQ_API_KEY` and `GROQ_MODEL`.

Groq requests use the standard-library `urllib`; no Groq Python package is
required. Gemini uses `google-genai`, and `.env` loading uses `python-dotenv`.
