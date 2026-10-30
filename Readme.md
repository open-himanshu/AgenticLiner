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

## Choosing a provider

Set `PROVIDER` in `.env` to one of `ollama`, `gemini`, or `groq`.

- `ollama`: Install and start Ollama locally. Set `OLLAMA_MODEL` if you want a
  model other than the script's default.
- `gemini`: Set `GEMINI_API_KEY` and `GEMINI_MODEL`.
- `groq`: Set `GROQ_API_KEY` and `GROQ_MODEL`.

Groq requests use the standard-library `urllib`; no Groq Python package is
required. Gemini uses `google-genai`, and `.env` loading uses `python-dotenv`.
