import os
import re


def extract_arxiv_id(url):
    patterns = [
        r'arxiv\.org/abs/(\d+\.\d+)',
        r'arxiv\.org/pdf/(\d+\.\d+)',
        r'arxiv\.org/abs/([a-z\-]+/\d+)',
        r'arxiv\.org/pdf/([a-z\-]+/\d+)',
    ]
    for pattern in patterns:
        m = re.search(pattern, url)
        if m:
            return m.group(1)
    return None


def clean_filename(title):
    cleaned = re.sub(r'[<>:"/\\|?*]', '_', title).strip()
    return cleaned[:200]


def extract_year(version_history, arxiv_id):
    """Return publication year as string from version_history or arXiv ID."""
    if version_history:
        m = re.search(r'Published\s+\d+\s+\w+\s+(\d{4})', version_history)
        if m:
            return m.group(1)
    m = re.search(r'(\d{2})\d{2}\.\d+', arxiv_id)
    if m:
        y = int(m.group(1))
        return str(1900 + y if y >= 90 else 2000 + y)
    return 'unknown'


def verify_pdf(filepath):
    """Return (is_valid, error_message)."""
    try:
        with open(filepath, 'rb') as f:
            header = f.read(8)
            if not header.startswith(b'%PDF-'):
                return False, f'文件头不是 PDF 格式: {header[:8]}'
            f.seek(0, 2)
            size = f.tell()
            if size < 1024:
                return False, f'文件过小 ({size} bytes)，可能下载不完整'
            f.seek(max(0, size - 1024))
            if b'%%EOF' not in f.read(1024):
                return False, 'PDF 文件尾部缺少 %%EOF 标记，可能下载不完整'
        return True, None
    except Exception as e:
        return False, f'验证 PDF 失败: {e}'


def get_md_path(pdf_path):
    if not pdf_path:
        return None
    return os.path.splitext(pdf_path)[0] + '.md'


def save_analysis_to_md(pdf_path, content):
    md_path = get_md_path(pdf_path)
    if md_path:
        with open(md_path, 'w', encoding='utf-8') as f:
            f.write(content)
        return md_path
    return None


def load_analysis_from_md(pdf_path):
    md_path = get_md_path(pdf_path)
    if md_path and os.path.exists(md_path):
        try:
            with open(md_path, 'r', encoding='utf-8') as f:
                return f.read()
        except Exception:
            pass
    return None
