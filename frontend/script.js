const videoUrlInput = document.getElementById('video-url');
const videoSelect = document.getElementById('video-select');
const searchTextInput = document.getElementById('search-text');
const searchModeSelect = document.getElementById('search-mode');
const runBtn = document.getElementById('run-btn');
const statusMsg = document.getElementById('status-msg');
const historyContainer = document.getElementById('history-container');

// Exclusive selection logic for URL vs Local File
videoUrlInput.addEventListener('input', () => {
    if (videoUrlInput.value.trim().length > 0) {
        videoSelect.disabled = true;
        videoSelect.value = "";
    } else {
        videoSelect.disabled = false;
    }
});

videoSelect.addEventListener('change', () => {
    if (videoSelect.value !== "") {
        videoUrlInput.disabled = true;
        videoUrlInput.value = "";
    } else {
        videoUrlInput.disabled = false;
    }
});

// Fetch cached videos and history on page load
window.addEventListener('DOMContentLoaded', async () => {
    // 1. Fetch Videos
    try {
        const resp = await fetch('/api/videos');
        if (resp.ok) {
            const data = await resp.json();
            data.videos.forEach(vid => {
                const opt = document.createElement('option');
                opt.value = vid;
                opt.textContent = vid;
                videoSelect.appendChild(opt);
            });
        }
    } catch (e) {
        console.error("Failed to fetch videos", e);
    }

    // 2. Fetch History
    try {
        const resp = await fetch('/api/history');
        if (resp.ok) {
            const data = await resp.json();
            data.history.forEach(hist => {
                // Backend sends newest first. We use beforeend so they stack top-to-bottom.
                renderHistoryCard(hist, hist.session_id, hist.target_text || "Unknown Target", false);
            });
        }
    } catch (e) {
        console.error("Failed to fetch history", e);
    }
});

function renderHistoryCard(resultData, sessionId, targetText, prepend = true) {
    if (resultData.status === "NOT_FOUND") {
        const cardHtml = `
            <div class="history-card" style="border-color: rgba(239, 68, 68, 0.3); background: rgba(239, 68, 68, 0.05);">
                <div style="display: flex; flex-direction: column; width: 100%; gap: 1rem;">
                    <div style="display: flex; align-items: center; gap: 0.5rem; color: var(--error);">
                        <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"></circle><line x1="12" y1="8" x2="12" y2="12"></line><line x1="12" y1="16" x2="12.01" y2="16"></line></svg>
                        <span style="font-weight: 700; font-size: 1.1rem; letter-spacing: 0.05em;">TARGET NOT FOUND</span>
                    </div>
                    <div class="history-quote-box" style="border-color: rgba(239, 68, 68, 0.2); background: rgba(239, 68, 68, 0.02);">
                        Searched for: <span style="font-style: italic;">"${targetText}"</span>
                    </div>
                </div>
            </div>
        `;
        if (prepend) historyContainer.insertAdjacentHTML('afterbegin', cardHtml);
        else historyContainer.insertAdjacentHTML('beforeend', cardHtml);
    } else {
        const imgSrc = `/api/frame?id=${sessionId}&t=` + new Date().getTime();
        
        let wordCount = 0;
        if (resultData.extracted_text && resultData.extracted_text.trim()) {
            wordCount = resultData.extracted_text.trim().split(/\s+/).length;
        }
        
        let mode = resultData.mode;
        if (!mode) {
            if (resultData.status === "ASR_ONLY_MATCH") mode = "asr_only";
            else mode = "ocr_only";
        }
        
        let methodIcon = "";
        let methodText = "";
        if (mode === "asr_only") {
            methodIcon = `<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M2 10v3"/><path d="M6 6v11"/><path d="M10 3v18"/><path d="M14 8v7"/><path d="M18 5v13"/><path d="M22 10v3"/></svg>`;
            methodText = "VOICE";
        } else if (mode === "ocr_only") {
            methodIcon = `<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"></path><circle cx="12" cy="12" r="3"></circle></svg>`;
            methodText = "VISUAL";
        } else {
            methodIcon = `<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="2"/><path d="M7.5 7.5a6.4 6.4 0 0 0 0 9"/><path d="M16.5 7.5a6.4 6.4 0 0 1 0 9"/><path d="M4.5 4.5a10.6 10.6 0 0 0 0 15"/><path d="M19.5 4.5a10.6 10.6 0 0 1 0 15"/><path d="M12 2v3"/><path d="M12 19v3"/></svg>`;
            methodText = "DUAL";
        }
        
        let asdBadgeHtml = "";
        if (resultData.asd_status === "ON_SCREEN" || resultData.asd_status === "OFF_SCREEN") {
            const isOff = resultData.asd_status === "OFF_SCREEN";
            const badgeColor = isOff ? "rgba(239, 68, 68, 0.9)" : "rgba(16, 185, 129, 0.9)";
            const badgeText = isOff ? "OFF-SCREEN" : "ON-SCREEN";
            const badgeIcon = isOff ? `<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M1 1l22 22"></path><path d="M9 9v3a3 3 0 005.12 2.12M15 9.34V4a3 3 0 00-5.94-.6"></path><path d="M17 16.95A7 7 0 015 12v-2m14 0v2a7 7 0 01-.11 1.23"></path><line x1="12" y1="19" x2="12" y2="23"></line><line x1="8" y1="23" x2="16" y2="23"></line></svg>` : `<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 1a3 3 0 0 0-3 3v8a3 3 0 0 0 6 0V4a3 3 0 0 0-3-3z"></path><path d="M19 10v2a7 7 0 0 1-14 0v-2"></path><line x1="12" y1="19" x2="12" y2="23"></line><line x1="8" y1="23" x2="16" y2="23"></line></svg>`;
            asdBadgeHtml = `
                <div style="position: absolute; top: 12px; left: 12px; background: ${badgeColor}; color: white; padding: 6px 10px; border-radius: 6px; font-size: 0.8rem; font-weight: 700; display: flex; align-items: center; gap: 6px; box-shadow: 0 4px 12px rgba(0,0,0,0.5); z-index: 10; letter-spacing: 0.05em; border: 1px solid rgba(255,255,255,0.2);">
                    ${badgeIcon}
                    ${badgeText}
                </div>
            `;
        }

        const cardHtml = `
            <div class="history-card">
                <div class="history-image-col">
                    <div style="position: relative; display: flex; max-width: 100%; height: auto;">
                        ${asdBadgeHtml}
                        <img src="${imgSrc}" alt="Extracted Frame" onerror="this.src=''" style="display: block; width: 100%; height: auto; border-radius: 6px;" />
                    </div>
                </div>
                <div class="history-details-col">
                    <div class="history-metrics-grid">
                        <div class="history-metric-box">
                            <div class="history-metric-header">
                                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"></circle><polyline points="12 6 12 12 16 14"></polyline></svg>
                                <span class="history-metric-label">TIMESTAMP</span>
                            </div>
                            <span class="history-metric-value">${resultData.timestamp}</span>
                        </div>
                        <div class="history-metric-box">
                            <div class="history-metric-header">
                                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="2" y="2" width="20" height="20" rx="2.18" ry="2.18"></rect><line x1="7" y1="2" x2="7" y2="22"></line><line x1="17" y1="2" x2="17" y2="22"></line><line x1="2" y1="12" x2="22" y2="12"></line><line x1="2" y1="7" x2="7" y2="7"></line><line x1="2" y1="17" x2="7" y2="17"></line><line x1="17" y1="17" x2="22" y2="17"></line><line x1="17" y1="7" x2="22" y2="7"></line></svg>
                                <span class="history-metric-label">FRAME</span>
                            </div>
                            <span class="history-metric-value">${resultData.frame_number}</span>
                        </div>
                        <div class="history-metric-box">
                            <div class="history-metric-header">
                                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="14" r="8"></circle><line x1="12" y1="2" x2="12" y2="6"></line><line x1="8" y1="2" x2="16" y2="2"></line></svg>
                                <span class="history-metric-label">TIME</span>
                            </div>
                            <span class="history-metric-value">${resultData.processing_time !== undefined ? resultData.processing_time + 's' : '0.0s'}</span>
                        </div>
                        <div class="history-metric-box">
                            <div class="history-metric-header">
                                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2"></polygon></svg>
                                <span class="history-metric-label">METHOD</span>
                            </div>
                            <div class="history-metric-value" style="display: flex; align-items: center; gap: 6px; color: var(--neon-blue);">
                                ${methodIcon} <span style="font-size: 0.95rem; line-height: 1.2;">${methodText}</span>
                            </div>
                        </div>
                        <div class="history-metric-box success" style="flex: 1 1 max-content; min-width: 110px;">
                            <div class="history-metric-header">
                                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"></path><polyline points="22 4 12 14.01 9 11.01"></polyline></svg>
                                <span class="history-metric-label">CONFIDENCE</span>
                            </div>
                            <span class="history-metric-value">${resultData.confidence_score}%</span>
                        </div>
                        <div class="history-metric-box" style="flex: 5 1 auto; min-width: 150px;">
                            <div class="history-metric-header">
                                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="11" cy="11" r="8"></circle><line x1="21" y1="21" x2="16.65" y2="16.65"></line></svg>
                                <span class="history-metric-label">TARGET</span>
                            </div>
                            <span class="history-metric-value" style="font-size: 0.95rem; line-height: 1.2; word-wrap: break-word; white-space: normal;">"${targetText}"</span>
                        </div>
                    </div>
                    <div class="history-quote-box">
                        "${resultData.extracted_text}"
                    </div>
                </div>
            </div>
        `;
        if (prepend) historyContainer.insertAdjacentHTML('afterbegin', cardHtml);
        else historyContainer.insertAdjacentHTML('beforeend', cardHtml);
    }
}

runBtn.addEventListener('click', async () => {
    const url = videoUrlInput.value.trim();
    const localVideo = videoSelect.value;
    const targetText = searchTextInput.value.trim();
    const searchMode = searchModeSelect.value;

    if (!url && !localVideo) {
        showStatus("Please select a cached video or enter a URL.", "error");
        return;
    }
    
    if (!targetText) {
        showStatus("Please enter a target phrase.", "error");
        return;
    }

    setLoading(runBtn, true);
    showStatus("", "");
    
    // Create processing card
    const processingId = 'proc-' + Date.now();
    const processingHtml = `
        <div id="${processingId}" class="history-card processing-card">
            <div class="scanner-container">
                <div class="scanner-box">
                    <div class="scanner-glow"></div>
                    <div class="scanner-line"></div>
                </div>
            </div>
            <div class="processing-text">Processing Pipeline...</div>
        </div>
    `;
    historyContainer.insertAdjacentHTML('afterbegin', processingHtml);
    const procCard = document.getElementById(processingId);

    try {
        // Send request
        const response = await fetch('/api/search', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ 
                target: targetText,
                url: url,
                local_video: localVideo,
                mode: searchMode
            })
        });
        
        const data = await response.json();
        procCard.remove(); // Remove processing card
        
        if (response.ok) {
            showStatus("Pipeline completed in " + data.elapsed.toFixed(1) + "s", "success");
            const sessionId = data.session_id || "";
            renderHistoryCard(data.result, sessionId, targetText, true);
        } else {
            showStatus("Error: " + data.error, "error");
        }
    } catch (err) {
        showStatus("Network error occurred.", "error");
        if(document.getElementById(processingId)) document.getElementById(processingId).remove();
    } finally {
        setLoading(runBtn, false);
    }
});

function showStatus(message, type) {
    statusMsg.textContent = message;
    statusMsg.className = "status-msg " + type;
}

function setLoading(button, isLoading) {
    if (isLoading) {
        button.disabled = true;
        button.dataset.originalText = button.textContent;
        button.textContent = "Processing...";
        button.classList.add("loading");
    } else {
        button.disabled = false;
        button.textContent = button.dataset.originalText;
        button.classList.remove("loading");
    }
}
