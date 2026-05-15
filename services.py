import os
import time
import traceback
from pathlib import Path

import arxiv
import openai

from prompts import (
    SYSTEM_PROMPT_SUMMARY,
    SYSTEM_PROMPT_FULL_ANALYSIS,
    get_summary_prompt,
    FULL_ANALYSIS_PROMPT,
)
from utils import clean_filename, verify_pdf, save_analysis_to_md
import db

UPLOAD_FOLDER = 'data/pdfs'


def download_paper(arxiv_id, force_redownload=False):
    max_retries = 4
    retry_delays = [10, 30, 60, 120]

    paper = None
    for attempt in range(max_retries):
        try:
            paper = next(arxiv.Search(id_list=[arxiv_id]).results())
            break
        except arxiv.HTTPError as e:
            if e.status == 429 and attempt < max_retries - 1:
                wait = retry_delays[attempt]
                print(f'arxiv API 限速 (429)，{wait}s 后重试（第 {attempt + 1}/{max_retries - 1} 次）...')
                time.sleep(wait)
            else:
                print(f'下载论文失败: {e}\n{traceback.format_exc()}')
                return None
        except StopIteration:
            print(f'下载论文失败: 未找到 arxiv_id={arxiv_id}')
            return None
        except Exception as e:
            print(f'下载论文失败: {e}\n{traceback.format_exc()}')
            return None

    if paper is None:
        print(f'下载论文失败: 多次重试后仍然 429，arxiv_id={arxiv_id}')
        return None

    try:
        published_year = paper.published.year if hasattr(paper, 'published') else 'unknown'
        version_history = ''
        if hasattr(paper, 'published'):
            pub_str = paper.published.strftime('%d %b %Y')
            if hasattr(paper, 'updated') and paper.published != paper.updated:
                version_history = f'Published {pub_str}, revised {paper.updated.strftime("%d %b %Y")}'
            else:
                version_history = f'Published {pub_str}'

        filename = os.path.basename(f'{published_year}_{clean_filename(paper.title)}.pdf')
        filepath = os.path.join(UPLOAD_FOLDER, filename)

        need_download = force_redownload or not os.path.exists(filepath)
        if not need_download:
            is_valid, _ = verify_pdf(filepath)
            if not is_valid:
                need_download = True
                _backup_corrupted(filepath)

        if need_download:
            # Add retry mechanism for PDF download to handle 429 errors and incomplete downloads
            pdf_download_retries = 4
            pdf_retry_delays = [10, 30, 60, 120]
            pdf_downloaded = False
            
            for pdf_attempt in range(pdf_download_retries):
                try:
                    paper.download_pdf(dirpath=UPLOAD_FOLDER, filename=filename)
                    pdf_downloaded = True
                    break
                except Exception as e:
                    error_str = str(e)
                    # Check if it's a 429 error or incomplete download
                    if ('429' in error_str or 'retrieval incomplete' in error_str or 'ContentTooShort' in error_str) and pdf_attempt < pdf_download_retries - 1:
                        wait = pdf_retry_delays[pdf_attempt]
                        error_type = '限速 (429)' if '429' in error_str else '下载不完整'
                        print(f'PDF 下载{error_type}，{wait}s 后重试（第 {pdf_attempt + 1}/{pdf_download_retries - 1} 次）...')
                        time.sleep(wait)
                    else:
                        print(f'PDF 下载失败: {e}\n{traceback.format_exc()}')
                        return None
            
            if not pdf_downloaded:
                print(f'PDF 下载失败: 多次重试后仍然失败，arxiv_id={arxiv_id}')
                return None
                
            is_valid, error_msg = verify_pdf(filepath)
            if not is_valid:
                print(f'下载后验证失败: {error_msg}')
                _backup_corrupted(filepath)
                return None

        return {
            'title': paper.title,
            'authors': ', '.join(str(a) for a in paper.authors),
            'abstract': paper.summary,
            'url': paper.entry_id,
            'pdf_path': filepath,
            'arxiv_id': arxiv_id,
            'year': published_year,
            'version_history': version_history,
        }
    except Exception as e:
        print(f'下载论文失败: {e}\n{traceback.format_exc()}')
        return None


def _backup_corrupted(filepath):
    try:
        os.rename(filepath, filepath + '.corrupted')
        print(f'已备份损坏文件到: {filepath}.corrupted')
    except Exception:
        pass


def cleanup_corrupted_files():
    removed = []
    for f in Path(UPLOAD_FOLDER).glob('*.corrupted'):
        try:
            f.unlink()
            removed.append(f.name)
        except Exception as e:
            print(f'删除损坏文件失败 {f.name}: {e}')
    if removed:
        print(f'启动清理：已删除 {len(removed)} 个损坏文件: {", ".join(removed)}')
    return removed


def generate_summary(text, model='gpt-3.5-turbo'):
    api_key = os.environ.get('OPENAI_API_KEY')
    base_url = os.environ.get('OPENAI_BASE_URL', 'https://api.openai.com/v1')
    if not api_key:
        return '请配置 OPENAI_API_KEY 环境变量'

    proxy_vars = ['HTTP_PROXY', 'HTTPS_PROXY', 'http_proxy', 'https_proxy']
    saved = {v: os.environ.pop(v) for v in proxy_vars if v in os.environ}
    try:
        client = openai.OpenAI(
            api_key=api_key,
            base_url=base_url if base_url != 'https://api.openai.com/v1' else None,
        )
        resp = client.chat.completions.create(
            model=model,
            messages=[
                {'role': 'system', 'content': SYSTEM_PROMPT_SUMMARY},
                {'role': 'user', 'content': get_summary_prompt(text)},
            ],
            temperature=0.3,
            max_tokens=1000,
        )
        return resp.choices[0].message.content
    except Exception as e:
        print(f'生成总结失败: {e}\n{traceback.format_exc()}')
        return f'总结生成失败: {e}'
    finally:
        os.environ.update(saved)


def generate_full_analysis(pdf_path, model='qwen-long'):
    MAX_MB = 50
    api_key = os.environ.get('DASHSCOPE_API_KEY') or os.environ.get('OPENAI_API_KEY')
    base_url = os.environ.get('DASHSCOPE_BASE_URL', 'https://dashscope.aliyuncs.com/compatible-mode/v1')
    if not api_key:
        return '请配置 DASHSCOPE_API_KEY 或 OPENAI_API_KEY 环境变量'

    file_path = Path(pdf_path)
    if not file_path.exists():
        return f'PDF 文件不存在：{pdf_path}'
    size_mb = file_path.stat().st_size / (1024 * 1024)
    if size_mb > MAX_MB:
        return f'全文分析失败: PDF 文件过大 ({size_mb:.1f}MB)，超过 {MAX_MB}MB 限制，无法处理。'

    try:
        client = openai.OpenAI(api_key=api_key, base_url=base_url)
        with open(file_path, 'rb') as f:
            file_obj = client.files.create(
                file=(file_path.name, f, 'application/pdf'),
                purpose='file-extract',
            )
        file_id = file_obj.id
        print(f'文件已上传，file_id={file_id}，大小={size_mb:.1f}MB，等待处理...')

        for waited in range(0, 300, 10):
            try:
                info = client.files.retrieve(file_id)
                status = getattr(info, 'status', None)
                print(f'  文件状态: {status}（已等待 {waited}s）')
                if status == 'processed':
                    break
                if status in ('error', 'deleted', 'failed'):
                    _safe_delete_file(client, file_id)
                    return f'全文分析失败: 文件处理出错，状态={status}。该 PDF 可能有加密、损坏或格式不支持。'
            except Exception as poll_e:
                print(f'  轮询文件状态失败: {poll_e}')
            time.sleep(10)
        else:
            _safe_delete_file(client, file_id)
            return '全文分析失败: 文件处理超时（300s），PDF 可能过大或格式异常。'

        completion = client.chat.completions.create(
            model=model,
            messages=[
                {'role': 'system', 'content': SYSTEM_PROMPT_FULL_ANALYSIS},
                {'role': 'system', 'content': f'fileid://{file_id}'},
                {'role': 'user', 'content': FULL_ANALYSIS_PROMPT},
            ],
            stream=True,
            stream_options={'include_usage': True},
        )
        content = ''.join(
            chunk.choices[0].delta.content
            for chunk in completion
            if chunk.choices and chunk.choices[0].delta.content
        )
        _safe_delete_file(client, file_id)
        return content or '全文分析生成失败，返回内容为空'

    except openai.APIError as e:
        err = str(e)
        print(f'全文分析失败 (APIError): {err}\n{traceback.format_exc()}')
        if 'encrypted or corrupted' in err:
            return '全文分析失败: 该 PDF 文件已加密或内容无法解析。请确认 PDF 可正常打开且未设置内容保护，或尝试重新下载。'
        return f'全文分析失败: {err}'
    except Exception as e:
        print(f'全文分析失败: {e}\n{traceback.format_exc()}')
        return f'全文分析失败: {e}'


def _safe_delete_file(client, file_id):
    try:
        client.files.delete(file_id)
    except Exception:
        pass


def run_full_analysis(arxiv_id, paper_data, model):
    """Execute full analysis in a background thread and update DB."""
    try:
        analysis = generate_full_analysis(paper_data['pdf_path'], model)
        if analysis and not analysis.startswith('全文分析失败'):
            save_analysis_to_md(paper_data['pdf_path'], analysis)
            db.update_paper(arxiv_id, full_analysis=analysis, full_analysis_status='completed')
            print(f'全文分析完成: {arxiv_id}')
        else:
            db.update_paper(arxiv_id, full_analysis=analysis, full_analysis_status='failed')
            print(f'全文分析失败: {arxiv_id} - {analysis}')
    except Exception as e:
        msg = f'全文分析异常: {e}'
        print(f'{msg}\n{traceback.format_exc()}')
        db.update_paper(arxiv_id, full_analysis=msg, full_analysis_status='failed')
