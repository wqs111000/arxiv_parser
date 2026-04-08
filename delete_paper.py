#!/usr/bin/env python3
"""
删除 arxiv_history.db 中指定 arxiv_id 的论文记录
同时会删除关联的 PDF 和 Markdown 文件

用法:
    python delete_paper.py <arxiv_id>
    
示例:
    python delete_paper.py 2501.08672
"""

import sqlite3
import os
import sys
from pathlib import Path

DB_PATH = 'data/arxiv_history.db'
PDF_FOLDER = 'data/pdfs'


def delete_paper(arxiv_id: str) -> dict:
    """删除指定 arxiv_id 的论文记录及相关文件"""
    
    if not os.path.exists(DB_PATH):
        return {'success': False, 'error': f'数据库不存在: {DB_PATH}'}
    
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    
    # 查询记录是否存在
    c.execute('SELECT pdf_path FROM papers WHERE arxiv_id = ?', (arxiv_id,))
    row = c.fetchone()
    
    if not row:
        conn.close()
        return {'success': False, 'error': f'论文不存在: {arxiv_id}'}
    
    pdf_path = row['pdf_path']
    deleted_files = []
    
    # 删除关联文件
    if pdf_path and os.path.exists(pdf_path):
        try:
            os.remove(pdf_path)
            deleted_files.append(pdf_path)
        except Exception as e:
            print(f'警告: 删除 PDF 失败: {e}')
    
    # 删除关联的 Markdown 文件
    if pdf_path:
        md_path = os.path.splitext(pdf_path)[0] + '.md'
        if os.path.exists(md_path):
            try:
                os.remove(md_path)
                deleted_files.append(md_path)
            except Exception as e:
                print(f'警告: 删除 Markdown 失败: {e}')
    
    # 删除数据库记录
    c.execute('DELETE FROM papers WHERE arxiv_id = ?', (arxiv_id,))
    conn.commit()
    conn.close()
    
    return {
        'success': True,
        'arxiv_id': arxiv_id,
        'deleted_files': deleted_files
    }


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    
    arxiv_id = sys.argv[1].strip()
    
    # 支持从 arxiv URL 中提取 ID
    if 'arxiv.org' in arxiv_id:
        import re
        match = re.search(r'arxiv\.org/(?:abs|pdf)/(\d+\.\d+|[a-z\-]+/\d+)', arxiv_id)
        if match:
            arxiv_id = match.group(1)
        else:
            print(f'错误: 无法从 URL 提取 arxiv_id: {arxiv_id}')
            sys.exit(1)
    
    result = delete_paper(arxiv_id)
    
    if result['success']:
        print(f'✓ 已删除论文: {result["arxiv_id"]}')
        if result['deleted_files']:
            print('  删除的文件:')
            for f in result['deleted_files']:
                print(f'    - {f}')
    else:
        print(f'✗ 删除失败: {result["error"]}')
        sys.exit(1)


if __name__ == '__main__':
    main()
