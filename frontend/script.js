const videoUrlInput = document.getElementById('video-url');
const videoSelect = document.getElementById('video-select');
const searchTextInput = document.getElementById('search-text');
const searchModeSelect = document.getElementById('search-mode');
const runBtn = document.getElementById('run-btn');
const statusMsg = document.getElementById('status-msg');
const historyContainer = document.getElementById('history-container');

const historyDrawer = document.getElementById('history-drawer');
const drawerOverlay = document.getElementById('drawer-overlay');
const historyToggleBtn = document.getElementById('history-toggle-btn');
const closeHistoryBtn = document.getElementById('close-history-btn');
const mainEmptyState = document.getElementById('main-empty-state');
const currentResultContainer = document.getElementById('current-result-container');

historyToggleBtn.addEventListener('click', () => {
    historyDrawer.classList.add('open');
    drawerOverlay.classList.add('show');
});
closeHistoryBtn.addEventListener('click', () => {
    historyDrawer.classList.remove('open');
    drawerOverlay.classList.remove('show');
});
drawerOverlay.addEventListener('click', () => {
    historyDrawer.classList.remove('open');
    drawerOverlay.classList.remove('show');
});

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
        if (prepend) {
            historyContainer.insertAdjacentHTML('afterbegin', cardHtml);
            currentResultContainer.innerHTML = cardHtml;
            currentResultContainer.style.display = 'block';
            mainEmptyState.style.display = 'none';
        } else {
            historyContainer.insertAdjacentHTML('beforeend', cardHtml);
        }
    } else {
        const imgSrc = `/api/frame?id=${sessionId}&t=` + new Date().getTime();
        
        let mode = resultData.mode;
        if (!mode) {
            if (resultData.status === "ASR_ONLY_MATCH") mode = "asr_only";
            else mode = "ocr_only";
        }
        
        let methodIcon = "";
        let methodText = "";
        let methodSub = "";
        if (mode === "asr_only") {
            methodIcon = `<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 2a3 3 0 0 0-3 3v7a3 3 0 0 0 6 0V5a3 3 0 0 0-3-3Z"></path><path d="M19 10v2a7 7 0 0 1-14 0v-2"></path><line x1="12" x2="12" y1="19" y2="22"></line></svg>`;
            methodText = "VOICE";
            methodSub = "ASR ONLY";
        } else if (mode === "ocr_only") {
            methodIcon = `<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"></path><circle cx="12" cy="12" r="3"></circle></svg>`;
            methodText = "VISUAL";
            methodSub = "OCR ONLY";
        } else {
            methodIcon = `<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 15v4c0 1.1.9 2 2 2h14a2 2 0 0 0 2-2v-4M17 9l-5 5-5-5M12 12.8V2.5"/></svg>`;
            methodText = "DUAL";
            methodSub = "ASR + OCR";
        }
        
        let asdBadgeHtml = "";
        if (resultData.asd_status === "ON_SCREEN" || resultData.asd_status === "OFF_SCREEN") {
            const isOff = resultData.asd_status === "OFF_SCREEN";
            const badgeClass = isOff ? "method-badge off-screen" : "method-badge on-screen";
            const badgeText = isOff ? "OFF-SCREEN" : "ON-SCREEN";
            const badgeIcon = isOff ? `<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M1 1l22 22"></path><path d="M9 9v3a3 3 0 005.12 2.12M15 9.34V4a3 3 0 00-5.94-.6"></path><path d="M17 16.95A7 7 0 015 12v-2m14 0v2a7 7 0 01-.11 1.23"></path><line x1="12" y1="19" x2="12" y2="23"></line><line x1="8" y1="23" x2="16" y2="23"></line></svg>` : `<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 1a3 3 0 0 0-3 3v8a3 3 0 0 0 6 0V4a3 3 0 0 0-3-3z"></path><path d="M19 10v2a7 7 0 0 1-14 0v-2"></path><line x1="12" y1="19" x2="12" y2="23"></line><line x1="8" y1="23" x2="16" y2="23"></line></svg>`;
            asdBadgeHtml = `<div class="${badgeClass}">${badgeIcon} ${badgeText}</div>`;
        }

        const cardHtml = `
            <div class="history-card">
                <div class="history-image-col">
                    ${asdBadgeHtml}
                    <img src="${imgSrc}" alt="Extracted Frame" onerror="this.src=''" />
                    <div class="timestamp-overlay">${resultData.timestamp}</div>
                </div>
                <div class="history-details-col">
                    <div class="card-header">
                        <button class="icon-btn"><svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="1"></circle><circle cx="12" cy="5" r="1"></circle><circle cx="12" cy="19" r="1"></circle></svg></button>
                    </div>
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
                                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="3" width="18" height="18" rx="2" ry="2"></rect><line x1="3" y1="9" x2="21" y2="9"></line><line x1="9" y1="21" x2="9" y2="9"></line></svg>
                                <span class="history-metric-label">FRAME</span>
                            </div>
                            <span class="history-metric-value">${resultData.frame_number.toLocaleString()}</span>
                        </div>
                        <div class="history-metric-box">
                            <div class="history-metric-header">
                                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="14" r="8"></circle><line x1="12" y1="2" x2="12" y2="6"></line><line x1="8" y1="2" x2="16" y2="2"></line></svg>
                                <span class="history-metric-label">DURATION</span>
                            </div>
                            <span class="history-metric-value">${resultData.processing_time !== undefined ? resultData.processing_time + 's' : '0.0s'}</span>
                        </div>
                        <div class="history-metric-box">
                            <div class="history-metric-header">
                                ${methodIcon}
                                <span class="history-metric-label">METHOD</span>
                            </div>
                            <div class="history-metric-value">${methodText}</div>
                            <div class="metric-value-sub">${methodSub}</div>
                        </div>
                        <div class="history-metric-box">
                            <div class="history-metric-header">
                                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"></path><polyline points="22 4 12 14.01 9 11.01"></polyline></svg>
                                <span class="history-metric-label">CONFIDENCE</span>
                            </div>
                            <span class="history-metric-value success-text">${resultData.confidence_score}%</span>
                        </div>
                        <div class="history-metric-box">
                            <div class="history-metric-header">
                                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"></path><line x1="22" y1="4" x2="12" y2="14.01"></line></svg>
                                <span class="history-metric-label">TARGET</span>
                            </div>
                            <span class="history-metric-value" style="font-size: 0.95rem; line-height: 1.2; word-wrap: break-word; white-space: normal; max-width: 150px; display: inline-block;">"${targetText}"</span>
                        </div>
                    </div>
                    <div class="extracted-section">
                        <span class="extracted-label">EXTRACTED TEXT</span>
                        <div class="history-quote-box">
                            &ldquo;${resultData.extracted_text}&rdquo;
                        </div>
                    </div>
                </div>
            </div>
        `;
        if (prepend) {
            historyContainer.insertAdjacentHTML('afterbegin', cardHtml);
            currentResultContainer.innerHTML = cardHtml;
            currentResultContainer.style.display = 'block';
            mainEmptyState.style.display = 'none';
        } else {
            historyContainer.insertAdjacentHTML('beforeend', cardHtml);
        }
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
    
    // Dynamic Nodes Assembly
    let nodesHtml = `
        <div class="flow-node active processing" id="flow-node-media">
            <div class="node-badge">1</div>
            <div class="node-icon"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="2" y="2" width="20" height="20" rx="2.18" ry="2.18"></rect><line x1="7" y1="2" x2="7" y2="22"></line><line x1="17" y1="2" x2="17" y2="22"></line><line x1="2" y1="12" x2="22" y2="12"></line><line x1="2" y1="7" x2="7" y2="7"></line><line x1="2" y1="17" x2="7" y2="17"></line><line x1="17" y1="17" x2="22" y2="17"></line><line x1="17" y1="7" x2="22" y2="7"></line></svg></div>
            <div class="node-label">MEDIA</div>
        </div>
    `;
    
    let cardsHtml = `
        <div class="exec-card active" id="card-media">
            <div class="card-visual">
                <div class="video-placeholder"></div>
            </div>
            <div class="card-details">
                <h4>Loading Video</h4>
                <p>Reading video file and extracting audio...</p>
            </div>
        </div>
    `;
    
    let badgeIdx = 2;

    if (searchMode === 'asr_only' || searchMode === 'asr_ocr') {
        nodesHtml += `
            <div class="flow-connector"></div>
            <div class="flow-node" id="flow-node-asr">
                <div class="node-badge">${badgeIdx++}</div>
                <div class="node-icon"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 2a3 3 0 0 0-3 3v7a3 3 0 0 0 6 0V5a3 3 0 0 0-3-3Z"></path><path d="M19 10v2a7 7 0 0 1-14 0v-2"></path><line x1="12" y1="19" x2="12" y2="22"></line></svg></div>
                <div class="node-label">ASR VOICE</div>
            </div>
        `;
        cardsHtml += `
            <div class="exec-card" id="card-asr">
                <div class="card-visual">
                    <div style="font-size: 1.5rem; color: var(--primary-orange); letter-spacing: 2px;">||||||||||</div>
                    <div class="status-msg">Extracting speech...</div>
                    <div class="transcription-box">
                        <span id="live-typing-text">"..."</span>
                    </div>
                </div>
                <div class="card-details">
                    <h4>Extracting Voice</h4>
                    <p>Converting speech to text using ASR model...</p>
                </div>
            </div>
        `;
    }

    if (searchMode === 'ocr_only' || searchMode === 'asr_ocr') {
        nodesHtml += `
            <div class="flow-connector"></div>
            <div class="flow-node" id="flow-node-ocr">
                <div class="node-badge">${badgeIdx++}</div>
                <div class="node-icon"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M4 7V4h16v3"></path><path d="M9 20h6"></path><path d="M12 4v16"></path></svg></div>
                <div class="node-label">OCR TEXT</div>
            </div>
        `;
        cardsHtml += `
            <div class="exec-card" id="card-ocr">
                <div class="card-visual">
                    <div class="asd-visual" style="background: rgba(16,185,129,0.1); color: #10b981;">
                        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M4 7V4h16v3"></path><path d="M9 20h6"></path><path d="M12 4v16"></path></svg>
                    </div>
                    <div class="status-msg">Scanning frames...</div>
                </div>
                <div class="card-details">
                    <h4>Extracting Text</h4>
                    <p>Scanning visual frames for on-screen text...</p>
                </div>
            </div>
        `;
    }

    nodesHtml += `
        <div class="flow-connector"></div>
        <div class="flow-node" id="flow-node-asd">
            <div class="node-badge">${badgeIdx++}</div>
            <div class="node-icon"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"></path><circle cx="12" cy="7" r="4"></circle></svg></div>
            <div class="node-label">ASD SPEAKER</div>
        </div>
        <div class="flow-connector"></div>
        <div class="flow-node" id="flow-node-fuzzy">
            <div class="node-badge">${badgeIdx++}</div>
            <div class="node-icon"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="11" cy="11" r="8"></circle><line x1="21" y1="21" x2="16.65" y2="16.65"></line></svg></div>
            <div class="node-label">FUZZY MATCH</div>
        </div>
        <div class="flow-connector"></div>
        <div class="flow-node" id="flow-node-result">
            <div class="node-badge">${badgeIdx++}</div>
            <div class="node-icon"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"></path><polyline points="22 4 12 14.01 9 11.01"></polyline></svg></div>
            <div class="node-label">RESULT</div>
        </div>
    `;
    
    cardsHtml += `
        <div class="exec-card" id="card-asd">
            <div class="card-visual">
                <div class="asd-visual">
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"></path><circle cx="12" cy="7" r="4"></circle></svg>
                </div>
                <div class="status-msg">Identifying speaker...</div>
            </div>
            <div class="card-details">
                <h4>Analyzing Speaker</h4>
                <p>Detecting if the speaker is on-screen or off-screen...</p>
            </div>
        </div>
        <div class="exec-card" id="card-fuzzy">
            <div class="card-visual fuzzy-list">
                <div class="fuzzy-item"><span>Target match...</span> <span class="score">92%</span></div>
                <div class="fuzzy-item"><span>Partial match...</span> <span class="score">85%</span></div>
                <div class="fuzzy-item"><span>Low match...</span> <span class="score">40%</span></div>
                <div class="status-msg">Matching text...</div>
            </div>
            <div class="card-details">
                <h4>Fuzzy Matching</h4>
                <p>Matching extracted text with target phrase...</p>
            </div>
        </div>
        <div class="exec-card" id="card-result">
            <div class="card-visual">
                <div class="result-circle">
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3"><polyline points="20 6 9 17 4 12"></polyline></svg>
                </div>
                <div class="status-msg" style="color: #10b981;">Match Found!</div>
            </div>
            <div class="card-details">
                <h4>Pipeline Complete</h4>
                <p>Target phrase detected successfully.</p>
            </div>
        </div>
    `;

    const processingHtml = `
        <div id="${processingId}" class="history-card creative-processing-container" style="background: white; max-width: 1200px; width: 100%; padding: 2.5rem; margin: 0 auto; flex-direction: column; gap: 0;">
            <h2 class="pipeline-exec-title">Pipeline Execution in Progress</h2>
            
            <div class="pipeline-flowchart">
                ${nodesHtml}
            </div>

            <div class="pipeline-cards">
                ${cardsHtml}
            </div>
        </div>
    `;
    currentResultContainer.innerHTML = processingHtml;
    currentResultContainer.style.display = 'block';
    mainEmptyState.style.display = 'none';
    const procCard = document.getElementById(processingId);

    const allNodes = document.querySelectorAll('.flow-node');
    const allConns = document.querySelectorAll('.flow-connector');
    const allCards = document.querySelectorAll('.exec-card');
    
    // Typewriter effect setup
    const typingSpan = document.getElementById('live-typing-text');
    const wordsToType = targetText.split(' ');
    let wordIndex = 0;
    let typeInterval = null;

    let statusInterval = setInterval(async () => {
        try {
            const res = await fetch('/api/status');
            if (res.ok) {
                const data = await res.json();
                
                if (data.node === 'none') return;
                
                let foundCurrent = false;
                allNodes.forEach((node, idx) => {
                    node.classList.remove('processing');
                    
                    const cardId = node.id.replace('flow-node-', 'card-');
                    const card = document.getElementById(cardId);
                    
                    if (!foundCurrent) {
                        node.classList.add('active');
                        if (card) card.classList.add('active');
                        if (idx > 0 && allConns[idx - 1]) {
                            allConns[idx - 1].classList.add('active');
                        }
                        
                        if (node.id === 'flow-' + data.node) {
                            node.classList.add('processing');
                            
                            // Trigger type-writer effect only if on ASR
                            if (data.node === 'node-asr' && !typeInterval) {
                                typeInterval = setInterval(() => {
                                    if(wordIndex < wordsToType.length) {
                                        const currentText = wordsToType.slice(0, wordIndex+1).join(" ");
                                        typingSpan.innerHTML = `"${currentText}..."`;
                                        wordIndex++;
                                    } else {
                                        // Final output string
                                        let finalHTML = `"${wordsToType.join(" ")}"`;
                                        // Make a word orange randomly for aesthetics
                                        if (wordsToType.length > 2) {
                                            const rIdx = Math.floor(wordsToType.length/2);
                                            wordsToType[rIdx] = `<span style="color: var(--primary-orange);">${wordsToType[rIdx]}</span>`;
                                            finalHTML = `"${wordsToType.join(" ")}"`;
                                        }
                                        typingSpan.innerHTML = finalHTML;
                                        clearInterval(typeInterval);
                                    }
                                }, 800);
                            }
                            
                            foundCurrent = true;
                        }
                    } else {
                        node.classList.remove('active');
                        if (card) card.classList.remove('active');
                        if (idx > 0 && allConns[idx - 1]) {
                            allConns[idx - 1].classList.remove('active');
                        }
                    }
                });
            }
        } catch (e) {}
    }, 1000);

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
        if (procCard) procCard.remove();
        
        if (response.ok) {
            showStatus("Pipeline completed in " + data.elapsed.toFixed(1) + "s", "success");
            const sessionId = data.session_id || "";
            renderHistoryCard(data.result, sessionId, targetText, true);
        } else {
            showStatus("Error: " + data.error, "error");
            currentResultContainer.style.display = 'none';
            mainEmptyState.style.display = 'flex';
        }
    } catch (err) {
        showStatus("Network error occurred.", "error");
        if(document.getElementById(processingId)) document.getElementById(processingId).remove();
        currentResultContainer.style.display = 'none';
        mainEmptyState.style.display = 'flex';
    } finally {
        setLoading(runBtn, false);
        if (typeof statusInterval !== 'undefined') clearInterval(statusInterval);
        if (typeof typeInterval !== 'undefined' && typeInterval) clearInterval(typeInterval);
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
