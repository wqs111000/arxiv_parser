# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

**Run the app locally:**
```bash
conda activate arxiv_parser
python app.py
```

**Install dependencies (Conda, recommended):**
```bash
conda env create -f environment.yml
conda activate arxiv_parser
```

**Install dependencies (pip):**
```bash
pip install -r requirements.txt
```

**Docker:**
```bash
docker compose up -d          # start
docker compose up -d --build  # rebuild and start
docker compose down           # stop
```

**Run tests:**
```bash
python test_file_parser.py
```

## Architecture

This is a single-file Flask web app (`app.py`) for downloading and AI-summarizing arXiv papers.

**Backend (`app.py`):**
- Flask routes under `/api/*` handle paper processing, status polling, PDF download, and history
- `download_paper()` uses the `arxiv` Python library with 429 retry logic; validates PDF integrity (`_verify_pdf_integrity()`) before and after download
- `generate_summary()` calls any OpenAI-compatible API (configured via `.env`) on the paper abstract to produce a structured Chinese summary
- `generate_full_analysis()` uploads the PDF to DashScope (Alibaba Cloud) and uses `qwen-long` for full-text analysis; polls file processing status before calling the model; deletes uploaded file after use
- Both summary and full-analysis run in background threads (`threading.Thread`) so `/api/process` returns immediately; the frontend polls `/api/status/<arxiv_id>` for completion
- SQLite database at `data/arxiv_history.db` stores all paper metadata and results; schema migration is done inline at startup with `ALTER TABLE ... ADD COLUMN` wrapped in try/except

**Prompts (`prompts.py`):**
- All LLM prompts are centralized here. Edit this file to change summary structure or full-analysis sections.

**Frontend (`templates/index.html`, `static/`):**
- Single-page app using Bootstrap 5, KaTeX for LaTeX rendering
- `static/js/app.js` handles form submission, status polling, and history panel

**Data layout:**
- `data/pdfs/` — downloaded PDFs, named `{year}_{title}.pdf`
- `data/pdfs/{year}_{title}.md` — full-analysis Markdown files (co-located with PDFs)
- `data/arxiv_history.db` — SQLite database

## Key environment variables

| Variable | Purpose |
|---|---|
| `OPENAI_API_KEY` | Required. Used for both summary (any OpenAI-compatible provider) and full analysis (DashScope) |
| `OPENAI_BASE_URL` | API endpoint (default: OpenAI). Set to `https://api.deepseek.com/v1` for DeepSeek, etc. |
| `DEFAULT_MODEL` | Model for abstract summaries (default: `deepseek-chat`) |
| `FULL_ANALYSIS_MODEL` | Model for full-text analysis (default: `qwen-long`) |
| `DASHSCOPE_API_KEY` | Optional override for DashScope API key (falls back to `OPENAI_API_KEY`) |
| `DASHSCOPE_BASE_URL` | Optional override for DashScope endpoint |
| `FLASK_PORT` | Server port (default: `5000`) |

Copy `.env.example` to `.env` and fill in values before running.
