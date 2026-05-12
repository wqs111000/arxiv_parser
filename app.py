from flask import Flask, render_template, request, jsonify, send_file, Response
from dotenv import load_dotenv
import os
import re
import sqlite3
import arxiv
import openai
import threading
from pathlib import Path

# 加载 .env 文件
load_dotenv()

# 导入 prompts 模块
from prompts import (
    SYSTEM_PROMPT_SUMMARY,
    SYSTEM_PROMPT_FULL_ANALYSIS,
    get_summary_prompt,
    FULL_ANALYSIS_PROMPT
)

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', os.urandom(24).hex())
app.config['UPLOAD_FOLDER'] = 'data/pdfs'
app.config['DATABASE'] = 'data/arxiv_history.db'
app.config['MAX_CONTENT_LENGTH'] = 50 * 1024 * 1024  # 50MB 最大上传文件大小

# 确保必要的目录存在
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

# 初始化数据库
def init_db():
    conn = sqlite3.connect(app.config['DATABASE'])
    c = conn.cursor()
    c.execute('''
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
    # 兼容旧数据库，若字段不存在则添加
    try:
        c.execute('ALTER TABLE papers ADD COLUMN full_analysis TEXT')
    except sqlite3.OperationalError as e:
        if 'duplicate column name' not in str(e).lower():
            raise  # 重新抛出非预期错误
    try:
        c.execute("ALTER TABLE papers ADD COLUMN full_analysis_status TEXT DEFAULT 'none'")
    except sqlite3.OperationalError as e:
        if 'duplicate column name' not in str(e).lower():
            raise  # 重新抛出非预期错误
    conn.commit()
    conn.close()

init_db()

def extract_arxiv_id(url):
    """从arXiv链接中提取论文ID"""
    patterns = [
        r'arxiv\.org/abs/(\d+\.\d+)',
        r'arxiv\.org/pdf/(\d+\.\d+)',
        r'arxiv\.org/abs/([a-z\-]+/\d+)',
        r'arxiv\.org/pdf/([a-z\-]+/\d+)'
    ]
    
    for pattern in patterns:
        match = re.search(pattern, url)
        if match:
            return match.group(1)
    return None

def clean_filename(title):
    """清理文件名中的非法字符"""
    # 定义非法字符（Windows和Linux/Mac都不允许的字符）
    illegal_chars = r'[<>:"/\\|?*]'
    
    # 替换非法字符为下划线
    cleaned = re.sub(illegal_chars, '_', title)
    
    # 移除前后空格和点（避免隐藏文件）
    cleaned = cleaned.strip()
    
    # 限制长度（避免文件系统限制）
    if len(cleaned) > 200:
        cleaned = cleaned[:200]
    
    return cleaned

def _verify_pdf_integrity(filepath):
    """验证 PDF 文件完整性，返回 (是否有效, 错误信息)"""
    try:
        with open(filepath, 'rb') as f:
            header = f.read(8)
            # PDF 文件必须以 %PDF- 开头
            if not header.startswith(b'%PDF-'):
                return False, f"文件头不是 PDF 格式: {header[:8]}"
            
            # 检查文件大小
            f.seek(0, 2)  # 跳到文件末尾
            file_size = f.tell()
            if file_size < 1024:  # 小于 1KB 肯定有问题
                return False, f"文件过小 ({file_size} bytes)，可能下载不完整"
            
            # 检查文件尾部是否有 %%EOF
            f.seek(max(0, file_size - 1024))
            tail = f.read(1024)
            if b'%%EOF' not in tail:
                return False, "PDF 文件尾部缺少 %%EOF 标记，可能下载不完整"
        
        return True, None
    except Exception as e:
        return False, f"验证 PDF 失败: {e}"


def download_paper(arxiv_id, force_redownload=False):
    """下载arXiv论文，遇到 429 限速时自动退避重试，支持完整性检查和重新下载"""
    import time as _time
    import random

    max_retries = 4
    retry_delays = [10, 30, 60, 120]  # 每次重试的等待秒数

    for attempt in range(max_retries):
        try:
            # 使用新的 Client API（替代已弃用的 Search.results）
            client = arxiv.Client()
            search = arxiv.Search(id_list=[arxiv_id])
            results = client.results(search)
            paper = next(results)
            break  # 成功则跳出重试循环
        except arxiv.HTTPError as e:
            if e.status == 429 and attempt < max_retries - 1:
                # 添加随机抖动以避免多个客户端同时重试
                wait = retry_delays[attempt] + random.uniform(0, 5)
                print(f"arxiv API 限速 (429)，{wait:.1f}s 后重试（第 {attempt + 1}/{max_retries - 1} 次）...")
                _time.sleep(wait)
                continue
            print(f"下载论文失败: {e}")
            import traceback
            print(f"详细错误: {traceback.format_exc()}")
            return None
        except StopIteration:
            print(f"下载论文失败: 未找到 arxiv_id={arxiv_id}")
            return None
        except Exception as e:
            print(f"下载论文失败: {e}")
            import traceback
            print(f"详细错误: {traceback.format_exc()}")
            return None
    else:
        print(f"下载论文失败: 多次重试后仍然 429，arxiv_id={arxiv_id}")
        return None

    try:
        # 提取发表年份
        published_year = paper.published.year if hasattr(paper, 'published') else 'unknown'
        
        # 生成版本记录信息
        version_history = ""
        if hasattr(paper, 'published'):
            published_str = paper.published.strftime('%d %b %Y')
            
            # 检查是否有更新日期
            if hasattr(paper, 'updated') and paper.published != paper.updated:
                updated_str = paper.updated.strftime('%d %b %Y')
                version_history = f"Published {published_str}, revised {updated_str}"
            else:
                version_history = f"Published {published_str}"
        
        # 清理论文标题，生成合法的文件名
        clean_title = clean_filename(paper.title)
        
        # 生成新文件名格式：年份_论文标题.pdf
        filename = f"{published_year}_{clean_title}.pdf"
        
        # 确保文件名不包含路径遍历
        filename = os.path.basename(filename)
        
        filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        
        # 检查是否需要下载
        need_download = force_redownload or not os.path.exists(filepath)
        
        # 如果文件存在，验证完整性
        if not need_download and os.path.exists(filepath):
            is_valid, error_msg = _verify_pdf_integrity(filepath)
            if not is_valid:
                print(f"PDF 验证失败: {error_msg}，将重新下载: {filename}")
                need_download = True
                # 备份损坏的文件
                try:
                    backup_path = filepath + '.corrupted'
                    os.rename(filepath, backup_path)
                    print(f"已备份损坏文件到: {backup_path}")
                except Exception:
                    pass
        
        # 下载PDF（如果需要）
        if need_download:
            paper.download_pdf(dirpath=app.config['UPLOAD_FOLDER'], filename=filename)
            
            # 下载后验证完整性
            is_valid, error_msg = _verify_pdf_integrity(filepath)
            if not is_valid:
                print(f"下载后验证失败: {error_msg}")
                # 备份损坏的文件，让用户可以手动处理
                try:
                    backup_path = filepath + '.corrupted'
                    os.rename(filepath, backup_path)
                    print(f"已备份损坏文件到: {backup_path}，请使用重新下载或手动上传功能")
                except Exception:
                    pass
                return None
        
        return {
            'title': paper.title,
            'authors': ', '.join([str(author) for author in paper.authors]),
            'abstract': paper.summary,
            'url': paper.entry_id,
            'pdf_path': filepath,
            'arxiv_id': arxiv_id,
            'year': published_year,
            'version_history': version_history
        }
    except Exception as e:
        print(f"下载论文失败: {e}")
        import traceback
        print(f"详细错误: {traceback.format_exc()}")
        return None

def generate_summary(text, model="gpt-3.5-turbo"):
    """调用大模型生成论文总结"""
    try:
        # 从环境变量获取API配置
        api_key = os.environ.get("OPENAI_API_KEY")
        base_url = os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1")
        
        if not api_key:
            app.logger.error("OPENAI_API_KEY 未配置")
            return "API 配置错误，请联系管理员"
        
        # 基本格式验证
        if not api_key.startswith(('sk-', 'dashscope-')):
            app.logger.warning(f"无效的 API Key 格式: {api_key[:8]}...")
            return "API Key 格式无效"
        
        # 使用 prompts 模块生成 prompt
        prompt = get_summary_prompt(text)
        
        # 导入 OpenAI 并创建客户端 - 使用 httpx 禁用代理以避免线程安全问题
        import openai
        import httpx
        
        # 创建不使用代理的 HTTP 客户端
        http_client = httpx.Client(proxies={})
        
        try:
            # 创建客户端
            client = openai.OpenAI(
                api_key=api_key,
                base_url=base_url if base_url != "https://api.openai.com/v1" else None,
                http_client=http_client
            )
            
            response = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT_SUMMARY},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.3,
                max_tokens=1000
            )
            return response.choices[0].message.content
            
        finally:
            # 关闭 HTTP 客户端
            http_client.close()
            
    except Exception as e:
        print(f"生成总结失败: {e}")
        import traceback
        print(f"详细错误: {traceback.format_exc()}")
        return f"总结生成失败: {str(e)}"

def generate_full_analysis(pdf_path, model="qwen-long"):
    """使用 qwen-long 对完整 PDF 进行全文分析，返回 markdown 字符串"""
    import time
    import traceback as _tb

    # 文件大小限制：qwen-long 支持最大 100MB，但超过 30MB 容易出问题
    MAX_FILE_SIZE_MB = 50

    try:
        api_key = os.environ.get("DASHSCOPE_API_KEY") or os.environ.get("OPENAI_API_KEY")
        base_url = os.environ.get("DASHSCOPE_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1")

        if not api_key:
            return "请配置 DASHSCOPE_API_KEY 或 OPENAI_API_KEY 环境变量"

        import openai as _openai
        client = _openai.OpenAI(api_key=api_key, base_url=base_url)

        file_path = Path(pdf_path)
        if not file_path.exists():
            return f"PDF 文件不存在：{pdf_path}"

        # 检查文件大小
        file_size_mb = file_path.stat().st_size / (1024 * 1024)
        if file_size_mb > MAX_FILE_SIZE_MB:
            return f"全文分析失败: PDF 文件过大 ({file_size_mb:.1f}MB)，超过 {MAX_FILE_SIZE_MB}MB 限制，无法处理。"

        # 上传文件 —— 必须显式指定文件名和 MIME 类型，否则 DashScope 无法识别格式
        with open(file_path, "rb") as f:
            file_object = client.files.create(
                file=(file_path.name, f, "application/pdf"),
                purpose="file-extract"
            )

        file_id = file_object.id
        print(f"文件已上传，file_id={file_id}，大小={file_size_mb:.1f}MB，等待文件处理完成...")

        # 轮询等待文件处理完成（最多等待 300 秒，大文件需要更长时间）
        max_wait = 300
        poll_interval = 10
        waited = 0
        while waited < max_wait:
            try:
                file_info = client.files.retrieve(file_id)
                file_status = getattr(file_info, 'status', None)
                print(f"  文件状态: {file_status}（已等待 {waited}s）")
                if file_status == 'processed':
                    break
                elif file_status in ('error', 'deleted', 'failed'):
                    try:
                        client.files.delete(file_id)
                    except Exception:
                        pass
                    return f"全文分析失败: 文件处理出错，状态={file_status}。该 PDF 可能有加密、损坏或格式不支持。"
            except Exception as poll_e:
                print(f"  轮询文件状态失败: {poll_e}")
            time.sleep(poll_interval)
            waited += poll_interval
        else:
            # 超时，清理并返回错误
            try:
                client.files.delete(file_id)
            except Exception:
                pass
            return f"全文分析失败: 文件处理超时（{max_wait}s），PDF 可能过大或格式异常。"

        # 调用 qwen-long 进行全文分析
        completion = client.chat.completions.create(
            model=model,
            messages=[
                {'role': 'system', 'content': SYSTEM_PROMPT_FULL_ANALYSIS},
                {'role': 'system', 'content': f'fileid://{file_id}'},
                {
                    'role': 'user',
                    'content': FULL_ANALYSIS_PROMPT
                }
            ],
            stream=True,
            stream_options={"include_usage": True}
        )

        full_content = ""
        for chunk in completion:
            if chunk.choices and chunk.choices[0].delta.content:
                full_content += chunk.choices[0].delta.content

        # 清理：删除已上传的文件（避免占用配额）
        try:
            client.files.delete(file_id)
        except Exception:
            pass

        return full_content if full_content else "全文分析生成失败，返回内容为空"

    except _openai.APIError as e:
        err_msg = str(e)
        print(f"全文分析失败 (APIError): {err_msg}\n{_tb.format_exc()}")
        if "encrypted or corrupted" in err_msg:
            return "全文分析失败: 该 PDF 文件已加密或内容无法解析。请确认 PDF 可正常打开且未设置内容保护，或尝试重新下载。"
        return f"全文分析失败: {err_msg}"
    except Exception as e:
        print(f"全文分析失败: {e}\n{_tb.format_exc()}")
        return f"全文分析失败: {str(e)}"


def save_paper_to_db(paper_data, summary=None, model=None, status=None,
                     full_analysis=None, full_analysis_status=None):
    """保存论文信息到数据库"""
    conn = sqlite3.connect(app.config['DATABASE'])
    c = conn.cursor()
    
    # 确定状态
    if status is None:
        if summary:
            status = 'completed'
        else:
            status = 'downloaded'
    
    # 确定全文分析状态
    if full_analysis_status is None:
        full_analysis_status = 'none'
    
    try:
        c.execute('''
            INSERT OR REPLACE INTO papers 
            (arxiv_id, title, authors, abstract, url, pdf_path, version_history, summary, summary_model, status,
             full_analysis, full_analysis_status)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            paper_data['arxiv_id'],
            paper_data['title'],
            paper_data['authors'],
            paper_data['abstract'],
            paper_data['url'],
            paper_data['pdf_path'],
            paper_data.get('version_history', ''),
            summary,
            model,
            status,
            full_analysis,
            full_analysis_status
        ))
        conn.commit()
    except Exception as e:
        print(f"保存到数据库失败: {e}")
        import traceback
        print(f"详细错误: {traceback.format_exc()}")
    finally:
        conn.close()

def get_paper_history():
    """获取论文历史记录"""
    conn = sqlite3.connect(app.config['DATABASE'])
    c = conn.cursor()

    c.execute('''
        SELECT id, arxiv_id, title, version_history, created_at, status, summary,
               full_analysis_status, pdf_path
        FROM papers
        ORDER BY created_at DESC
    ''')

    papers = []
    for row in c.fetchall():
        pdf_path = row[8]
        md_path = get_md_path_from_pdf(pdf_path)
        md_exists = os.path.exists(md_path) if md_path else False

        papers.append({
            'id': row[0],
            'arxiv_id': row[1],
            'title': row[2],
            'version_history': row[3],
            'created_at': row[4],
            'status': row[5],
            'summary': row[6],
            'full_analysis_status': row[7] or 'none',
            'md_file_path': md_path if md_exists else None,
            'md_exists': md_exists
        })

    conn.close()
    return papers

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/process', methods=['POST'])
def process_paper():
    data = request.get_json()
    arxiv_url = data.get('url')
    enable_ai = data.get('enable_ai', True)  # 是否启用AI总结，默认为True
    enable_full_analysis = data.get('enable_full_analysis', False)  # 是否启用全文分析
    
    # 从环境变量获取模型配置
    model = os.environ.get("DEFAULT_MODEL", "deepseek-chat")
    full_analysis_model = os.environ.get("FULL_ANALYSIS_MODEL", "qwen-long")
    
    if not arxiv_url:
        return jsonify({'error': '请输入arXiv链接'}), 400
    
    arxiv_id = extract_arxiv_id(arxiv_url)
    if not arxiv_id:
        return jsonify({'error': '无法提取arXiv ID，请检查链接格式'}), 400
    
    # 检查是否已处理过
    conn = sqlite3.connect(app.config['DATABASE'])
    c = conn.cursor()
    c.execute('SELECT * FROM papers WHERE arxiv_id = ?', (arxiv_id,))
    existing = c.fetchone()
    conn.close()
    
    if existing:
        return jsonify({
            'message': '论文已存在',
            'arxiv_id': arxiv_id,
            'status': 'existing'
        })
    
    # 下载论文
    paper_data = download_paper(arxiv_id)
    if not paper_data:
        return jsonify({'error': '下载论文失败'}), 500
    
    if enable_ai:
        # 确定初始全文分析状态
        init_fa_status = 'processing' if enable_full_analysis else 'none'
        # 保存基本信息，状态设为 processing
        save_paper_to_db(paper_data, status='processing', full_analysis_status=init_fa_status)
        
        # 异步生成摘要总结（+ 可选全文分析）
        def async_generate_summary():
            try:
                summary = generate_summary(paper_data['abstract'], model)
                if summary and not summary.startswith("总结生成失败"):
                    save_paper_to_db(paper_data, summary, model, status='completed',
                                     full_analysis_status=init_fa_status)
                else:
                    print(f"总结生成失败: {summary}")
                    save_paper_to_db(paper_data, summary=None, model=None, status='failed',
                                     full_analysis_status=init_fa_status)
            except Exception as e:
                print(f"异步生成总结异常: {e}")
                import traceback
                print(f"详细错误: {traceback.format_exc()}")
                save_paper_to_db(paper_data, summary=None, model=None, status='failed',
                                 full_analysis_status=init_fa_status)
        
        thread = threading.Thread(target=async_generate_summary)
        thread.start()
        
        # 如果启用全文分析，单独异步处理
        if enable_full_analysis:
            def async_full_analysis():
                _run_full_analysis(arxiv_id, paper_data, full_analysis_model)
            fa_thread = threading.Thread(target=async_full_analysis)
            fa_thread.start()
        
        return jsonify({
            'message': '论文下载成功，正在生成总结...',
            'arxiv_id': arxiv_id,
            'title': paper_data['title'],
            'model': model,
            'status': 'processing',
            'full_analysis_status': init_fa_status
        })
    else:
        # 未启用AI总结
        init_fa_status = 'processing' if enable_full_analysis else 'none'
        save_paper_to_db(paper_data, status='downloaded', full_analysis_status=init_fa_status)
        
        if enable_full_analysis:
            def async_full_analysis():
                _run_full_analysis(arxiv_id, paper_data, full_analysis_model)
            fa_thread = threading.Thread(target=async_full_analysis)
            fa_thread.start()
        
        return jsonify({
            'message': '论文下载成功（未启用AI总结）',
            'arxiv_id': arxiv_id,
            'title': paper_data['title'],
            'status': 'downloaded',
            'full_analysis_status': init_fa_status
        })

@app.route('/api/status/<arxiv_id>')
def get_status(arxiv_id):
    """获取论文处理状态"""
    conn = sqlite3.connect(app.config['DATABASE'])
    c = conn.cursor()
    c.execute('''SELECT status, summary, title, authors, abstract, summary_model, version_history,
                        full_analysis_status, full_analysis, pdf_path
                 FROM papers WHERE arxiv_id = ?''', (arxiv_id,))
    result = c.fetchone()
    conn.close()

    if not result:
        return jsonify({'error': '论文不存在'}), 404

    pdf_path = result[9]
    md_path = get_md_path_from_pdf(pdf_path)
    md_exists = os.path.exists(md_path) if md_path else False

    # 如果数据库中没有全文分析，但本地有 md 文件，则加载
    full_analysis = result[8]
    full_analysis_status = result[7] or 'none'

    if not full_analysis and md_exists:
        full_analysis = load_analysis_from_md(pdf_path)
        if full_analysis:
            full_analysis_status = 'completed'
            # 可选：同步到数据库
            try:
                conn2 = sqlite3.connect(app.config['DATABASE'])
                c2 = conn2.cursor()
                c2.execute('UPDATE papers SET full_analysis=?, full_analysis_status=? WHERE arxiv_id=?',
                           (full_analysis, 'completed', arxiv_id))
                conn2.commit()
                conn2.close()
            except Exception as e:
                print(f"同步 md 到数据库失败: {e}")

    return jsonify({
        'arxiv_id': arxiv_id,
        'status': result[0],
        'summary': result[1],
        'title': result[2],
        'authors': result[3],
        'abstract': result[4],
        'summary_model': result[5],
        'version_history': result[6],
        'full_analysis_status': full_analysis_status,
        'full_analysis': full_analysis,
        'md_file_path': md_path if md_exists else None,
        'md_exists': md_exists
    })

@app.route('/api/history')
def get_history():
    """获取历史记录，支持分页"""
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 20, type=int)
    offset = (page - 1) * per_page
    
    conn = sqlite3.connect(app.config['DATABASE'])
    c = conn.cursor()
    
    # 获取总数
    c.execute('SELECT COUNT(*) FROM papers')
    total = c.fetchone()[0]
    
    # 获取分页数据
    c.execute('''
        SELECT id, arxiv_id, title, version_history, created_at, status, summary,
               full_analysis_status, pdf_path
        FROM papers
        ORDER BY created_at DESC
        LIMIT ? OFFSET ?
    ''', (per_page, offset))

    papers = []
    for row in c.fetchall():
        pdf_path = row[8]
        md_path = get_md_path_from_pdf(pdf_path)
        md_exists = os.path.exists(md_path) if md_path else False

        papers.append({
            'id': row[0],
            'arxiv_id': row[1],
            'title': row[2],
            'version_history': row[3],
            'created_at': row[4],
            'status': row[5],
            'summary': row[6],
            'full_analysis_status': row[7] or 'none',
            'md_file_path': md_path if md_exists else None,
            'md_exists': md_exists
        })

    conn.close()
    
    return jsonify({
        'papers': papers,
        'total': total,
        'page': page,
        'per_page': per_page,
        'total_pages': (total + per_page - 1) // per_page
    })

@app.route('/api/download/<arxiv_id>')
def download_pdf(arxiv_id):
    """下载PDF文件，使用规范化的文件名（年份_标题.pdf）"""
    conn = sqlite3.connect(app.config['DATABASE'])
    c = conn.cursor()
    c.execute('SELECT pdf_path, title, version_history FROM papers WHERE arxiv_id = ?', (arxiv_id,))
    result = c.fetchone()
    conn.close()
    
    if result and result[0] and os.path.exists(result[0]):
        pdf_path = result[0]
        title = result[1] or arxiv_id
        
        # 生成规范化的下载文件名：年份_标题.pdf
        clean_title = clean_filename(title)
        # 从 version_history 提取发表年份（格式：Published 01 Jan 2017, revised ...）
        version_history = result[2] or ''
        year = 'unknown'
        year_match = re.search(r'Published\s+\d+\s+\w+\s+(\d{4})', version_history)
        if year_match:
            year = year_match.group(1)
        else:
            # 如果 version_history 为空，尝试从 arXiv ID 提取年份
            # arXiv ID 格式如 1706.03762 -> 2017, 1810.04805 -> 2018
            arxiv_year_match = re.search(r'(\d{2})\d{2}\.\d+', arxiv_id)
            if arxiv_year_match:
                year_short = int(arxiv_year_match.group(1))
                # arXiv 年份：00-24 是 2000-2024，25-99 是 1990-1999
                if year_short >= 90:
                    year = str(1900 + year_short)
                else:
                    year = str(2000 + year_short)
        download_filename = f"{year}_{clean_title}.pdf"
        
        # 使用 quote 对文件名进行 URL 编码，支持中文
        from urllib.parse import quote
        encoded_filename = quote(download_filename, safe='')  # 编码所有特殊字符
        
        return send_file(
            pdf_path,
            as_attachment=True,
            download_name=download_filename,
            mimetype='application/pdf'
        )
    else:
        # 如果找不到，尝试旧文件名格式
        old_filename = f"{arxiv_id}.pdf"
        old_filepath = os.path.join(app.config['UPLOAD_FOLDER'], old_filename)
        if os.path.exists(old_filepath):
            return send_file(old_filepath, as_attachment=True)
        return jsonify({'error': '文件不存在'}), 404

@app.route('/api/paper/<arxiv_id>')
def get_paper_detail(arxiv_id):
    """获取论文详细信息"""
    conn = sqlite3.connect(app.config['DATABASE'])
    c = conn.cursor()
    c.execute('''
        SELECT arxiv_id, title, authors, abstract, url, pdf_path, version_history,
               summary, summary_model, created_at, status, full_analysis, full_analysis_status
        FROM papers
        WHERE arxiv_id = ?
    ''', (arxiv_id,))
    result = c.fetchone()
    conn.close()

    if not result:
        return jsonify({'error': '论文不存在'}), 404

    pdf_path = result[5]
    md_path = get_md_path_from_pdf(pdf_path)
    md_exists = os.path.exists(md_path) if md_path else False

    # 如果数据库中没有全文分析，但本地有 md 文件，则加载
    full_analysis = result[11]
    full_analysis_status = result[12] or 'none'

    if not full_analysis and md_exists:
        full_analysis = load_analysis_from_md(pdf_path)
        if full_analysis:
            full_analysis_status = 'completed'
            # 同步到数据库
            try:
                conn2 = sqlite3.connect(app.config['DATABASE'])
                c2 = conn2.cursor()
                c2.execute('UPDATE papers SET full_analysis=?, full_analysis_status=? WHERE arxiv_id=?',
                           (full_analysis, 'completed', arxiv_id))
                conn2.commit()
                conn2.close()
            except Exception as e:
                print(f"同步 md 到数据库失败: {e}")

    return jsonify({
        'arxiv_id': result[0],
        'title': result[1],
        'authors': result[2],
        'abstract': result[3],
        'url': result[4],
        'pdf_path': result[5],
        'version_history': result[6],
        'summary': result[7],
        'summary_model': result[8],
        'created_at': result[9],
        'status': result[10],
        'full_analysis': full_analysis,
        'full_analysis_status': full_analysis_status,
        'md_file_path': md_path if md_exists else None,
        'md_exists': md_exists
    })

def get_md_path_from_pdf(pdf_path):
    """根据 PDF 路径生成对应的 Markdown 文件路径"""
    if not pdf_path:
        return None
    base = os.path.splitext(pdf_path)[0]
    return base + '.md'


def save_analysis_to_md(pdf_path, analysis_content):
    """将全文分析保存到 PDF 同目录同名 .md 文件"""
    try:
        md_path = get_md_path_from_pdf(pdf_path)
        if md_path:
            with open(md_path, 'w', encoding='utf-8') as f:
                f.write(analysis_content)
            return md_path
    except Exception as e:
        print(f"保存 Markdown 文件失败: {e}")
    return None


def load_analysis_from_md(pdf_path):
    """从本地 Markdown 文件加载全文分析内容"""
    try:
        md_path = get_md_path_from_pdf(pdf_path)
        if md_path and os.path.exists(md_path):
            with open(md_path, 'r', encoding='utf-8') as f:
                return f.read()
    except Exception as e:
        print(f"读取 Markdown 文件失败: {e}")
    return None


def _run_full_analysis(arxiv_id, paper_data, model):
    """在后台执行全文分析并更新数据库（不改变 summary 状态）"""
    def _update_status(status, analysis=None):
        """辅助函数：更新数据库状态"""
        try:
            conn = sqlite3.connect(app.config['DATABASE'])
            c = conn.cursor()
            if analysis is not None:
                c.execute(
                    'UPDATE papers SET full_analysis=?, full_analysis_status=? WHERE arxiv_id=?',
                    (analysis, status, arxiv_id)
                )
            else:
                c.execute(
                    'UPDATE papers SET full_analysis_status=? WHERE arxiv_id=?',
                    (status, arxiv_id)
                )
            conn.commit()
            conn.close()
        except Exception as db_e:
            print(f"更新数据库状态失败: {db_e}")

    try:
        analysis = generate_full_analysis(paper_data['pdf_path'], model)
        
        # 判断是否成功
        if analysis and not analysis.startswith("全文分析失败"):
            # 保存到本地 Markdown 文件
            save_analysis_to_md(paper_data['pdf_path'], analysis)
            _update_status('completed', analysis)
            print(f"全文分析完成: {arxiv_id}")
        else:
            _update_status('failed', analysis)
            print(f"全文分析失败: {arxiv_id} - {analysis}")
    except Exception as e:
        import traceback
        error_msg = f"全文分析异常: {e}"
        print(f"{error_msg}\n{traceback.format_exc()}")
        _update_status('failed', error_msg)


@app.route('/api/full_analysis/<arxiv_id>', methods=['POST'])
def start_full_analysis(arxiv_id):
    """手动触发全文分析"""
    try:
        full_analysis_model = os.environ.get("FULL_ANALYSIS_MODEL", "qwen-long")

        conn = sqlite3.connect(app.config['DATABASE'])
        c = conn.cursor()
        c.execute('SELECT title, authors, abstract, url, pdf_path, version_history FROM papers WHERE arxiv_id = ?',
                  (arxiv_id,))
        row = c.fetchone()
        conn.close()

        if not row:
            return jsonify({'error': '论文不存在'}), 404

        paper_data = {
            'arxiv_id': arxiv_id,
            'title': row[0],
            'authors': row[1],
            'abstract': row[2],
            'url': row[3],
            'pdf_path': row[4],
            'version_history': row[5],
        }

        # 更新状态为 processing
        conn = sqlite3.connect(app.config['DATABASE'])
        c = conn.cursor()
        c.execute('UPDATE papers SET full_analysis_status=? WHERE arxiv_id=?', ('processing', arxiv_id))
        conn.commit()
        conn.close()

        def async_fa():
            _run_full_analysis(arxiv_id, paper_data, full_analysis_model)

        threading.Thread(target=async_fa).start()

        return jsonify({'message': '开始全文分析...', 'arxiv_id': arxiv_id, 'full_analysis_status': 'processing'})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/download_analysis/<arxiv_id>')
def download_analysis(arxiv_id):
    """下载全文分析 Markdown，使用与本地保存相同的文件名"""
    conn = sqlite3.connect(app.config['DATABASE'])
    c = conn.cursor()
    c.execute('SELECT full_analysis, pdf_path, title FROM papers WHERE arxiv_id = ?', (arxiv_id,))
    result = c.fetchone()
    conn.close()

    if not result or not result[0]:
        return jsonify({'error': '全文分析不存在'}), 404

    full_analysis, pdf_path, title = result
    
    # 使用与本地保存相同的文件名逻辑：与 PDF 同名，只改后缀为 .md
    if pdf_path:
        md_path = get_md_path_from_pdf(pdf_path)
        if md_path:
            filename = os.path.basename(md_path)
        else:
            filename = f"{arxiv_id}.md"
    else:
        # 没有 pdf_path 时，使用 arxiv_id 作为文件名
        filename = f"{arxiv_id}.md"
    
    # 使用 quote 对文件名进行 URL 编码，支持中文
    from urllib.parse import quote
    encoded_filename = quote(filename)

    return Response(
        full_analysis,
        mimetype='text/markdown; charset=utf-8',
        headers={
            'Content-Disposition': f"attachment; filename*=UTF-8''{encoded_filename}",
            'Content-Type': 'text/markdown; charset=utf-8'
        }
    )


@app.route('/api/continue_ai/<arxiv_id>', methods=['POST'])
def continue_ai_summary(arxiv_id):
    """继续完成AI总结"""
    try:
        # 从环境变量获取模型配置
        model = os.environ.get("DEFAULT_MODEL", "deepseek-chat")
        
        # 获取论文信息
        conn = sqlite3.connect(app.config['DATABASE'])
        c = conn.cursor()
        c.execute('SELECT title, authors, abstract, url, pdf_path, version_history, full_analysis_status FROM papers WHERE arxiv_id = ?', (arxiv_id,))
        paper_data = c.fetchone()
        conn.close()
        
        if not paper_data:
            return jsonify({'error': '论文不存在'}), 404
        
        existing_fa_status = paper_data[6] or 'none'
        
        # 构建完整的论文数据
        paper_info = {
            'arxiv_id': arxiv_id,
            'title': paper_data[0],
            'authors': paper_data[1],
            'abstract': paper_data[2],
            'url': paper_data[3],
            'pdf_path': paper_data[4],
            'version_history': paper_data[5],
        }
        
        # 先更新状态为 processing（保留 full_analysis_status）
        conn = sqlite3.connect(app.config['DATABASE'])
        c = conn.cursor()
        c.execute('UPDATE papers SET status=? WHERE arxiv_id=?', ('processing', arxiv_id))
        conn.commit()
        conn.close()
        
        # 异步生成总结
        def async_generate_summary():
            try:
                summary = generate_summary(paper_info['abstract'], model)
                if summary and not summary.startswith("总结生成失败"):
                    conn2 = sqlite3.connect(app.config['DATABASE'])
                    c2 = conn2.cursor()
                    c2.execute('UPDATE papers SET summary=?, summary_model=?, status=? WHERE arxiv_id=?',
                               (summary, model, 'completed', arxiv_id))
                    conn2.commit()
                    conn2.close()
                else:
                    print(f"总结生成失败: {summary}")
                    conn2 = sqlite3.connect(app.config['DATABASE'])
                    c2 = conn2.cursor()
                    c2.execute('UPDATE papers SET status=? WHERE arxiv_id=?', ('failed', arxiv_id))
                    conn2.commit()
                    conn2.close()
            except Exception as e:
                print(f"异步生成总结异常: {e}")
                import traceback
                print(f"详细错误: {traceback.format_exc()}")
                conn2 = sqlite3.connect(app.config['DATABASE'])
                c2 = conn2.cursor()
                c2.execute('UPDATE papers SET status=? WHERE arxiv_id=?', ('failed', arxiv_id))
                conn2.commit()
                conn2.close()
        
        thread = threading.Thread(target=async_generate_summary)
        thread.start()
        
        return jsonify({
            'message': '开始生成AI总结...',
            'arxiv_id': arxiv_id,
            'status': 'processing'
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/reset_analysis/<arxiv_id>', methods=['POST'])
def reset_analysis(arxiv_id):
    """重置分析状态，允许重新进行 AI 总结和全文分析"""
    try:
        data = request.get_json() or {}
        reset_type = data.get('type', 'all')  # 'all', 'summary', 'full_analysis'
        
        conn = sqlite3.connect(app.config['DATABASE'])
        c = conn.cursor()
        
        # 获取当前论文信息
        c.execute('SELECT pdf_path FROM papers WHERE arxiv_id = ?', (arxiv_id,))
        result = c.fetchone()
        if not result:
            conn.close()
            return jsonify({'error': '论文不存在'}), 404
        
        pdf_path = result[0]
        
        if reset_type == 'all' or reset_type == 'summary':
            # 重置 AI 总结
            c.execute('UPDATE papers SET summary=?, summary_model=?, status=? WHERE arxiv_id=?',
                      (None, None, 'downloaded', arxiv_id))
        
        if reset_type == 'all' or reset_type == 'full_analysis':
            # 重置全文分析
            c.execute('UPDATE papers SET full_analysis=?, full_analysis_status=? WHERE arxiv_id=?',
                      (None, 'none', arxiv_id))
            # 删除本地 md 文件
            if pdf_path:
                md_path = get_md_path_from_pdf(pdf_path)
                if md_path and os.path.exists(md_path):
                    try:
                        os.remove(md_path)
                    except Exception as e:
                        print(f"删除 md 文件失败: {e}")
        
        conn.commit()
        conn.close()
        
        return jsonify({
            'message': '分析状态已重置',
            'arxiv_id': arxiv_id,
            'reset_type': reset_type
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/redownload/<arxiv_id>', methods=['POST'])
def redownload_paper(arxiv_id):
    """重新下载论文 PDF（用于修复损坏的文件）"""
    try:
        conn = sqlite3.connect(app.config['DATABASE'])
        c = conn.cursor()
        c.execute('SELECT title, authors, abstract, url, pdf_path, version_history FROM papers WHERE arxiv_id = ?',
                  (arxiv_id,))
        row = c.fetchone()
        conn.close()

        if not row:
            return jsonify({'error': '论文不存在'}), 404

        pdf_path = row[4]
        
        # 如果 PDF 存在，先删除
        if pdf_path and os.path.exists(pdf_path):
            try:
                os.remove(pdf_path)
                print(f"已删除旧 PDF: {pdf_path}")
            except Exception as e:
                return jsonify({'error': f'删除旧 PDF 失败: {e}'}), 500
        
        # 同时删除关联的 Markdown 文件
        if pdf_path:
            md_path = get_md_path_from_pdf(pdf_path)
            if md_path and os.path.exists(md_path):
                try:
                    os.remove(md_path)
                    print(f"已删除旧 Markdown: {md_path}")
                except Exception as e:
                    print(f"删除旧 Markdown 失败: {e}")

        # 重新下载
        paper_data = download_paper(arxiv_id, force_redownload=True)
        if not paper_data:
            return jsonify({'error': '重新下载论文失败'}), 500

        # 更新数据库中的 pdf_path（文件名可能改变）
        conn = sqlite3.connect(app.config['DATABASE'])
        c = conn.cursor()
        c.execute('UPDATE papers SET pdf_path=? WHERE arxiv_id=?',
                  (paper_data['pdf_path'], arxiv_id))
        conn.commit()
        conn.close()

        return jsonify({
            'message': '论文重新下载成功',
            'arxiv_id': arxiv_id,
            'pdf_path': paper_data['pdf_path'],
            'pdf_exists': True
        })
    except Exception as e:
        import traceback
        print(f"重新下载失败: {e}\n{traceback.format_exc()}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/upload_pdf/<arxiv_id>', methods=['POST'])
def upload_pdf(arxiv_id):
    """用户手动上传 PDF 文件"""
    try:
        conn = sqlite3.connect(app.config['DATABASE'])
        c = conn.cursor()
        c.execute('SELECT title, pdf_path, version_history FROM papers WHERE arxiv_id = ?', (arxiv_id,))
        row = c.fetchone()
        conn.close()

        if not row:
            return jsonify({'error': '论文不存在，请先添加论文信息'}), 404

        if 'pdf_file' not in request.files:
            return jsonify({'error': '请选择 PDF 文件'}), 400

        file = request.files['pdf_file']
        if file.filename == '':
            return jsonify({'error': '请选择 PDF 文件'}), 400

        if not file.filename.lower().endswith('.pdf'):
            return jsonify({'error': '只支持 PDF 文件'}), 400

        # 生成文件名：年份_标题.pdf
        title = row[0] or arxiv_id
        clean_title = clean_filename(title)
        
        # 从 version_history 提取发表年份（格式：Published 01 Jan 2017, revised ...）
        version_history = row[2] or ''
        year = 'unknown'
        year_match = re.search(r'Published\s+\d+\s+\w+\s+(\d{4})', version_history)
        if year_match:
            year = year_match.group(1)
        else:
            # 如果 version_history 为空，尝试从 arXiv ID 提取年份
            # arXiv ID 格式如 1706.03762 -> 2017, 1810.04805 -> 2018
            arxiv_year_match = re.search(r'(\d{2})\d{2}\.\d+', arxiv_id)
            if arxiv_year_match:
                year_short = int(arxiv_year_match.group(1))
                # arXiv 年份：00-24 是 2000-2024，25-99 是 1990-1999
                if year_short >= 90:
                    year = str(1900 + year_short)
                else:
                    year = str(2000 + year_short)
        
        filename = f"{year}_{clean_title}.pdf"
        filename = os.path.basename(filename)
        filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)

        # 如果已存在旧文件，先删除
        old_pdf_path = row[1]
        if old_pdf_path and os.path.exists(old_pdf_path) and old_pdf_path != filepath:
            try:
                os.remove(old_pdf_path)
                # 同时删除关联的 Markdown
                md_path = get_md_path_from_pdf(old_pdf_path)
                if md_path and os.path.exists(md_path):
                    os.remove(md_path)
            except Exception as e:
                print(f"删除旧文件失败: {e}")

        # 保存上传的文件
        file.save(filepath)

        # 验证 PDF 完整性
        is_valid, error_msg = _verify_pdf_integrity(filepath)
        if not is_valid:
            os.remove(filepath)
            return jsonify({'error': f'PDF 文件验证失败: {error_msg}'}), 400

        # 更新数据库
        conn = sqlite3.connect(app.config['DATABASE'])
        c = conn.cursor()
        c.execute('UPDATE papers SET pdf_path=? WHERE arxiv_id=?', (filepath, arxiv_id))
        conn.commit()
        conn.close()

        return jsonify({
            'message': 'PDF 上传成功',
            'arxiv_id': arxiv_id,
            'pdf_path': filepath,
            'pdf_exists': True
        })
    except Exception as e:
        import traceback
        print(f"上传 PDF 失败: {e}\n{traceback.format_exc()}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/check_pdf/<arxiv_id>')
def check_pdf(arxiv_id):
    """检查 PDF 文件是否存在且有效"""
    try:
        conn = sqlite3.connect(app.config['DATABASE'])
        c = conn.cursor()
        c.execute('SELECT pdf_path FROM papers WHERE arxiv_id = ?', (arxiv_id,))
        row = c.fetchone()
        conn.close()

        if not row or not row[0]:
            return jsonify({'exists': False, 'valid': False, 'error': '无 PDF 路径'})

        pdf_path = row[0]
        if not os.path.exists(pdf_path):
            return jsonify({'exists': False, 'valid': False, 'error': 'PDF 文件不存在'})

        is_valid, error_msg = _verify_pdf_integrity(pdf_path)
        return jsonify({
            'exists': True,
            'valid': is_valid,
            'error': error_msg if not is_valid else None,
            'pdf_path': pdf_path
        })
    except Exception as e:
        return jsonify({'exists': False, 'valid': False, 'error': str(e)}), 500


if __name__ == '__main__':
    flask_port = int(os.environ.get("FLASK_PORT", 5000))
    app.run(debug=True, host='0.0.0.0', port=flask_port)