from flask import Flask, render_template, request, jsonify, send_file
from dotenv import load_dotenv
import os
import re
import sqlite3
import arxiv
import openai
import threading

# 加载 .env 文件
load_dotenv()

app = Flask(__name__)
app.config['SECRET_KEY'] = 'arxiv-parser-secret-key'
app.config['UPLOAD_FOLDER'] = 'data/pdfs'
app.config['DATABASE'] = 'data/arxiv_history.db'

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
            status TEXT DEFAULT 'pending'
        )
    ''')
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

def download_paper(arxiv_id):
    """下载arXiv论文"""
    try:
        search = arxiv.Search(id_list=[arxiv_id])
        paper = next(search.results())
        
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
        
        # 下载PDF
        if not os.path.exists(filepath):
            paper.download_pdf(dirpath=app.config['UPLOAD_FOLDER'], filename=filename)
        
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
            return "请配置 OPENAI_API_KEY 环境变量"
        
        prompt = f"""请对下面的学术论文进行结构化总结，总字数 300–500 字，语言简洁专业。
严格按下面 5 个标题输出，每个标题一段，不要列表、不要符号、不要多余解释。
TL;DR：
【一句话概括论文核心贡献】
动机：
【说明要解决的问题、现有方法不足、研究意义】
方法：
【简述模型、算法、实验设计、技术方案】
结果：
【关键指标、对比效果、实验结论】
总结：
【论文价值、局限、未来方向】
论文内容：
{text}
"""
        
        # 导入 OpenAI 并创建客户端 - 移除代理参数
        import openai
        
        # 检查是否存在代理环境变量并临时移除
        proxy_vars = ['HTTP_PROXY', 'HTTPS_PROXY', 'http_proxy', 'https_proxy']
        old_proxy_values = {}
        
        for var in proxy_vars:
            if var in os.environ:
                old_proxy_values[var] = os.environ[var]
                del os.environ[var]
        
        try:
            # 创建客户端 - 使用更简洁的方式避免代理问题
            client = openai.OpenAI(api_key=api_key, base_url=base_url if base_url != "https://api.openai.com/v1" else None)
            
            response = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": "You are a professional paper analyst.You should avoid unnecessarily long replies and instead provide concise, detailed, and precise answers using correct terminology.。"},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.3,
                max_tokens=1000
            )
            return response.choices[0].message.content
            
        finally:
            # 恢复代理环境变量
            for var, value in old_proxy_values.items():
                os.environ[var] = value
            
    except Exception as e:
        print(f"生成总结失败: {e}")
        import traceback
        print(f"详细错误: {traceback.format_exc()}")
        return f"总结生成失败: {str(e)}"

def save_paper_to_db(paper_data, summary=None, model=None, status=None):
    """保存论文信息到数据库"""
    conn = sqlite3.connect(app.config['DATABASE'])
    c = conn.cursor()
    
    # 确定状态
    if status is None:
        if summary:
            status = 'completed'
        else:
            status = 'downloaded'
    
    try:
        c.execute('''
            INSERT OR REPLACE INTO papers 
            (arxiv_id, title, authors, abstract, url, pdf_path, version_history, summary, summary_model, status)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
            status
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
        SELECT id, arxiv_id, title, version_history, created_at, status, summary 
        FROM papers 
        ORDER BY created_at DESC
    ''')
    
    papers = []
    for row in c.fetchall():
        papers.append({
            'id': row[0],
            'arxiv_id': row[1],
            'title': row[2],
            'version_history': row[3],
            'created_at': row[4],
            'status': row[5],
            'summary': row[6]
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
    
    # 从环境变量获取模型配置
    model = os.environ.get("DEFAULT_MODEL", "deepseek-chat")
    
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
        # 保存基本信息，状态设为 processing
        save_paper_to_db(paper_data, status='processing')
        
        # 异步生成总结
        def async_generate_summary():
            try:
                summary = generate_summary(paper_data['abstract'], model)
                if summary and not summary.startswith("总结生成失败"):
                    save_paper_to_db(paper_data, summary, model, status='completed')
                else:
                    print(f"总结生成失败: {summary}")
                    # 标记为失败，避免前端一直停留在 processing
                    save_paper_to_db(paper_data, summary=None, model=None, status='failed')
            except Exception as e:
                print(f"异步生成总结异常: {e}")
                import traceback
                print(f"详细错误: {traceback.format_exc()}")
                # 异常时同样标记为失败
                save_paper_to_db(paper_data, summary=None, model=None, status='failed')
        
        thread = threading.Thread(target=async_generate_summary)
        thread.start()
        
        return jsonify({
            'message': '论文下载成功，正在生成总结...',
            'arxiv_id': arxiv_id,
            'title': paper_data['title'],
            'model': model,
            'status': 'processing'
        })
    else:
        # 只下载不生成总结
        save_paper_to_db(paper_data, status='downloaded')
        
        return jsonify({
            'message': '论文下载成功（未启用AI总结）',
            'arxiv_id': arxiv_id,
            'title': paper_data['title'],
            'status': 'downloaded'
        })

@app.route('/api/status/<arxiv_id>')
def get_status(arxiv_id):
    """获取论文处理状态"""
    conn = sqlite3.connect(app.config['DATABASE'])
    c = conn.cursor()
    c.execute('SELECT status, summary, title, authors, abstract, summary_model, version_history FROM papers WHERE arxiv_id = ?', (arxiv_id,))
    result = c.fetchone()
    conn.close()
    
    if not result:
        return jsonify({'error': '论文不存在'}), 404
    
    return jsonify({
        'arxiv_id': arxiv_id,
        'status': result[0],
        'summary': result[1],
        'title': result[2],
        'authors': result[3],
        'abstract': result[4],
        'summary_model': result[5],
        'version_history': result[6]
    })

@app.route('/api/history')
def get_history():
    """获取历史记录"""
    papers = get_paper_history()
    return jsonify(papers)

@app.route('/api/download/<arxiv_id>')
def download_pdf(arxiv_id):
    """下载PDF文件"""
    conn = sqlite3.connect(app.config['DATABASE'])
    c = conn.cursor()
    c.execute('SELECT pdf_path FROM papers WHERE arxiv_id = ?', (arxiv_id,))
    result = c.fetchone()
    conn.close()
    
    if result and result[0] and os.path.exists(result[0]):
        return send_file(result[0], as_attachment=True)
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
               summary, summary_model, created_at, status 
        FROM papers 
        WHERE arxiv_id = ?
    ''', (arxiv_id,))
    result = c.fetchone()
    conn.close()
    
    if not result:
        return jsonify({'error': '论文不存在'}), 404
    
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
        'status': result[10]
    })

@app.route('/api/continue_ai/<arxiv_id>', methods=['POST'])
def continue_ai_summary(arxiv_id):
    """继续完成AI总结"""
    try:
        # 从环境变量获取模型配置
        model = os.environ.get("DEFAULT_MODEL", "deepseek-chat")
        
        # 获取论文信息
        conn = sqlite3.connect(app.config['DATABASE'])
        c = conn.cursor()
        c.execute('SELECT title, authors, abstract, url, pdf_path, version_history FROM papers WHERE arxiv_id = ?', (arxiv_id,))
        paper_data = c.fetchone()
        conn.close()
        
        if not paper_data:
            return jsonify({'error': '论文不存在'}), 404
        
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
        
        # 先更新状态为 processing
        save_paper_to_db(paper_info, status='processing')
        
        # 异步生成总结
        def async_generate_summary():
            try:
                summary = generate_summary(paper_info['abstract'], model)
                if summary and not summary.startswith("总结生成失败"):
                    save_paper_to_db(paper_info, summary, model, status='completed')
                else:
                    print(f"总结生成失败: {summary}")
                    # 标记为失败，避免前端一直停留在 processing
                    save_paper_to_db(paper_info, summary=None, model=None, status='failed')
            except Exception as e:
                print(f"异步生成总结异常: {e}")
                import traceback
                print(f"详细错误: {traceback.format_exc()}")
                # 异常时同样标记为失败
                save_paper_to_db(paper_info, summary=None, model=None, status='failed')
        
        thread = threading.Thread(target=async_generate_summary)
        thread.start()
        
        return jsonify({
            'message': '开始生成AI总结...',
            'arxiv_id': arxiv_id,
            'status': 'processing'
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    flask_port = int(os.environ.get("FLASK_PORT", 5000))
    app.run(debug=True, host='0.0.0.0', port=flask_port)