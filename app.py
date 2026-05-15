import os
import threading
from urllib.parse import quote

from flask import Flask, render_template, request, jsonify, send_file, Response
from dotenv import load_dotenv

load_dotenv()

import db
import utils
from services import download_paper, generate_summary, run_full_analysis, cleanup_corrupted_files, UPLOAD_FOLDER

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', os.urandom(24).hex())

os.makedirs(UPLOAD_FOLDER, exist_ok=True)
db.init_db()
cleanup_corrupted_files()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _pdf_info(pdf_path):
    """Return (pdf_exists, md_path, md_exists) for a given pdf_path."""
    pdf_exists = bool(pdf_path and os.path.exists(pdf_path))
    md_path = utils.get_md_path(pdf_path)
    md_exists = bool(md_path and os.path.exists(md_path))
    return pdf_exists, md_path, md_exists


def _enrich_paper(paper):
    """Add pdf_exists, md_exists, md_file_path fields to a paper dict."""
    pdf_exists, md_path, md_exists = _pdf_info(paper.get('pdf_path'))

    full_analysis = paper.get('full_analysis')
    fa_status = paper.get('full_analysis_status') or 'none'

    if not full_analysis and md_exists:
        full_analysis = utils.load_analysis_from_md(paper['pdf_path'])
        if full_analysis:
            fa_status = 'completed'
            db.update_paper(paper['arxiv_id'], full_analysis=full_analysis,
                            full_analysis_status='completed')

    return {
        **paper,
        'pdf_exists': pdf_exists,
        'md_exists': md_exists,
        'md_file_path': md_path if md_exists else None,
        'full_analysis': full_analysis,
        'full_analysis_status': fa_status,
    }


def _start_summary_thread(arxiv_id, abstract, model):
    def worker():
        summary = generate_summary(abstract, model)
        if summary and not summary.startswith('总结生成失败'):
            db.update_paper(arxiv_id, summary=summary, summary_model=model, status='completed')
        else:
            db.update_paper(arxiv_id, status='failed')
    threading.Thread(target=worker, daemon=True).start()


def _start_full_analysis_thread(arxiv_id, paper_data, model):
    threading.Thread(
        target=run_full_analysis,
        args=(arxiv_id, paper_data, model),
        daemon=True,
    ).start()


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.route('/')
def index():
    return render_template('index.html')


@app.route('/api/process', methods=['POST'])
def process_paper():
    data = request.get_json()
    arxiv_url = data.get('url')
    enable_ai = data.get('enable_ai', True)
    enable_full_analysis = data.get('enable_full_analysis', False)
    model = os.environ.get('DEFAULT_MODEL', 'deepseek-chat')
    fa_model = os.environ.get('FULL_ANALYSIS_MODEL', 'qwen-long')

    if not arxiv_url:
        return jsonify({'error': '请输入arXiv链接'}), 400

    arxiv_id = utils.extract_arxiv_id(arxiv_url)
    if not arxiv_id:
        return jsonify({'error': '无法提取arXiv ID，请检查链接格式'}), 400

    if db.get_paper(arxiv_id):
        return jsonify({'message': '论文已存在', 'arxiv_id': arxiv_id, 'status': 'existing'})

    paper_data = download_paper(arxiv_id)
    if not paper_data:
        return jsonify({'error': '下载论文失败'}), 500

    init_fa_status = 'processing' if enable_full_analysis else 'none'

    if enable_ai:
        db.save_paper(paper_data, status='processing', full_analysis_status=init_fa_status)
        _start_summary_thread(arxiv_id, paper_data['abstract'], model)
    else:
        db.save_paper(paper_data, status='downloaded', full_analysis_status=init_fa_status)

    if enable_full_analysis:
        _start_full_analysis_thread(arxiv_id, paper_data, fa_model)

    return jsonify({
        'message': '论文下载成功，正在生成总结...' if enable_ai else '论文下载成功（未启用AI总结）',
        'arxiv_id': arxiv_id,
        'title': paper_data['title'],
        'model': model if enable_ai else None,
        'status': 'processing' if enable_ai else 'downloaded',
        'full_analysis_status': init_fa_status,
    })


@app.route('/api/status/<arxiv_id>')
def get_status(arxiv_id):
    paper = db.get_paper(arxiv_id)
    if not paper:
        return jsonify({'error': '论文不存在'}), 404
    return jsonify(_enrich_paper(paper))


@app.route('/api/history')
def get_history():
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 50, type=int)
    rows, total = db.get_history(page=page, per_page=per_page)

    papers = []
    for r in rows:
        _, md_path, md_exists = _pdf_info(r.get('pdf_path'))
        papers.append({
            **r,
            'md_exists': md_exists,
            'md_file_path': md_path if md_exists else None,
        })

    return jsonify({'papers': papers, 'total': total})


@app.route('/api/paper/<arxiv_id>')
def get_paper_detail(arxiv_id):
    paper = db.get_paper(arxiv_id)
    if not paper:
        return jsonify({'error': '论文不存在'}), 404
    return jsonify(_enrich_paper(paper))


@app.route('/api/paper/<arxiv_id>', methods=['DELETE'])
def delete_paper(arxiv_id):
    pdf_path = db.remove_paper(arxiv_id)
    if pdf_path is None:
        return jsonify({'error': '论文不存在'}), 404
    for path in (pdf_path, utils.get_md_path(pdf_path)):
        if path and os.path.exists(path):
            try:
                os.remove(path)
            except Exception as e:
                print(f'删除文件失败: {path} - {e}')
    return jsonify({'message': '删除成功', 'arxiv_id': arxiv_id})


@app.route('/api/download/<arxiv_id>')
def download_pdf(arxiv_id):
    paper = db.get_paper(arxiv_id)
    if not paper:
        return jsonify({'error': '论文不存在'}), 404

    pdf_path = paper.get('pdf_path')
    if pdf_path and os.path.exists(pdf_path):
        year = utils.extract_year(paper.get('version_history', ''), arxiv_id)
        filename = f"{year}_{utils.clean_filename(paper.get('title', arxiv_id))}.pdf"
        return send_file(
            pdf_path,
            as_attachment=True,
            download_name=filename,
            mimetype='application/pdf',
        )
    # Fallback: old filename format
    old = os.path.join(UPLOAD_FOLDER, f'{arxiv_id}.pdf')
    if os.path.exists(old):
        return send_file(old, as_attachment=True)
    return jsonify({'error': '文件不存在'}), 404


@app.route('/api/download_analysis/<arxiv_id>')
def download_analysis(arxiv_id):
    paper = db.get_paper(arxiv_id)
    if not paper or not paper.get('full_analysis'):
        return jsonify({'error': '全文分析不存在'}), 404

    pdf_path = paper.get('pdf_path')
    md_path = utils.get_md_path(pdf_path)
    filename = os.path.basename(md_path) if md_path else f'{arxiv_id}.md'

    return Response(
        paper['full_analysis'],
        mimetype='text/markdown; charset=utf-8',
        headers={
            'Content-Disposition': f"attachment; filename*=UTF-8''{quote(filename)}",
        },
    )


@app.route('/api/continue_ai/<arxiv_id>', methods=['POST'])
def continue_ai_summary(arxiv_id):
    paper = db.get_paper(arxiv_id)
    if not paper:
        return jsonify({'error': '论文不存在'}), 404

    model = os.environ.get('DEFAULT_MODEL', 'deepseek-chat')
    db.update_paper(arxiv_id, status='processing')
    _start_summary_thread(arxiv_id, paper['abstract'], model)

    return jsonify({'message': '开始生成AI总结...', 'arxiv_id': arxiv_id, 'status': 'processing'})


@app.route('/api/full_analysis/<arxiv_id>', methods=['POST'])
def start_full_analysis(arxiv_id):
    paper = db.get_paper(arxiv_id)
    if not paper:
        return jsonify({'error': '论文不存在'}), 404

    fa_model = os.environ.get('FULL_ANALYSIS_MODEL', 'qwen-long')
    db.update_paper(arxiv_id, full_analysis_status='processing')
    _start_full_analysis_thread(arxiv_id, paper, fa_model)

    return jsonify({'message': '开始全文分析...', 'arxiv_id': arxiv_id, 'full_analysis_status': 'processing'})


@app.route('/api/reset_analysis/<arxiv_id>', methods=['POST'])
def reset_analysis(arxiv_id):
    data = request.get_json() or {}
    reset_type = data.get('type', 'all')

    paper = db.get_paper(arxiv_id)
    if not paper:
        return jsonify({'error': '论文不存在'}), 404

    if reset_type in ('all', 'summary'):
        db.update_paper(arxiv_id, summary=None, summary_model=None, status='downloaded')

    if reset_type in ('all', 'full_analysis'):
        db.update_paper(arxiv_id, full_analysis=None, full_analysis_status='none')
        md_path = utils.get_md_path(paper.get('pdf_path'))
        if md_path and os.path.exists(md_path):
            try:
                os.remove(md_path)
            except Exception as e:
                print(f'删除 md 文件失败: {e}')

    return jsonify({'message': '分析状态已重置', 'arxiv_id': arxiv_id, 'reset_type': reset_type})


@app.route('/api/redownload/<arxiv_id>', methods=['POST'])
def redownload_paper(arxiv_id):
    paper = db.get_paper(arxiv_id)
    if not paper:
        return jsonify({'error': '论文不存在'}), 404

    old_pdf = paper.get('pdf_path')
    for path in (old_pdf, utils.get_md_path(old_pdf)):
        if path and os.path.exists(path):
            try:
                os.remove(path)
            except Exception as e:
                return jsonify({'error': f'删除旧文件失败: {e}'}), 500

    new_data = download_paper(arxiv_id, force_redownload=True)
    if not new_data:
        return jsonify({'error': '重新下载论文失败'}), 500

    db.update_paper(arxiv_id, pdf_path=new_data['pdf_path'])
    return jsonify({
        'message': '论文重新下载成功',
        'arxiv_id': arxiv_id,
        'pdf_path': new_data['pdf_path'],
        'pdf_exists': True,
    })


@app.route('/api/upload_pdf/<arxiv_id>', methods=['POST'])
def upload_pdf(arxiv_id):
    paper = db.get_paper(arxiv_id)
    if not paper:
        return jsonify({'error': '论文不存在，请先添加论文信息'}), 404

    if 'pdf_file' not in request.files:
        return jsonify({'error': '请选择 PDF 文件'}), 400
    f = request.files['pdf_file']
    if not f.filename or not f.filename.lower().endswith('.pdf'):
        return jsonify({'error': '只支持 PDF 文件'}), 400

    year = utils.extract_year(paper.get('version_history', ''), arxiv_id)
    filename = os.path.basename(
        f"{year}_{utils.clean_filename(paper.get('title', arxiv_id))}.pdf"
    )
    filepath = os.path.join(UPLOAD_FOLDER, filename)

    old_pdf = paper.get('pdf_path')
    if old_pdf and os.path.exists(old_pdf) and old_pdf != filepath:
        for path in (old_pdf, utils.get_md_path(old_pdf)):
            if path and os.path.exists(path):
                try:
                    os.remove(path)
                except Exception:
                    pass

    f.save(filepath)
    is_valid, error_msg = utils.verify_pdf(filepath)
    if not is_valid:
        os.remove(filepath)
        return jsonify({'error': f'PDF 文件验证失败: {error_msg}'}), 400

    db.update_paper(arxiv_id, pdf_path=filepath)
    return jsonify({'message': 'PDF 上传成功', 'arxiv_id': arxiv_id, 'pdf_path': filepath, 'pdf_exists': True})


@app.route('/api/check_pdf/<arxiv_id>')
def check_pdf(arxiv_id):
    paper = db.get_paper(arxiv_id)
    if not paper or not paper.get('pdf_path'):
        return jsonify({'exists': False, 'valid': False, 'error': '无 PDF 路径'})

    pdf_path = paper['pdf_path']
    if not os.path.exists(pdf_path):
        return jsonify({'exists': False, 'valid': False, 'error': 'PDF 文件不存在'})

    is_valid, error_msg = utils.verify_pdf(pdf_path)
    return jsonify({'exists': True, 'valid': is_valid, 'error': error_msg, 'pdf_path': pdf_path})


if __name__ == '__main__':
    port = int(os.environ.get('FLASK_PORT', 5000))
    app.run(debug=True, host='0.0.0.0', port=port)
