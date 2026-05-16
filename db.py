import logging
import sqlite3
from contextlib import contextmanager

logger = logging.getLogger(__name__)

DATABASE = 'data/arxiv_history.db'

_ALLOWED_UPDATE_COLUMNS = frozenset({
    'title', 'authors', 'abstract', 'url', 'pdf_path', 'version_history',
    'summary', 'summary_model', 'status', 'full_analysis', 'full_analysis_status',
})


@contextmanager
def get_db():
    conn = sqlite3.connect(DATABASE)
    conn.execute('PRAGMA journal_mode=WAL')
    conn.execute('PRAGMA synchronous=NORMAL')
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db():
    with get_db() as conn:
        conn.execute('''
            CREATE TABLE IF NOT EXISTS papers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                arxiv_id TEXT UNIQUE,
                title TEXT,
                authors TEXT,
                abstract TEXT,
                url TEXT,
                pdf_path TEXT,
                version_history TEXT,
                summary TEXT,
                summary_model TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                status TEXT DEFAULT 'pending',
                full_analysis TEXT,
                full_analysis_status TEXT DEFAULT 'none'
            )
        ''')
        conn.execute('CREATE INDEX IF NOT EXISTS idx_arxiv_id ON papers (arxiv_id)')
        conn.execute('CREATE INDEX IF NOT EXISTS idx_created_at ON papers (created_at)')
        for col in ('full_analysis TEXT', "full_analysis_status TEXT DEFAULT 'none'"):
            try:
                conn.execute(f'ALTER TABLE papers ADD COLUMN {col}')
            except Exception:
                pass


def _row_to_dict(cursor, row):
    return dict(zip([d[0] for d in cursor.description], row))


def save_paper(paper_data, summary=None, model=None, status=None,
               full_analysis=None, full_analysis_status=None):
    if status is None:
        status = 'completed' if summary else 'downloaded'
    if full_analysis_status is None:
        full_analysis_status = 'none'
    with get_db() as conn:
        conn.execute('''
            INSERT OR REPLACE INTO papers
            (arxiv_id, title, authors, abstract, url, pdf_path, version_history,
             summary, summary_model, status, full_analysis, full_analysis_status)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            paper_data['arxiv_id'], paper_data['title'], paper_data['authors'],
            paper_data['abstract'], paper_data['url'], paper_data['pdf_path'],
            paper_data.get('version_history', ''),
            summary, model, status, full_analysis, full_analysis_status,
        ))


def get_paper(arxiv_id):
    with get_db() as conn:
        c = conn.execute('SELECT * FROM papers WHERE arxiv_id = ?', (arxiv_id,))
        row = c.fetchone()
        if not row:
            return None
        return _row_to_dict(c, row)


def get_history(page=1, per_page=50):
    offset = (page - 1) * per_page
    with get_db() as conn:
        c = conn.execute(
            '''SELECT id, arxiv_id, title, version_history, created_at, status,
                      summary, full_analysis_status, pdf_path, authors
               FROM papers ORDER BY created_at DESC LIMIT ? OFFSET ?''',
            (per_page, offset),
        )
        cols = [d[0] for d in c.description]
        rows = [dict(zip(cols, r)) for r in c.fetchall()]
        total = conn.execute('SELECT COUNT(*) FROM papers').fetchone()[0]
    return rows, total


def update_paper(arxiv_id, **fields):
    if not fields:
        return
    invalid = set(fields) - _ALLOWED_UPDATE_COLUMNS
    if invalid:
        raise ValueError(f'update_paper: 不允许更新的列: {invalid}')
    set_clause = ', '.join(f'{k}=?' for k in fields)
    with get_db() as conn:
        conn.execute(
            f'UPDATE papers SET {set_clause} WHERE arxiv_id=?',
            (*fields.values(), arxiv_id),
        )


def remove_paper(arxiv_id):
    """Delete record and return pdf_path, or None if not found."""
    with get_db() as conn:
        c = conn.execute('SELECT pdf_path FROM papers WHERE arxiv_id=?', (arxiv_id,))
        row = c.fetchone()
        conn.execute('DELETE FROM papers WHERE arxiv_id=?', (arxiv_id,))
    return row[0] if row else None
