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
        
        historyList.innerHTML = papers.map(paper => `
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
                        </div>
                        <div class="ms-2">
                            ${paper.summary ? '<i class="fas fa-check-circle text-success"></i>' : '<i class="fas fa-hourglass-half text-warning"></i>'}
                        </div>
                    </div>
                </div>
            </div>
        `).join('');
    } catch (error) {
        historyList.innerHTML = '<div class="text-center py-4 text-danger">加载失败</div>';
    }
}

// 处理表单提交
async function handleFormSubmit(e) {
    e.preventDefault();
    
    const url = document.getElementById('arxivUrl').value.trim();
    const enableAI = document.getElementById('enableAISummary').checked;
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
            body: JSON.stringify({ url, enable_ai: enableAI })
        });
        
        const data = await response.json();
        
        if (response.ok) {
            currentArxivId = data.arxiv_id;
            showToast(data.message, 'success');
            
            if (data.status === 'existing') {
                loadPaperData(currentArxivId);
            } else if (data.status === 'downloaded') {
                // 未启用AI总结，直接加载论文数据
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
    
    // 30秒后停止自动检查
    setTimeout(() => {
        if (statusCheckInterval) {
            clearInterval(statusCheckInterval);
            statusCheckInterval = null;
        }
    }, 30000);
}

// 检查论文状态
async function checkPaperStatus() {
    if (!currentArxivId) return;
    
    try {
        const response = await fetch(`/api/status/${currentArxivId}`);
        const data = await response.json();
        
        if (response.ok) {
            updateResultDisplay(data);
            
            // 如果总结已完成，停止检查
            if (data.status === 'completed' && data.summary) {
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
    
    // 更新总结
    const summaryDiv = document.getElementById('paperSummary');
    const statusBadge = document.getElementById('summaryStatus');
    const continueBtn = document.getElementById('continueAISummaryBtn');
    
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
    } else if (data.status === 'downloaded') {
        summaryDiv.style.display = 'none';
        statusBadge.textContent = '未启用';
        statusBadge.className = 'badge bg-secondary';
        continueBtn.style.display = 'inline-block';
    } else if (data.status === 'failed') {
        summaryDiv.innerHTML = '<em>AI 总结生成失败，请点击“继续完成 AI 总结”重试</em>';
        summaryDiv.style.display = 'block';
        statusBadge.textContent = '失败';
        statusBadge.className = 'badge bg-danger';
        continueBtn.style.display = 'inline-block';
    } else {
        summaryDiv.style.display = 'none';
        statusBadge.textContent = '等待中';
        statusBadge.className = 'badge bg-secondary';
        continueBtn.style.display = 'none';
    }
}

// 下载PDF
async function downloadPDF() {
    if (!currentArxivId) {
        showToast('请先处理论文', 'warning');
        return;
    }
    
    window.open(`/api/download/${currentArxivId}`, '_blank');
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