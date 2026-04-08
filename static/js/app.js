// 全局变量
let currentArxivId = null;
let statusCheckInterval = null;

// 初始化
document.addEventListener('DOMContentLoaded', function() {
    loadHistorySide();
    
    // 表单提交
    document.getElementById('paperForm').addEventListener('submit', handleFormSubmit);
    
    // 回车键提交
    document.getElementById('arxivUrl').addEventListener('keypress', function(e) {
        if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault();
            handleFormSubmit(e);
        }
    });
});

// 加载历史记录（侧边栏）
async function loadHistorySide() {
    const historyList = document.getElementById('historyListSide');

    historyList.innerHTML = '<div class="text-center py-3 text-muted"><div class="spinner-border spinner-border-sm text-primary" role="status"><span class="visually-hidden">加载中...</span></div><p class="mt-2 mb-0">加载历史记录...</p></div>';

    try {
        const response = await fetch('/api/history');
        const papers = await response.json();

        if (papers.length === 0) {
            historyList.innerHTML = '<div class="text-center py-4 text-muted">暂无历史记录</div>';
            return;
        }

        historyList.innerHTML = papers.map(paper => {
            // 判断状态：有摘要、有全文分析(md文件)
            const hasSummary = !!paper.summary;
            const hasMd = paper.md_exists;
            const faStatus = paper.full_analysis_status || 'none';

            // 状态图标
            let statusIcon = '';
            if (hasSummary && hasMd) {
                statusIcon = '<i class="fas fa-check-double text-success" title="AI总结和全文分析已完成"></i>';
            } else if (hasSummary) {
                statusIcon = '<i class="fas fa-check-circle text-primary" title="AI总结已完成"></i>';
            } else if (hasMd) {
                statusIcon = '<i class="fas fa-file-alt text-info" title="全文分析文件已存在"></i>';
            } else {
                statusIcon = '<i class="fas fa-hourglass-half text-warning" title="待处理"></i>';
            }

            return `
            <div class="card mb-2 history-item ${paper.status}" onclick="loadPaperFromHistory('${paper.arxiv_id}')" style="cursor: pointer;">
                <div class="card-body p-3">
                    <div class="d-flex justify-content-between align-items-start">
                        <div class="flex-grow-1">
                            <h6 class="mb-1 fs-6">${escapeHtml(paper.title)}</h6>
                            ${paper.version_history ? `<p class="text-muted small mb-1">
                                <i class="fas fa-history me-1"></i>${paper.version_history.substring(0, 50)}${paper.version_history.length > 50 ? '...' : ''}
                            </p>` : ''}
                            <p class="text-muted small mb-0">
                                <i class="fas fa-clock me-1"></i>${formatDate(paper.created_at)}
                            </p>
                            <div class="mt-1">
                                ${hasSummary ? '<span class="badge bg-primary me-1" style="font-size:0.6em;">总结</span>' : ''}
                                ${hasMd ? '<span class="badge bg-success me-1" style="font-size:0.6em;">全文</span>' : ''}
                                ${(!hasSummary && !hasMd) ? '<span class="badge bg-secondary" style="font-size:0.6em;">仅下载</span>' : ''}
                            </div>
                        </div>
                        <div class="ms-2">
                            ${statusIcon}
                        </div>
                    </div>
                </div>
            </div>
        `}).join('');
    } catch (error) {
        historyList.innerHTML = '<div class="text-center py-4 text-danger">加载失败</div>';
    }
}

// 处理表单提交
async function handleFormSubmit(e) {
    e.preventDefault();
    
    const url = document.getElementById('arxivUrl').value.trim();
    const enableAI = document.getElementById('enableAISummary').checked;
    const enableFullAnalysis = document.getElementById('enableFullAnalysis').checked;
    const submitBtn = document.getElementById('submitBtn');
    
    if (!url) {
        showToast('请输入arXiv链接', 'warning');
        return;
    }
    
    // 禁用按钮
    submitBtn.disabled = true;
    submitBtn.innerHTML = '<i class="fas fa-spinner fa-spin me-2"></i>处理中...';
    
    try {
        const response = await fetch('/api/process', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({ url, enable_ai: enableAI, enable_full_analysis: enableFullAnalysis })
        });
        
        const data = await response.json();
        
        if (response.ok) {
            currentArxivId = data.arxiv_id;
            showToast(data.message, 'success');
            
            if (data.status === 'existing') {
                loadPaperData(currentArxivId);
            } else if (data.status === 'downloaded' && (data.full_analysis_status || 'none') === 'none') {
                // 未启用AI总结且未启用全文分析，直接加载论文数据
                loadPaperData(currentArxivId);
            } else {
                // 开始检查状态（processing）
                startStatusChecking();
            }
        } else {
            showToast(data.error || '处理失败', 'error');
        }
    } catch (error) {
        showToast('网络错误，请重试', 'error');
    } finally {
        submitBtn.disabled = false;
        submitBtn.innerHTML = '<i class="fas fa-magic me-2"></i>开始处理';
    }
}

// 开始检查状态
function startStatusChecking() {
    // 立即检查一次
    checkPaperStatus();
    
    // 每3秒检查一次
    statusCheckInterval = setInterval(checkPaperStatus, 3000);
    
    // 5分钟后停止自动检查（全文分析可能耗时较长）
    setTimeout(() => {
        if (statusCheckInterval) {
            clearInterval(statusCheckInterval);
            statusCheckInterval = null;
        }
    }, 300000);
}

// 检查论文状态
async function checkPaperStatus() {
    if (!currentArxivId) return;
    
    try {
        const response = await fetch(`/api/status/${currentArxivId}`);
        const data = await response.json();
        
        if (response.ok) {
            updateResultDisplay(data);
            
            // 摘要和全文分析都完成（或无需等待），才停止轮询
            const summaryDone = data.status === 'completed' || data.status === 'downloaded' || data.status === 'failed';
            const faStatus = data.full_analysis_status || 'none';
            const faDone = faStatus === 'completed' || faStatus === 'failed' || faStatus === 'none';
            
            if (summaryDone && faDone) {
                if (statusCheckInterval) {
                    clearInterval(statusCheckInterval);
                    statusCheckInterval = null;
                }
            }
        }
    } catch (error) {
        console.error('检查状态失败:', error);
    }
}

// 更新结果显示
function updateResultDisplay(data) {
    // 显示结果容器
    document.getElementById('emptyState').style.display = 'none';
    document.getElementById('resultContainer').style.display = 'block';

    // 更新论文信息
    document.getElementById('paperTitle').textContent = data.title || '未知标题';
    document.getElementById('paperAuthors').textContent = data.authors || '未知作者';
    document.getElementById('paperAbstract').textContent = data.abstract || '暂无摘要';

    // 显示版本记录（如果有）
    if (data.version_history) {
        const versionHistory = document.getElementById('versionHistory');
        const versionInfo = document.getElementById('versionInfo');
        versionHistory.style.display = 'block';
        versionInfo.textContent = data.version_history;
    }

    // 显示使用的模型（如果有）
    if (data.summary_model || data.model) {
        const modelInfo = document.getElementById('modelInfo');
        const modelName = document.getElementById('modelName');
        modelInfo.style.display = 'block';
        modelName.textContent = data.summary_model || data.model;
    }

    // 保存当前论文ID用于继续AI总结（如果后端返回了 arxiv_id 就更新，否则保留现有值）
    if (data.arxiv_id) {
        currentArxivId = data.arxiv_id;
    }

    // 更新 PDF 按钮状态
    checkAndUpdatePdfStatus();

    // 更新总结
    const summaryDiv = document.getElementById('paperSummary');
    const statusBadge = document.getElementById('summaryStatus');
    const continueBtn = document.getElementById('continueAISummaryBtn');
    const resetSummaryBtn = document.getElementById('resetSummaryBtn');

    // 检查是否有本地 md 文件（用于判断是否可以补充全文分析）
    const hasLocalMd = data.md_exists;

    if (data.status === 'completed') {
        if (data.summary) {
            summaryDiv.innerHTML = data.summary.replace(/\n/g, '<br>');
            summaryDiv.style.display = 'block';
        } else {
            summaryDiv.innerHTML = '<em>总结生成失败，请重试</em>';
            summaryDiv.style.display = 'block';
        }
        statusBadge.textContent = '已完成';
        statusBadge.className = 'badge bg-success';
        continueBtn.style.display = 'none';
        resetSummaryBtn.style.display = 'inline-block';
    } else if (data.status === 'processing') {
        summaryDiv.innerHTML = `
            <div class="spinner-border spinner-border-sm text-primary" role="status">
                <span class="visually-hidden">加载中...</span>
            </div>
            <span class="ms-2">正在生成总结...</span>
        `;
        summaryDiv.style.display = 'block';
        statusBadge.textContent = '生成中';
        statusBadge.className = 'badge bg-warning';
        continueBtn.style.display = 'none';
        resetSummaryBtn.style.display = 'none';
    } else if (data.status === 'downloaded') {
        summaryDiv.style.display = 'none';
        statusBadge.textContent = '未启用';
        statusBadge.className = 'badge bg-secondary';
        // 始终显示"继续完成 AI 总结"按钮，让用户可以随时启用摘要总结
        continueBtn.style.display = 'inline-block';
        resetSummaryBtn.style.display = 'none';
    } else if (data.status === 'failed') {
        summaryDiv.innerHTML = '<em>AI 总结生成失败，请点击"继续完成 AI 总结"重试</em>';
        summaryDiv.style.display = 'block';
        statusBadge.textContent = '失败';
        statusBadge.className = 'badge bg-danger';
        continueBtn.style.display = 'inline-block';
        resetSummaryBtn.style.display = 'none';
    } else {
        summaryDiv.style.display = 'none';
        statusBadge.textContent = '等待中';
        statusBadge.className = 'badge bg-secondary';
        continueBtn.style.display = 'none';
        resetSummaryBtn.style.display = 'none';
    }

    // 更新全文分析区域
    updateFullAnalysisDisplay(data);
}

// 更新全文分析展示
function updateFullAnalysisDisplay(data) {
    const faStatus = data.full_analysis_status || 'none';
    const faSection = document.getElementById('fullAnalysisSection');
    const faStatusBadge = document.getElementById('fullAnalysisStatus');
    const faContent = document.getElementById('fullAnalysisContent');
    const faLoading = document.getElementById('fullAnalysisLoading');
    const downloadBtn = document.getElementById('downloadAnalysisBtn');
    const startBtn = document.getElementById('startFullAnalysisBtn');
    const resetFullAnalysisBtn = document.getElementById('resetFullAnalysisBtn');

    // 检查本地是否有 md 文件（从本地加载的）
    const hasLocalMd = data.md_exists && data.full_analysis;

    // 始终显示全文分析区域（只要有内容或可以开始分析）
    const canShowSection = faStatus !== 'none' || hasLocalMd || data.pdf_path;

    if (!canShowSection) {
        faSection.style.display = 'none';
        return;
    }

    // 显示全文分析区域
    faSection.style.display = 'block';

    if (faStatus === 'processing') {
        faStatusBadge.textContent = '分析中';
        faStatusBadge.className = 'badge bg-warning';
        faContent.style.display = 'none';
        faLoading.style.display = 'block';
        downloadBtn.style.display = 'none';
        startBtn.style.display = 'none';
        resetFullAnalysisBtn.style.display = 'none';
    } else if (faStatus === 'completed' || hasLocalMd) {
        faStatusBadge.textContent = '已完成';
        faStatusBadge.className = 'badge bg-success';
        faLoading.style.display = 'none';
        downloadBtn.style.display = 'inline-block';
        startBtn.style.display = 'none';
        resetFullAnalysisBtn.style.display = 'inline-block';
        if (data.full_analysis) {
            faContent.innerHTML = renderMarkdown(data.full_analysis);
            faContent.style.display = 'block';
        }
    } else if (faStatus === 'failed') {
        faStatusBadge.textContent = '失败';
        faStatusBadge.className = 'badge bg-danger';
        faLoading.style.display = 'none';
        faContent.innerHTML = '<em class="text-danger">全文分析失败，请重试</em>';
        faContent.style.display = 'block';
        downloadBtn.style.display = 'none';
        startBtn.style.display = 'inline-block';
        resetFullAnalysisBtn.style.display = 'none';
    } else {
        // 未开始状态，显示开始按钮
        faStatusBadge.textContent = '未分析';
        faStatusBadge.className = 'badge bg-secondary';
        faLoading.style.display = 'none';
        resetFullAnalysisBtn.style.display = 'none';
        faContent.style.display = 'none';
        downloadBtn.style.display = 'none';
        startBtn.style.display = 'inline-block';
    }
}

// 渲染 Markdown（支持 LaTeX 公式）
function renderMarkdown(text) {
    if (!text) return '';

    // 先保护代码块中的内容，避免被公式解析干扰
    const codeBlocks = [];
    let protectedText = text.replace(/```[\s\S]*?```/g, (match) => {
        codeBlocks.push(match);
        return `\x00CODE_BLOCK_${codeBlocks.length - 1}\x00`;
    });

    // 保护行内代码
    const inlineCodes = [];
    protectedText = protectedText.replace(/`[^`]+`/g, (match) => {
        inlineCodes.push(match);
        return `\x00INLINE_CODE_${inlineCodes.length - 1}\x00`;
    });

    // 转换 LaTeX 公式为占位符，避免被 marked 解析
    const mathExpressions = [];

    // 保护块级公式 $$...$$
    protectedText = protectedText.replace(/\$\$([\s\S]*?)\$\$/g, (match, formula) => {
        mathExpressions.push({ type: 'block', formula: formula.trim() });
        return `\x00MATH_${mathExpressions.length - 1}\x00`;
    });

    // 保护行内公式 $...$（更宽松的匹配，排除常见货币格式）
    protectedText = protectedText.replace(/\$([^\$\s][^\$]*?)\$/g, (match, formula) => {
        // 排除纯数字（可能是价格）
        if (/^\d+(\.\d{1,2})?$/.test(formula.trim())) {
            return match;
        }
        // 排除常见的货币格式如 $100, $1.99
        if (/^\d+(,\d{3})*(\.\d{1,2})?$/.test(formula.trim())) {
            return match;
        }
        mathExpressions.push({ type: 'inline', formula: formula.trim() });
        return `\x00MATH_${mathExpressions.length - 1}\x00`;
    });

    // 使用 marked 解析 Markdown
    let html = '';
    if (typeof marked !== 'undefined') {
        html = marked.parse(protectedText);
    } else {
        html = protectedText.replace(/\n/g, '<br>');
    }

    // 恢复代码块
    codeBlocks.forEach((code, i) => {
        html = html.replace(`\x00CODE_BLOCK_${i}\x00`, code);
    });

    // 恢复行内代码
    inlineCodes.forEach((code, i) => {
        html = html.replace(`\x00INLINE_CODE_${i}\x00`, code);
    });

    // 恢复并渲染公式
    mathExpressions.forEach((math, i) => {
        let rendered = '';
        try {
            if (typeof katex !== 'undefined') {
                rendered = katex.renderToString(math.formula, {
                    throwOnError: false,
                    displayMode: math.type === 'block'
                });
            } else {
                // KaTeX 未加载，显示原始文本
                rendered = math.type === 'block'
                    ? `<div class="math-block">$$${math.formula}$$</div>`
                    : `<span class="math-inline">$${math.formula}$</span>`;
            }
        } catch (e) {
            // 渲染失败，显示原始文本
            rendered = math.type === 'block'
                ? `<div class="math-block text-danger">$$${math.formula}$$</div>`
                : `<span class="math-inline text-danger">$${math.formula}$</span>`;
        }
        html = html.replace(`\x00MATH_${i}\x00`, rendered);
    });

    return html;
}

// 下载PDF
async function downloadPDF() {
    if (!currentArxivId) {
        showToast('请先处理论文', 'warning');
        return;
    }
    
    // 先检查 PDF 是否存在
    try {
        const response = await fetch(`/api/check_pdf/${currentArxivId}`);
        const data = await response.json();
        
        if (!data.exists || !data.valid) {
            showToast(data.error || 'PDF 文件不存在或已损坏', 'error');
            updatePdfButtonState(false);
            return;
        }
        
        window.open(`/api/download/${currentArxivId}`, '_blank');
    } catch (error) {
        showToast('检查 PDF 状态失败', 'error');
    }
}

// 检查并更新 PDF 状态
async function checkAndUpdatePdfStatus() {
    if (!currentArxivId) return;
    
    try {
        const response = await fetch(`/api/check_pdf/${currentArxivId}`);
        const data = await response.json();
        updatePdfButtonState(data.exists && data.valid);
    } catch (error) {
        console.error('检查 PDF 状态失败:', error);
        updatePdfButtonState(false);
    }
}

// 更新 PDF 按钮状态
function updatePdfButtonState(pdfExists) {
    const downloadBtn = document.getElementById('downloadPdfBtn');
    const redownloadBtn = document.getElementById('redownloadPdfBtn');
    const uploadBtn = document.getElementById('uploadPdfBtn');
    
    // 三个按钮始终显示在按钮组中
    downloadBtn.style.display = 'inline-block';
    redownloadBtn.style.display = 'inline-block';
    uploadBtn.style.display = 'inline-block';
    
    if (pdfExists) {
        // PDF 存在且有效：下载按钮可用，重新下载和上传作为辅助选项
        downloadBtn.disabled = false;
        downloadBtn.classList.remove('btn-outline-secondary');
        downloadBtn.classList.add('btn-outline-primary');
        redownloadBtn.disabled = false;
        uploadBtn.disabled = false;
    } else {
        // PDF 不存在或损坏：下载按钮禁用，提示用户使用重新下载或上传
        downloadBtn.disabled = true;
        downloadBtn.classList.remove('btn-outline-primary');
        downloadBtn.classList.add('btn-outline-secondary');
        redownloadBtn.disabled = false;
        uploadBtn.disabled = false;
    }
}

// 重新下载 PDF
async function redownloadPDF() {
    if (!currentArxivId) {
        showToast('请先选择论文', 'warning');
        return;
    }
    
    const btn = document.getElementById('redownloadPdfBtn');
    const originalHtml = btn.innerHTML;
    btn.disabled = true;
    btn.innerHTML = '<i class="fas fa-spinner fa-spin"></i>';
    
    try {
        const response = await fetch(`/api/redownload/${currentArxivId}`, {
            method: 'POST'
        });
        const data = await response.json();
        
        if (response.ok) {
            showToast(data.message, 'success');
            updatePdfButtonState(true);
        } else {
            showToast(data.error || '重新下载失败', 'error');
            updatePdfButtonState(false);
        }
    } catch (error) {
        showToast('网络错误，请重试', 'error');
    } finally {
        btn.disabled = false;
        btn.innerHTML = originalHtml;
    }
}

// 显示上传 PDF 模态框
function showUploadPdfModal() {
    if (!currentArxivId) {
        showToast('请先选择论文', 'warning');
        return;
    }
    
    document.getElementById('uploadArxivId').textContent = currentArxivId;
    document.getElementById('pdfFileInput').value = '';
    document.getElementById('uploadProgress').style.display = 'none';
    
    const modal = new bootstrap.Modal(document.getElementById('uploadPdfModal'));
    modal.show();
}

// 上传 PDF
async function uploadPDF() {
    if (!currentArxivId) {
        showToast('请先选择论文', 'warning');
        return;
    }
    
    const fileInput = document.getElementById('pdfFileInput');
    const file = fileInput.files[0];
    
    if (!file) {
        showToast('请选择 PDF 文件', 'warning');
        return;
    }
    
    if (!file.name.toLowerCase().endsWith('.pdf')) {
        showToast('只支持 PDF 文件', 'warning');
        return;
    }
    
    const progressDiv = document.getElementById('uploadProgress');
    progressDiv.style.display = 'block';
    
    const formData = new FormData();
    formData.append('pdf_file', file);
    
    try {
        const response = await fetch(`/api/upload_pdf/${currentArxivId}`, {
            method: 'POST',
            body: formData
        });
        
        const data = await response.json();
        
        // 关闭模态框
        const modal = bootstrap.Modal.getInstance(document.getElementById('uploadPdfModal'));
        modal.hide();
        
        if (response.ok) {
            showToast(data.message, 'success');
            updatePdfButtonState(true);
        } else {
            showToast(data.error || '上传失败', 'error');
        }
    } catch (error) {
        showToast('网络错误，请重试', 'error');
    } finally {
        progressDiv.style.display = 'none';
    }
}

// 显示历史记录
async function showHistory() {
    const modal = new bootstrap.Modal(document.getElementById('historyModal'));
    modal.show();
    
    await loadHistory();
}

// 加载历史记录
async function loadHistory() {
    const historyList = document.getElementById('historyList');
    const loadingDiv = document.getElementById('historyLoading');
    
    loadingDiv.style.display = 'block';
    historyList.innerHTML = '';
    
    try {
        const response = await fetch('/api/history');
        const papers = await response.json();
        
        loadingDiv.style.display = 'none';
        
        if (papers.length === 0) {
            historyList.innerHTML = '<div class="text-center py-4 text-muted">暂无历史记录</div>';
            return;
        }
        
        historyList.innerHTML = papers.map(paper => `
            <div class="card mb-3 history-item ${paper.status}" onclick="loadPaperFromHistory('${paper.arxiv_id}')">
                <div class="card-body">
                    <div class="row">
                        <div class="col-md-9">
                            <h6 class="mb-1">${escapeHtml(paper.title)}</h6>
                            <p class="text-muted small mb-1">${escapeHtml(paper.authors)}</p>
                            <p class="text-muted small mb-0">
                                <i class="fas fa-clock me-1"></i>${formatDate(paper.created_at)}
                                <span class="badge bg-${paper.status === 'completed' ? 'success' : 'warning'} ms-2">
                                    ${paper.status === 'completed' ? '已完成' : '处理中'}
                                </span>
                            </p>
                        </div>
                        <div class="col-md-3 text-end">
                            ${paper.summary ? '<i class="fas fa-check-circle text-success"></i>' : '<i class="fas fa-hourglass-half text-warning"></i>'}
                        </div>
                    </div>
                </div>
            </div>
        `).join('');
    } catch (error) {
        loadingDiv.style.display = 'none';
        historyList.innerHTML = '<div class="text-center py-4 text-danger">加载失败</div>';
    }
}

// 从历史记录加载论文
function loadPaperFromHistory(arxivId) {
    currentArxivId = arxivId;
    loadPaperData(arxivId);
    
    // 关闭模态框
    const modal = bootstrap.Modal.getInstance(document.getElementById('historyModal'));
    modal.hide();
    
    showToast('加载成功', 'success');
}

// 加载论文数据（包含URL更新）
async function loadPaperData(arxivId) {
    try {
        const response = await fetch(`/api/paper/${arxivId}`);
        const data = await response.json();
        
        if (response.ok) {
            updateResultDisplay(data);
            
            // 更新URL输入框（如果存在url字段）
            if (data.url) {
                document.getElementById('arxivUrl').value = data.url;
            }
        } else {
            showToast(data.error || '加载失败', 'error');
        }
    } catch (error) {
        showToast('加载失败', 'error');
    }
}

// 设置示例URL
function setExampleUrl(url) {
    document.getElementById('arxivUrl').value = url;
    document.getElementById('arxivUrl').focus();
}

// 继续完成AI总结
async function continueAISummary() {
    if (!currentArxivId) {
        showToast('请先选择论文', 'warning');
        return;
    }
    
    const continueBtn = document.getElementById('continueAISummaryBtn');
    const statusBadge = document.getElementById('summaryStatus');
    const summaryDiv = document.getElementById('paperSummary');
    
    // 禁用按钮并显示加载状态
    continueBtn.disabled = true;
    continueBtn.innerHTML = '<i class="fas fa-spinner fa-spin me-1"></i>处理中...';
    statusBadge.textContent = '生成中';
    statusBadge.className = 'badge bg-warning';
    
    summaryDiv.innerHTML = `
        <div class="spinner-border spinner-border-sm text-primary" role="status">
            <span class="visually-hidden">加载中...</span>
        </div>
        <span class="ms-2">正在生成总结...</span>
    `;
    summaryDiv.style.display = 'block';
    
    try {
        const response = await fetch(`/api/continue_ai/${currentArxivId}`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            }
        });
        
        const data = await response.json();
        
        if (response.ok) {
            showToast(data.message, 'success');
            // 开始检查状态
            startStatusChecking();
        } else {
            showToast(data.error || '处理失败', 'error');
            // 恢复按钮状态
            continueBtn.disabled = false;
            continueBtn.innerHTML = '<i class="fas fa-play me-1"></i>继续完成 AI 总结';
        }
    } catch (error) {
        showToast('网络错误，请重试', 'error');
        // 恢复按钮状态
        continueBtn.disabled = false;
        continueBtn.innerHTML = '<i class="fas fa-play me-1"></i>继续完成 AI 总结';
    }
}

// 手动开始全文分析
async function startFullAnalysis() {
    if (!currentArxivId) {
        showToast('请先选择论文', 'warning');
        return;
    }

    const startBtn = document.getElementById('startFullAnalysisBtn');
    startBtn.disabled = true;
    startBtn.innerHTML = '<i class="fas fa-spinner fa-spin me-1"></i>处理中...';

    try {
        const response = await fetch(`/api/full_analysis/${currentArxivId}`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' }
        });
        const data = await response.json();

        if (response.ok) {
            showToast(data.message, 'success');
            // 立即刷新显示，然后开始轮询
            checkPaperStatus();
            startStatusChecking();
        } else {
            showToast(data.error || '启动失败', 'error');
            startBtn.disabled = false;
            startBtn.innerHTML = '<i class="fas fa-play me-1"></i>开始全文分析';
        }
    } catch (error) {
        showToast('网络错误，请重试', 'error');
        startBtn.disabled = false;
        startBtn.innerHTML = '<i class="fas fa-play me-1"></i>开始全文分析';
    }
}

// 下载全文分析 Markdown
function downloadAnalysis() {
    if (!currentArxivId) {
        showToast('请先选择论文', 'warning');
        return;
    }
    window.open(`/api/download_analysis/${currentArxivId}`, '_blank');
}

// 重置分析状态（重新分析）
async function resetAnalysis(type) {
    if (!currentArxivId) {
        showToast('请先选择论文', 'warning');
        return;
    }

    const typeText = type === 'summary' ? 'AI 总结' : '全文分析';
    if (!confirm(`确定要重新进行${typeText}吗？之前的分析结果将被清除。`)) {
        return;
    }

    try {
        const response = await fetch(`/api/reset_analysis/${currentArxivId}`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({ type: type })
        });

        const data = await response.json();

        if (response.ok) {
            showToast(data.message, 'success');
            // 刷新页面显示
            await loadPaperData(currentArxivId);
            // 刷新历史记录
            loadHistorySide();
            
            // 根据类型自动开始新的分析
            if (type === 'summary' || type === 'all') {
                // 自动开始 AI 总结
                continueAISummary();
            } else if (type === 'full_analysis') {
                // 自动开始全文分析
                startFullAnalysis();
            }
        } else {
            showToast(data.error || '重置失败', 'error');
        }
    } catch (error) {
        showToast('网络错误，请重试', 'error');
    }
}

// 显示提示消息
function showToast(message, type = 'info') {
    const toastEl = document.getElementById('toast');
    const toastMessage = document.getElementById('toastMessage');
    const toast = new bootstrap.Toast(toastEl);
    
    // 设置消息
    toastMessage.textContent = message;
    
    // 设置图标
    const icon = toastEl.querySelector('.fas');
    icon.className = `fas me-2 text-${type === 'error' ? 'danger' : type === 'success' ? 'success' : 'primary'}`;
    icon.classList.add(type === 'error' ? 'fa-exclamation-circle' : type === 'success' ? 'fa-check-circle' : 'fa-info-circle');
    
    toast.show();
}

// 工具函数：HTML转义
function escapeHtml(text) {
    const map = {
        '&': '&amp;',
        '<': '&lt;',
        '>': '&gt;',
        '"': '&quot;',
        "'": '&#039;'
    };
    return text.replace(/[&<>"']/g, m => map[m]);
}

// 工具函数：格式化日期为北京时间
function formatDate(dateString) {
    if (!dateString) return '';

    // SQLite 默认的 CURRENT_TIMESTAMP 形如 "YYYY-MM-DD HH:MM:SS"，按 UTC 处理再转为北京时间
    let isoString = dateString.trim();

    // 如果不包含时区信息，则按 UTC 处理
    if (!isoString.endsWith('Z') && !isoString.includes('+') && !isoString.includes('-T')) {
        isoString = isoString.replace(' ', 'T') + 'Z';
    }

    const date = new Date(isoString);

    if (isNaN(date.getTime())) {
        return dateString || '';
    }

    // 使用 Asia/Shanghai 时区格式化为北京时间
    const formatter = new Intl.DateTimeFormat('zh-CN', {
        timeZone: 'Asia/Shanghai',
        year: 'numeric',
        month: '2-digit',
        day: '2-digit',
        hour: '2-digit',
        minute: '2-digit',
        second: '2-digit',
        hour12: false
    });

    const parts = formatter.formatToParts(date).reduce((acc, part) => {
        acc[part.type] = part.value;
        return acc;
    }, {});

    const year = parts.year;
    const month = parts.month;
    const day = parts.day;
    const hours = parts.hour;
    const minutes = parts.minute;
    const seconds = parts.second;

    return `${year}.${month}.${day}-${hours}:${minutes}:${seconds}`;
}