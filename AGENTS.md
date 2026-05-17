# Repository Guidelines

## Project Structure & Module Organization

This is a Flask web app for downloading arXiv papers, generating AI summaries, and storing history in SQLite. Core backend entry points live at the repository root:

- `app.py`: Flask routes, background task orchestration, app startup.
- `services.py`: paper download, summary generation, full-analysis workflow.
- `db.py`: SQLite initialization, migrations, and paper history access.
- `utils.py`: arXiv parsing, file helpers, PDF/Markdown utilities.
- `prompts.py`: centralized LLM prompt text.
- `templates/index.html`, `static/css/style.css`, `static/js/app.js`: single-page frontend.
- `data/`: local runtime state, including `data/pdfs/` and `data/arxiv_history.db`.
- `assets/`: screenshots and documentation media.

## Build, Test, and Development Commands

Use Conda when possible:

```bash
conda env create -f environment.yml
conda activate arxiv_parser
python app.py
```

Alternative pip setup:

```bash
pip install -r requirements.txt
python app.py
```

Docker workflow:

```bash
docker compose up -d
docker compose up -d --build
docker compose down
```

Run the current parser/full-analysis smoke test with:

```bash
python test_file_parser.py
```

## Coding Style & Naming Conventions

Use Python 3.9-compatible code and follow PEP 8 conventions: 4-space indentation, `snake_case` for functions and variables, and `UPPER_CASE` for constants. Keep route handlers thin where practical; shared logic belongs in `services.py`, `db.py`, or `utils.py`. Keep prompt changes in `prompts.py` rather than embedding prompt text in route code. Frontend JavaScript uses plain ES6 functions and `camelCase` names.

## Testing Guidelines

There is no formal test runner configured yet. Add focused tests as `test_*.py` files and prefer deterministic unit tests around parsing, file path generation, database updates, and status transitions. Avoid tests that require live LLM or arXiv network calls unless clearly marked as integration checks. Before changing download or analysis behavior, run `python test_file_parser.py` with valid environment variables if the test path is available.

## Commit & Pull Request Guidelines

Recent commits use Conventional Commit-style prefixes such as `feat:`, `fix:`, and `refactor(app):`; keep that pattern. Write concise, imperative subjects and include scope when useful, for example `fix(db): preserve full analysis status`.

Pull requests should include a short behavior summary, setup or migration notes, linked issues when applicable, and screenshots for visible UI changes. Mention any environment variables required to verify the change.

## Security & Configuration Tips

Do not commit `.env`, API keys, generated PDFs, Markdown analyses, or SQLite databases. Required runtime configuration includes `OPENAI_API_KEY`; production deployments should also set a strong `SECRET_KEY`. Optional model settings include `OPENAI_BASE_URL`, `DEFAULT_MODEL`, `FULL_ANALYSIS_MODEL`, and DashScope-specific overrides.
