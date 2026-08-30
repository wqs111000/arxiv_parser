// Global state
let currentArxivId = null;
let statusCheckTimeout = null;
let pollElapsed = 0;
let allHistoryPapers = [];
const apiUrl = path => `${window.APP_BASE_PATH || ''}/api${path}`;

// Init
document.addEventListener('DOMContentLoaded', function () {
    loadHistorySide();
    document.getElementById('paperForm').addEventListener('submit', handleFormSubmit);
    document.getElementById('arxivUrl').addEventListener('keypress', function (e) {
        if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault();
            handleFormSubmit(e);
        }
    });
});

// ---------------------------------------------------------------------------
// History
// ---------------------------------------------------------------------------

async function loadHistorySide() {
    const historyList = document.getElementById('historyListSide');
    historyList.innerHTML = '<div class="text-center py-3 text-muted"><div class="spinner-border spinner-border-sm text-primary" role="status"></div><p class="mt-2 mb-0">加载历史记录...</p></div>';

    try {
        const response = await fetch(apiUrl('/history?page=1&per_page=100'));
        const data = await response.json();
        allHistoryPapers = data.papers || [];
        renderHistorySide(allHistoryPapers);
    } catch (error) {
        historyList.innerHTML = '<div class="text-center py-4 text-danger">加载失败</div>';
    }
}

function renderHistorySide(papers) {
    const historyList = document.getElementById('historyListSide');
    if (papers.length === 0) {
        historyList.innerHTML = '<div class="text-center py-4 text-muted">暂无历史记录</div>';
        return;
    }
    historyList.innerHTML = papers.map(paper => {
        const hasSummary = !!paper.summary;
        const hasMd = paper.md_exists;
        let statusIcon;
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
        <div class="card mb-2 history-item ${paper.status}" style="cursor: pointer;">
            <div class="card-body p-3">
                <div class="d-flex justify-content-between align-items-start">
                    <div class="flex-grow-1" onclick="loadPaperFromHistory('${paper.arxiv_id}')">
                        <h6 class="mb-1 fs-6">${escapeHtml(paper.title)}</h6>
                        ${paper.version_history ? `<p class="text-muted small mb-1"><i class="fas fa-history me-1"></i>${paper.version_history.substring(0, 50)}${paper.version_history.length > 50 ? '...' : ''}</p>` : ''}
                        <p class="text-muted small mb-0"><i class="fas fa-clock me-1"></i>${formatDate(paper.created_at)}</p>
                        <div class="mt-1">
                            ${hasSummary ? '<span class="badge bg-primary me-1" style="font-size:0.6em;">总结</span>' : ''}
                            ${hasMd ? '<span class="badge bg-success me-1" style="font-size:0.6em;">全文</span>' : ''}
                            ${(!hasSummary && !hasMd) ? '<span class="badge bg-secondary" style="font-size:0.6em;">仅下载</span>' : ''}
                        </div>
                    </div>
                    <div class="ms-2 d-flex flex-column align-items-end gap-1">
                        ${statusIcon}
                        <button class="btn btn-link btn-sm p-0 text-danger" title="删除" onclick="deletePaper('${paper.arxiv_id}', event)">
                            <i class="fas fa-trash-alt" style="font-size:0.75em;"></i>
                        </button>
                    </div>
                </div>
            </div>
        </div>`;
    }).join('');
}

function filterHistory(query) {
    const q = query.trim().toLowerCase();
    if (!q) {
        renderHistorySide(allHistoryPapers);
        return;
    }
    const filtered = allHistoryPapers.filter(p =>
        (p.title || '').toLowerCase().includes(q)
    );
    renderHistorySide(filtered);
}

async function deletePaper(arxivId, event) {
    event.stopPropagation();
    if (!confirm('确定要删除该论文及其所有分析结果吗？')) return;

    try {
        const response = await fetch(apiUrl(`/paper/${arxivId}`), { method: 'DELETE' });
        const data = await response.json();
        if (response.ok) {
            showToast(data.message, 'success');
            if (currentArxivId === arxivId) {
                currentArxivId = null;
                document.getElementById('resultContainer').style.display = 'none';
                document.getElementById('emptyState').style.display = 'block';
            }
            loadHistorySide();
        } else {
            showToast(data.error || '删除失败', 'error');
        }
    } catch (error) {
        showToast('网络错误，请重试', 'error');
    }
}

// ---------------------------------------------------------------------------
// Form submit
// ---------------------------------------------------------------------------

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
    submitBtn.disabled = true;
    submitBtn.innerHTML = '<i class="fas fa-spinner fa-spin me-2"></i>处理中...';

    try {
        const response = await fetch(apiUrl('/process'), {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ url, enable_ai: enableAI, enable_full_analysis: enableFullAnalysis }),
        });
        const data = await response.json();

        if (response.ok) {
            currentArxivId = data.arxiv_id;
            showToast(data.message, 'success');
            if (data.status === 'existing') {
                loadPaperData(currentArxivId);
            } else if (data.status === 'downloaded' && (data.full_analysis_status || 'none') === 'none') {
                loadPaperData(currentArxivId);
            } else {
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

// ---------------------------------------------------------------------------
// Adaptive polling
// ---------------------------------------------------------------------------

function startStatusChecking() {
    stopStatusChecking();
    pollElapsed = 0;
    _schedulePoll();
}

function stopStatusChecking() {
    if (statusCheckTimeout) {
        clearTimeout(statusCheckTimeout);
        statusCheckTimeout = null;
    }
}

function _pollInterval() {
    if (pollElapsed < 30000) return 2000;   // first 30 s: every 2 s
    if (pollElapsed < 120000) return 5000;  // 30 s – 2 min: every 5 s
    return 10000;                           // 2 min+: every 10 s
}

function _schedulePoll() {
    const interval = _pollInterval();
    statusCheckTimeout = setTimeout(async () => {
        await checkPaperStatus();
        pollElapsed += interval;
        // Keep polling if still running; hard stop at 10 min
        if (statusCheckTimeout !== null && pollElapsed < 600000) {
            _schedulePoll();
        }
    }, interval);
}

async function checkPaperStatus() {
    if (!currentArxivId) return;
    try {
        const response = await fetch(apiUrl(`/status/${currentArxivId}`));
        const data = await response.json();
        if (response.ok) {
            updateResultDisplay(data);
            const summaryDone = ['completed', 'downloaded', 'failed'].includes(data.status);
            const faStatus = data.full_analysis_status || 'none';
            const faDone = ['completed', 'failed', 'none'].includes(faStatus);
            if (summaryDone && faDone) {
                stopStatusChecking();
                loadHistorySide();
            }
        }
    } catch (error) {
        console.error('检查状态失败:', error);
    }
}

// ---------------------------------------------------------------------------
// Display
// ---------------------------------------------------------------------------

function updateResultDisplay(data) {
    document.getElementById('emptyState').style.display = 'none';
    document.getElementById('resultContainer').style.display = 'block';

    document.getElementById('paperTitle').textContent = data.title || '未知标题';
    document.getElementById('paperAuthors').textContent = data.authors || '未知作者';
    document.getElementById('paperAbstract').textContent = data.abstract || '暂无摘要';

    if (data.version_history) {
        document.getElementById('versionHistory').style.display = 'block';
        document.getElementById('versionInfo').textContent = data.version_history;
    }
    if (data.summary_model || data.model) {
        document.getElementById('modelInfo').style.display = 'block';
        document.getElementById('modelName').textContent = data.summary_model || data.model;
    }
    if (data.arxiv_id) currentArxivId = data.arxiv_id;

    // Use pdf_exists from API response to avoid an extra check_pdf round-trip
    if (typeof data.pdf_exists === 'boolean') {
        updatePdfButtonState(data.pdf_exists);
    } else {
        checkAndUpdatePdfStatus();
    }

    // Summary section
    const summaryDiv = document.getElementById('paperSummary');
    const statusBadge = document.getElementById('summaryStatus');
    const continueBtn = document.getElementById('continueAISummaryBtn');
    const resetSummaryBtn = document.getElementById('resetSummaryBtn');

    if (data.status === 'completed') {
        summaryDiv.innerHTML = data.summary ? data.summary.replace(/\n/g, '<br>') : '<em>总结生成失败，请重试</em>';
        summaryDiv.style.display = 'block';
        statusBadge.textContent = '已完成';
        statusBadge.className = 'badge bg-success';
        continueBtn.style.display = 'none';
        resetSummaryBtn.style.display = 'inline-block';
    } else if (data.status === 'processing') {
        summaryDiv.innerHTML = '<div class="spinner-border spinner-border-sm text-primary" role="status"></div><span class="ms-2">正在生成总结...</span>';
        summaryDiv.style.display = 'block';
        statusBadge.textContent = '生成中';
        statusBadge.className = 'badge bg-warning';
        continueBtn.style.display = 'none';
        resetSummaryBtn.style.display = 'none';
    } else if (data.status === 'downloaded') {
        summaryDiv.style.display = 'none';
        statusBadge.textContent = '未启用';
        statusBadge.className = 'badge bg-secondary';
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

    updateFullAnalysisDisplay(data);
}

function updateFullAnalysisDisplay(data) {
    const faStatus = data.full_analysis_status || 'none';
    const faSection = document.getElementById('fullAnalysisSection');
    const faStatusBadge = document.getElementById('fullAnalysisStatus');
    const faContent = document.getElementById('fullAnalysisContent');
    const faLoading = document.getElementById('fullAnalysisLoading');
    const downloadBtn = document.getElementById('downloadAnalysisBtn');
    const startBtn = document.getElementById('startFullAnalysisBtn');
    const resetFullAnalysisBtn = document.getElementById('resetFullAnalysisBtn');

    const hasLocalMd = data.md_exists && data.full_analysis;
    if (faStatus === 'none' && !hasLocalMd && !data.pdf_exists) {
        faSection.style.display = 'none';
        return;
    }
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
        faStatusBadge.textContent = '未分析';
        faStatusBadge.className = 'badge bg-secondary';
        faLoading.style.display = 'none';
        faContent.style.display = 'none';
        downloadBtn.style.display = 'none';
        startBtn.style.display = 'inline-block';
        resetFullAnalysisBtn.style.display = 'none';
    }
}

// ---------------------------------------------------------------------------
// Markdown + LaTeX rendering
// ---------------------------------------------------------------------------

function renderMarkdown(text) {
    if (!text) return '';

    const codeBlocks = [];
    let t = text.replace(/```[\s\S]*?```/g, m => {
        codeBlocks.push(m);
        return `\x00CODE_${codeBlocks.length - 1}\x00`;
    });

    const inlineCodes = [];
    t = t.replace(/`[^`]+`/g, m => {
        inlineCodes.push(m);
        return `\x00ICODE_${inlineCodes.length - 1}\x00`;
    });

    const maths = [];
    t = t.replace(/\$\$([\s\S]*?)\$\$/g, (_, f) => {
        maths.push({ type: 'block', formula: f.trim() });
        return `\x00MATH_${maths.length - 1}\x00`;
    });
    t = t.replace(/\$([^\$\s][^\$]*?)\$/g, (match, f) => {
        if (/^\d+(,\d{3})*(\.\d{1,2})?$/.test(f.trim())) return match;
        maths.push({ type: 'inline', formula: f.trim() });
        return `\x00MATH_${maths.length - 1}\x00`;
    });

    let html = typeof marked !== 'undefined' ? marked.parse(t) : t.replace(/\n/g, '<br>');

    codeBlocks.forEach((c, i) => { html = html.replace(`\x00CODE_${i}\x00`, c); });
    inlineCodes.forEach((c, i) => { html = html.replace(`\x00ICODE_${i}\x00`, c); });
    maths.forEach((m, i) => {
        let rendered;
        try {
            rendered = typeof katex !== 'undefined'
                ? katex.renderToString(m.formula, { throwOnError: false, displayMode: m.type === 'block' })
                : (m.type === 'block' ? `<div class="math-block">$$${m.formula}$$</div>` : `<span>$${m.formula}$</span>`);
        } catch (e) {
            rendered = m.type === 'block' ? `<div class="math-block text-danger">$$${m.formula}$$</div>` : `<span class="text-danger">$${m.formula}$</span>`;
        }
        html = html.replace(`\x00MATH_${i}\x00`, rendered);
    });
    return html;
}

// ---------------------------------------------------------------------------
// PDF actions
// ---------------------------------------------------------------------------

async function downloadPDF() {
    if (!currentArxivId) { showToast('请先处理论文', 'warning'); return; }
    try {
        const r = await fetch(apiUrl(`/check_pdf/${currentArxivId}`));
        const d = await r.json();
        if (!d.exists || !d.valid) {
            showToast(d.error || 'PDF 文件不存在或已损坏', 'error');
            updatePdfButtonState(false);
            return;
        }
        window.open(apiUrl(`/download/${currentArxivId}`), '_blank');
    } catch (e) {
        showToast('检查 PDF 状态失败', 'error');
    }
}

async function checkAndUpdatePdfStatus() {
    if (!currentArxivId) return;
    try {
        const r = await fetch(apiUrl(`/check_pdf/${currentArxivId}`));
        const d = await r.json();
        updatePdfButtonState(d.exists && d.valid);
    } catch (e) {
        updatePdfButtonState(false);
    }
}

function updatePdfButtonState(pdfExists) {
    const downloadBtn = document.getElementById('downloadPdfBtn');
    const redownloadBtn = document.getElementById('redownloadPdfBtn');
    const uploadBtn = document.getElementById('uploadPdfBtn');
    downloadBtn.style.display = redownloadBtn.style.display = uploadBtn.style.display = 'inline-block';
    if (pdfExists) {
        downloadBtn.disabled = false;
        downloadBtn.classList.replace('btn-outline-secondary', 'btn-outline-primary');
    } else {
        downloadBtn.disabled = true;
        downloadBtn.classList.replace('btn-outline-primary', 'btn-outline-secondary');
    }
    redownloadBtn.disabled = false;
    uploadBtn.disabled = false;
}

async function redownloadPDF() {
    if (!currentArxivId) { showToast('请先选择论文', 'warning'); return; }
    const btn = document.getElementById('redownloadPdfBtn');
    const orig = btn.innerHTML;
    btn.disabled = true;
    btn.innerHTML = '<i class="fas fa-spinner fa-spin"></i>';
    try {
        const r = await fetch(apiUrl(`/redownload/${currentArxivId}`), { method: 'POST' });
        const d = await r.json();
        showToast(r.ok ? d.message : (d.error || '重新下载失败'), r.ok ? 'success' : 'error');
        updatePdfButtonState(r.ok);
    } catch (e) {
        showToast('网络错误，请重试', 'error');
    } finally {
        btn.disabled = false;
        btn.innerHTML = orig;
    }
}

function showUploadPdfModal() {
    if (!currentArxivId) { showToast('请先选择论文', 'warning'); return; }
    document.getElementById('uploadArxivId').textContent = currentArxivId;
    document.getElementById('pdfFileInput').value = '';
    document.getElementById('uploadProgress').style.display = 'none';
    new bootstrap.Modal(document.getElementById('uploadPdfModal')).show();
}

async function uploadPDF() {
    if (!currentArxivId) { showToast('请先选择论文', 'warning'); return; }
    const file = document.getElementById('pdfFileInput').files[0];
    if (!file) { showToast('请选择 PDF 文件', 'warning'); return; }
    if (!file.name.toLowerCase().endsWith('.pdf')) { showToast('只支持 PDF 文件', 'warning'); return; }

    document.getElementById('uploadProgress').style.display = 'block';
    const formData = new FormData();
    formData.append('pdf_file', file);
    try {
        const r = await fetch(apiUrl(`/upload_pdf/${currentArxivId}`), { method: 'POST', body: formData });
        const d = await r.json();
        bootstrap.Modal.getInstance(document.getElementById('uploadPdfModal')).hide();
        showToast(r.ok ? d.message : (d.error || '上传失败'), r.ok ? 'success' : 'error');
        if (r.ok) updatePdfButtonState(true);
    } catch (e) {
        showToast('网络错误，请重试', 'error');
    } finally {
        document.getElementById('uploadProgress').style.display = 'none';
    }
}

// ---------------------------------------------------------------------------
// History modal (unchanged behaviour)
// ---------------------------------------------------------------------------

async function showHistory() {
    new bootstrap.Modal(document.getElementById('historyModal')).show();
    await loadHistory();
}

async function loadHistory() {
    const historyList = document.getElementById('historyList');
    const loadingDiv = document.getElementById('historyLoading');
    loadingDiv.style.display = 'block';
    historyList.innerHTML = '';
    try {
        const r = await fetch(apiUrl('/history?page=1&per_page=20'));
        const data = await r.json();
        const papers = data.papers || [];
        loadingDiv.style.display = 'none';
        if (papers.length === 0) {
            historyList.innerHTML = '<div class="text-center py-4 text-muted">暂无历史记录</div>';
            return;
        }
        historyList.innerHTML = papers.map(p => `
            <div class="card mb-3 history-item ${p.status}" onclick="loadPaperFromHistory('${p.arxiv_id}')">
                <div class="card-body">
                    <div class="row">
                        <div class="col-md-9">
                            <h6 class="mb-1">${escapeHtml(p.title)}</h6>
                            <p class="text-muted small mb-1">${escapeHtml(p.authors || '')}</p>
                            <p class="text-muted small mb-0">
                                <i class="fas fa-clock me-1"></i>${formatDate(p.created_at)}
                                <span class="badge bg-${p.status === 'completed' ? 'success' : 'warning'} ms-2">${p.status === 'completed' ? '已完成' : '处理中'}</span>
                            </p>
                        </div>
                        <div class="col-md-3 text-end">
                            ${p.summary ? '<i class="fas fa-check-circle text-success"></i>' : '<i class="fas fa-hourglass-half text-warning"></i>'}
                        </div>
                    </div>
                </div>
            </div>`).join('');
    } catch (error) {
        loadingDiv.style.display = 'none';
        historyList.innerHTML = '<div class="text-center py-4 text-danger">加载失败</div>';
    }
}

function loadPaperFromHistory(arxivId) {
    currentArxivId = arxivId;
    loadPaperData(arxivId);
    const modal = bootstrap.Modal.getInstance(document.getElementById('historyModal'));
    if (modal) modal.hide();
    showToast('加载成功', 'success');
}

async function loadPaperData(arxivId) {
    try {
        const r = await fetch(apiUrl(`/paper/${arxivId}`));
        const data = await r.json();
        if (r.ok) {
            updateResultDisplay(data);
            if (data.url) document.getElementById('arxivUrl').value = data.url;
        } else {
            showToast(data.error || '加载失败', 'error');
        }
    } catch (error) {
        showToast('加载失败', 'error');
    }
}

// ---------------------------------------------------------------------------
// AI actions
// ---------------------------------------------------------------------------

function setExampleUrl(url) {
    document.getElementById('arxivUrl').value = url;
    document.getElementById('arxivUrl').focus();
}

async function continueAISummary() {
    if (!currentArxivId) { showToast('请先选择论文', 'warning'); return; }
    const btn = document.getElementById('continueAISummaryBtn');
    const statusBadge = document.getElementById('summaryStatus');
    const summaryDiv = document.getElementById('paperSummary');

    btn.disabled = true;
    btn.innerHTML = '<i class="fas fa-spinner fa-spin me-1"></i>处理中...';
    statusBadge.textContent = '生成中';
    statusBadge.className = 'badge bg-warning';
    summaryDiv.innerHTML = '<div class="spinner-border spinner-border-sm text-primary" role="status"></div><span class="ms-2">正在生成总结...</span>';
    summaryDiv.style.display = 'block';

    try {
        const r = await fetch(apiUrl(`/continue_ai/${currentArxivId}`), { method: 'POST', headers: { 'Content-Type': 'application/json' } });
        const d = await r.json();
        if (r.ok) {
            showToast(d.message, 'success');
            startStatusChecking();
        } else {
            showToast(d.error || '处理失败', 'error');
            btn.disabled = false;
            btn.innerHTML = '<i class="fas fa-play me-1"></i>继续完成 AI 总结';
        }
    } catch (e) {
        showToast('网络错误，请重试', 'error');
        btn.disabled = false;
        btn.innerHTML = '<i class="fas fa-play me-1"></i>继续完成 AI 总结';
    }
}

async function startFullAnalysis() {
    if (!currentArxivId) { showToast('请先选择论文', 'warning'); return; }
    const btn = document.getElementById('startFullAnalysisBtn');
    btn.disabled = true;
    btn.innerHTML = '<i class="fas fa-spinner fa-spin me-1"></i>处理中...';
    try {
        const r = await fetch(apiUrl(`/full_analysis/${currentArxivId}`), { method: 'POST', headers: { 'Content-Type': 'application/json' } });
        const d = await r.json();
        if (r.ok) {
            showToast(d.message, 'success');
            checkPaperStatus();
            startStatusChecking();
        } else {
            showToast(d.error || '启动失败', 'error');
            btn.disabled = false;
            btn.innerHTML = '<i class="fas fa-play me-1"></i>开始全文分析';
        }
    } catch (e) {
        showToast('网络错误，请重试', 'error');
        btn.disabled = false;
        btn.innerHTML = '<i class="fas fa-play me-1"></i>开始全文分析';
    }
}

function downloadAnalysis() {
    if (!currentArxivId) { showToast('请先选择论文', 'warning'); return; }
    window.open(apiUrl(`/download_analysis/${currentArxivId}`), '_blank');
}

async function resetAnalysis(type) {
    if (!currentArxivId) { showToast('请先选择论文', 'warning'); return; }
    const typeText = type === 'summary' ? 'AI 总结' : '全文分析';
    if (!confirm(`确定要重新进行${typeText}吗？之前的分析结果将被清除。`)) return;

    try {
        const r = await fetch(apiUrl(`/reset_analysis/${currentArxivId}`), {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ type }),
        });
        const d = await r.json();
        if (r.ok) {
            showToast(d.message, 'success');
            await loadPaperData(currentArxivId);
            loadHistorySide();
            if (type === 'summary' || type === 'all') {
                continueAISummary();
            } else if (type === 'full_analysis') {
                startFullAnalysis();
            }
        } else {
            showToast(d.error || '重置失败', 'error');
        }
    } catch (e) {
        showToast('网络错误，请重试', 'error');
    }
}

// ---------------------------------------------------------------------------
// Utilities
// ---------------------------------------------------------------------------

function showToast(message, type = 'info') {
    const toastEl = document.getElementById('toast');
    const toastMessage = document.getElementById('toastMessage');
    toastMessage.textContent = message;
    const icon = toastEl.querySelector('.fas');
    const iconMap = { error: ['fa-exclamation-circle', 'text-danger'], success: ['fa-check-circle', 'text-success'] };
    const [iconClass, colorClass] = iconMap[type] || ['fa-info-circle', 'text-primary'];
    icon.className = `fas me-2 ${colorClass} ${iconClass}`;
    new bootstrap.Toast(toastEl).show();
}

// ---------------------------------------------------------------------------
// Knowledge base search
// ---------------------------------------------------------------------------

async function searchKnowledgeBase() {
    const query = document.getElementById('kbSearchInput').value.trim();
    if (!query) { showToast('请输入搜索关键词', 'warning'); return; }

    const container = document.getElementById('kbResultContainer');
    const answerDiv = document.getElementById('kbAnswer');
    const chunksDiv = document.getElementById('kbChunks');

    container.style.display = 'block';
    document.getElementById('emptyState').style.display = 'none';
    document.getElementById('resultContainer').style.display = 'none';
    answerDiv.style.display = 'none';
    chunksDiv.innerHTML = '<div class="text-center py-4"><div class="spinner-border spinner-border-sm text-primary"></div><span class="ms-2">搜索中...</span></div>';

    try {
        const r = await fetch(apiUrl(`/search?q=${encodeURIComponent(query)}&n=5`));
        const d = await r.json();
        if (!r.ok) { showToast(d.error || '搜索失败', 'error'); return; }

        if (d.answer) {
            answerDiv.innerHTML = `<strong>综合回答：</strong><br>${escapeHtml(d.answer).replace(/\n/g, '<br>')}`;
            answerDiv.style.display = 'block';
        }

        if (d.chunks && d.chunks.length > 0) {
            chunksDiv.innerHTML = '<h6 class="text-muted mt-3 mb-2">相关片段</h6>' + d.chunks.map((c, i) => `
                <div class="card mb-2">
                    <div class="card-body p-2">
                        <div class="d-flex justify-content-between align-items-start">
                            <small class="text-muted">${escapeHtml(c.metadata?.title || '未知')} · ${escapeHtml(c.metadata?.section || '')}</small>
                            ${c.score != null ? `<small class="text-muted">相关度: ${(c.score * 100).toFixed(0)}%</small>` : ''}
                        </div>
                        <p class="mb-0 mt-1 small" style="max-height: 150px; overflow-y: auto;">${escapeHtml((c.text || '').substring(0, 500))}</p>
                        ${c.metadata?.arxiv_id ? `<button class="btn btn-link btn-sm p-0 mt-1" onclick="loadPaperFromHistory('${c.metadata.arxiv_id}')">查看论文详情 →</button>` : ''}
                    </div>
                </div>
            `).join('');
        } else {
            chunksDiv.innerHTML = '<div class="text-center py-4 text-muted">未找到相关内容。请先对论文进行全文分析后再搜索。</div>';
        }
    } catch (e) {
        chunksDiv.innerHTML = '<div class="text-center py-4 text-danger">搜索失败，请重试</div>';
    }
}

function closeKBResult() {
    document.getElementById('kbResultContainer').style.display = 'none';
    document.getElementById('emptyState').style.display = 'block';
    document.getElementById('kbSearchInput').value = '';
}

function escapeHtml(text) {
    if (!text) return '';
    return text.replace(/[&<>"']/g, m => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#039;' }[m]));
}

function formatDate(dateString) {
    if (!dateString) return '';
    let iso = dateString.trim();
    if (!iso.endsWith('Z') && !iso.includes('+') && !iso.includes('-T')) {
        iso = iso.replace(' ', 'T') + 'Z';
    }
    const date = new Date(iso);
    if (isNaN(date.getTime())) return dateString;
    const fmt = new Intl.DateTimeFormat('zh-CN', {
        timeZone: 'Asia/Shanghai',
        year: 'numeric', month: '2-digit', day: '2-digit',
        hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false,
    });
    const p = fmt.formatToParts(date).reduce((a, x) => { a[x.type] = x.value; return a; }, {});
    return `${p.year}.${p.month}.${p.day}-${p.hour}:${p.minute}:${p.second}`;
}
