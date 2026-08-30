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

This is a Flask web app for downloading and AI-summarizing arXiv papers, with a paper knowledge base for cross-paper semantic search.

**Backend (`app.py`):**
- Flask routes under `/api/*` handle paper processing, status polling, PDF download, history, and knowledge base search
- Imported modules: `services.py` (business logic), `db.py` (SQLite), `utils.py` (helpers), `prompts.py` (AI prompts), `knowledge_store.py` (vector indexing), `knowledge_search.py` (retrieval + synthesis)

**Services (`services.py`):**
- `download_paper()` uses the `arxiv` Python library with 429 retry logic; validates PDF integrity (`verify_pdf()`) before and after download
- `generate_summary()` calls any OpenAI-compatible API (configured via `.env`) on the paper abstract to produce a structured Chinese summary
- `generate_full_analysis()` uploads the PDF to DashScope (Alibaba Cloud) and uses `qwen-long` for full-text analysis; polls file processing status before calling the model; deletes uploaded file after use
- `run_full_analysis()` runs in a background thread and auto-indexes the paper into the knowledge base on success

**Knowledge base (`knowledge_store.py`, `knowledge_search.py`):**
- Full-analysis results are automatically indexed into ChromaDB (vector database stored at `data/chromadb/`)
- Papers are chunked by `###` headers and embedded via OpenAI-compatible embedding API
- `/api/search?q=...` performs semantic search and AI-synthesizes answers from retrieved chunks
- `EMBEDDING_MODEL`, `EMBEDDING_BASE_URL`, `EMBEDDING_API_KEY` env vars control the embedding service

**Prompts (`prompts.py`):**
- All LLM prompts are centralized here. Edit this file to change summary structure or full-analysis sections.

**Frontend (`templates/index.html`, `static/`):**
- Single-page app using Bootstrap 5, KaTeX for LaTeX rendering
- `static/js/app.js` handles form submission, status polling, history panel, and knowledge base search

**Data layout:**
- `data/pdfs/` — downloaded PDFs, named `{year}_{title}.pdf`
- `data/pdfs/{year}_{title}.md` — full-analysis Markdown files (co-located with PDFs)
- `data/arxiv_history.db` — SQLite database
- `data/chromadb/` — ChromaDB vector database for knowledge base search

## Key environment variables

| Variable | Purpose |
|---|---|
| `OPENAI_API_KEY` | Required. Used for both summary (any OpenAI-compatible provider) and full analysis (DashScope) |
| `OPENAI_BASE_URL` | API endpoint (default: OpenAI). Set to `https://api.deepseek.com/v1` for DeepSeek, etc. |
| `DEFAULT_MODEL` | Model for abstract summaries (default: `deepseek-chat`) |
| `FULL_ANALYSIS_MODEL` | Model for full-text analysis (default: `qwen-long`) |
| `DASHSCOPE_API_KEY` | Optional override for DashScope API key (falls back to `OPENAI_API_KEY`) |
| `DASHSCOPE_BASE_URL` | Optional override for DashScope endpoint |
| `EMBEDDING_API_KEY` | API key for embeddings (falls back to `OPENAI_API_KEY`) |
| `EMBEDDING_BASE_URL` | Embedding API endpoint (default: `https://api.openai.com/v1`) |
| `EMBEDDING_MODEL` | Embedding model (default: `text-embedding-3-small`) |
| `FLASK_PORT` | Server port (default: `5000`) |

Copy `.env.example` to `.env` and fill in values before running.
