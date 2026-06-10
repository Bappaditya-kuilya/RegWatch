# RegWatch

Agentic regulatory change intelligence for Indian MSMEs.

## Setup

```bash
source .venv/bin/activate
uv pip install -r requirements.txt
cp .env.example .env
streamlit run ui/app.py
```

## Streamlit Community Cloud

Deploy using the GitHub repo and set these secrets in the Streamlit app settings:

```toml
GROQ_API_KEY="your_groq_key"
COHERE_API_KEY="your_cohere_key"
GEMINI_API_KEY="your_gemini_key"
LOG_LEVEL="INFO"
SCHEDULE_INTERVAL_HOURS="24"
DATA_DIR="./data"
```

Recommended entrypoint:

```text
ui/app.py
```

Recommended first run after deployment:

1. Open the app
2. Use `Demo Mode`
3. Run `python scripts/seed_data.py --clean --skip-remote --manifest tests/fixtures/demo_manifest.json` locally before pushing if you want a clean fixture-driven state in the repo workflow

For Streamlit Cloud demos, keep the UI in `Demo Mode` rather than `Live Scrape`.
