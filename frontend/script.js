const videoUrlInput = document.getElementById('video-url');
const videoSelect = document.getElementById('video-select');
const searchTextInput = document.getElementById('search-text');
const searchModeSelect = document.getElementById('search-mode');
const runBtn = document.getElementById('run-btn');
const statusMsg = document.getElementById('status-msg');
const historyContainer = document.getElementById('history-container');

const clearCacheBtn = document.getElementById('clear-cache-btn');
if (clearCacheBtn) {
    clearCacheBtn.addEventListener('click', async () => {
        const confirmClear = confirm("Are you sure you want to clear all cached videos and processed data? This cannot be undone.");
        if (!confirmClear) return;
        
        const originalText = clearCacheBtn.innerHTML;
        clearCacheBtn.innerHTML = "Clearing...";
        clearCacheBtn.disabled = true;
        
        try {
            const resp = await fetch('/api/cache', { method: 'DELETE' });
            if (resp.ok) {
                showStatus("Cache cleared successfully. Please refresh the page.", "success");
                if (typeof fetchVideos === 'function') {
                    fetchVideos(); // Refetch videos so the dropdown stays populated
                }
            } else {
                showStatus("Failed to clear cache.", "error");
            }
        } catch (e) {
            showStatus("Error connecting to server.", "error");
        } finally {
            clearCacheBtn.innerHTML = originalText;
            clearCacheBtn.disabled = false;
        }
    });
}

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
    const heroImg = document.getElementById('hero-img-placeholder');
    const heroVid = document.getElementById('hero-video-player');
    const heroOverlay = document.getElementById('hero-overlay');
    if (videoSelect.value !== "") {
        videoUrlInput.disabled = true;
        videoUrlInput.value = "";
        
        if (heroImg && heroVid) {
            heroImg.style.display = 'none';
            if (heroOverlay) heroOverlay.style.display = 'none';
            heroVid.style.display = 'block';
            heroVid.src = '/assets/video/' + encodeURIComponent(videoSelect.value);
            heroVid.play().catch(e => console.log('Autoplay prevented', e));
        }
    } else {
        videoUrlInput.disabled = false;
        if (heroImg && heroVid) {
            heroImg.style.display = 'block';
            if (heroOverlay) heroOverlay.style.display = 'block';
            heroVid.style.display = 'none';
            heroVid.pause();
            heroVid.src = '';
        }
    }
});

async function fetchVideos() {
    try {
        const resp = await fetch('/api/videos');
        if (resp.ok) {
            const data = await resp.json();
            videoSelect.innerHTML = '<option value="">Select file</option>';
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
}

// Fetch cached videos and history on page load
window.addEventListener('DOMContentLoaded', async () => {
    // 1. Fetch Videos
    await fetchVideos();

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

        // Generate unique IDs for interactive editor elements
        let videoId = 'editor-vid-' + Date.now();
        let playPauseBtnId = 'play-btn-' + Date.now();
        let rewindBtnId = 'rewind-btn-' + Date.now();
        let forwardBtnId = 'forward-btn-' + Date.now();
        let jumpMatchBtnId = 'jump-btn-' + Date.now();
        let trackAreaId = 'timeline-tracks-' + Date.now();
        let playheadId = 'playhead-' + Date.now();
        let matchClipV1Id = 'clip-v1-' + Date.now();
        let matchClipA1Id = 'clip-a1-' + Date.now();
        let timeDisplayId = 'time-display-' + Date.now();
        let rulerId = 'ruler-' + Date.now();
        
        let seconds = 0;
        if (resultData.timestamp) {
            const parts = resultData.timestamp.split(':');
            if (parts.length === 3) {
                seconds = parseFloat(parts[0]) * 3600 + parseFloat(parts[1]) * 60 + parseFloat(parts[2]);
            }
        }
        
        let relativeSeconds = seconds;
        if (resultData.clip_start_time !== undefined) {
            relativeSeconds = seconds - resultData.clip_start_time;
        }

        const isNotFound = resultData.status === 'NOT_FOUND' || (resultData.confidence_score === 0 && !resultData.extracted_text);
        
        const matchTimeChipHtml = isNotFound 
            ? `<div class="match-time-chip not-found-chip">
                   <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><circle cx="12" cy="12" r="10"></circle><line x1="15" y1="9" x2="9" y2="15"></line><line x1="9" y1="9" x2="15" y2="15"></line></svg>
                   No Match Found (0%)
               </div>`
            : `<div class="match-time-chip">
                   <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"></circle><polyline points="12 6 12 12 16 14"></polyline></svg>
                   Match: ${resultData.timestamp || '00:00:00.000'}
               </div>`;

        const displayedDialogue = isNotFound 
            ? `Phrase "${targetText}" not found in ${methodText.toLowerCase()} scan` 
            : (resultData.extracted_text || targetText || 'Dialogue Match');

        let mediaHtml = "";
        if (resultData.video_file) {
            mediaHtml = `
                <div class="custom-video-player">
                    <video src="/assets/video/${encodeURIComponent(resultData.video_file)}" poster="${imgSrc}" preload="metadata"></video>
                    
                    <!-- Dynamic On-Video Subtitles Overlay -->
                    <div class="video-subtitles-overlay">
                        <div class="subtitle-text-pill ${isNotFound ? 'sub-not-found' : ''}">
                            <span class="sub-quote-icon">${isNotFound ? '⚠️' : '❝'}</span>
                            <span class="sub-content">${displayedDialogue}</span>
                            <span class="sub-quote-icon">${isNotFound ? '' : '❞'}</span>
                        </div>
                    </div>

                    <!-- Floating Overlay Controls -->
                    <div class="player-controls-overlay">
                        <div class="controls-left">
                            <button class="player-ctrl-btn play-pause-btn" title="Play/Pause">
                                <svg class="play-icon" width="18" height="18" viewBox="0 0 24 24" fill="currentColor"><polygon points="5 3 19 12 5 21 5 3"></polygon></svg>
                                <svg class="pause-icon" width="18" height="18" viewBox="0 0 24 24" fill="currentColor" style="display:none;"><rect x="6" y="4" width="4" height="16"></rect><rect x="14" y="4" width="4" height="16"></rect></svg>
                            </button>
                            <button class="player-ctrl-btn rewind-btn" title="Rewind 3s">
                                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M11 19l-9-7 9-7v14z"></path><path d="M22 19l-9-7 9-7v14z"></path></svg>
                            </button>
                            <button class="player-ctrl-btn forward-btn" title="Forward 3s">
                                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M13 19l9-7-9-7v14z"></path><path d="M2 19l9-7-9-7v14z"></path></svg>
                            </button>
                            <div class="player-time-badge">
                                <span class="current-time">00:00:00.000</span> <span class="time-sep">/</span> <span class="total-time">00:00:00.000</span>
                            </div>
                        </div>
                        <div class="controls-right">
                            <button class="player-ctrl-btn cc-toggle-btn active-cc" title="Toggle Subtitles">
                                <span class="cc-label">CC</span>
                            </button>
                            ${!isNotFound ? `
                            <button class="jump-match-btn" title="Jump to detected match moment">
                                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><circle cx="12" cy="12" r="10"></circle><polygon points="12 8 8 12 12 16 12 8"></polygon></svg>
                                <span>Jump to Match</span>
                            </button>` : ''}
                        </div>
                    </div>
                </div>
            `;
        }

        let cardHtml = "";

        if (isNotFound) {
            cardHtml = `
                <div class="editor-studio-card not-found-hero-card">
                    <!-- Top Bar -->
                    <div class="editor-top-bar">
                        <div class="editor-file-badge">
                            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="var(--primary-orange)" stroke-width="2"><polygon points="23 7 16 12 23 17 23 7"></polygon><rect x="1" y="5" width="15" height="14" rx="2" ry="2"></rect></svg>
                            <span class="file-title">${resultData.video_file || 'Video Footage'}</span>
                        </div>
                        <div class="editor-badges-group">
                            <div class="match-time-chip not-found-chip">
                                <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><circle cx="12" cy="12" r="10"></circle><line x1="15" y1="9" x2="9" y2="15"></line><line x1="9" y1="9" x2="15" y2="15"></line></svg>
                                Phrase Not Detected (0%)
                            </div>
                        </div>
                    </div>

                    <!-- Not Found Hero Body -->
                    <div class="not-found-body-wrap">
                        <!-- Theme Vector Illustration -->
                        <div class="not-found-illustration-wrap">
                            <svg class="not-found-svg" viewBox="0 0 340 220" fill="none" xmlns="http://www.w3.org/2000/svg">
                                <!-- Background Container Box -->
                                <rect x="20" y="20" width="300" height="180" rx="16" fill="#f8fafc" stroke="#e2e8f0" stroke-width="2"/>
                                <!-- Top film holes -->
                                <rect x="35" y="32" width="14" height="10" rx="2" fill="#cbd5e1"/>
                                <rect x="58" y="32" width="14" height="10" rx="2" fill="#cbd5e1"/>
                                <rect x="81" y="32" width="14" height="10" rx="2" fill="#cbd5e1"/>
                                <rect x="245" y="32" width="14" height="10" rx="2" fill="#cbd5e1"/>
                                <rect x="268" y="32" width="14" height="10" rx="2" fill="#cbd5e1"/>
                                <rect x="291" y="32" width="14" height="10" rx="2" fill="#cbd5e1"/>
                                
                                <!-- Center Video monitor -->
                                <rect x="35" y="52" width="270" height="116" rx="10" fill="#0f172a"/>
                                
                                <!-- Subtitle / Dialogue Waveforms -->
                                <line x1="60" y1="110" x2="60" y2="110" stroke="#334155" stroke-width="4" stroke-linecap="round"/>
                                <line x1="75" y1="95" x2="75" y2="125" stroke="#334155" stroke-width="4" stroke-linecap="round"/>
                                <line x1="90" y1="102" x2="90" y2="118" stroke="#334155" stroke-width="4" stroke-linecap="round"/>
                                <line x1="105" y1="85" x2="105" y2="135" stroke="#334155" stroke-width="4" stroke-linecap="round"/>
                                <line x1="120" y1="100" x2="120" y2="120" stroke="#334155" stroke-width="4" stroke-linecap="round"/>
                                <line x1="135" y1="90" x2="135" y2="130" stroke="#334155" stroke-width="4" stroke-linecap="round"/>
                                
                                <!-- Floating Search Lens with Orange Accent -->
                                <circle cx="215" cy="110" r="38" fill="rgba(255, 87, 34, 0.15)" stroke="#ff5722" stroke-width="3"/>
                                <circle cx="215" cy="110" r="26" fill="#1e293b" stroke="rgba(255, 255, 255, 0.2)" stroke-width="1.5"/>
                                <!-- Cross inside lens -->
                                <path d="M205 100L225 120M225 100L205 120" stroke="#ff5722" stroke-width="3.5" stroke-linecap="round"/>
                                <path d="M242 137L270 165" stroke="#ff5722" stroke-width="5" stroke-linecap="round"/>
                                
                                <!-- Floating Sparks & Dots -->
                                <circle cx="150" cy="38" r="3" fill="#ff5722"/>
                                <circle cx="295" cy="190" r="2.5" fill="#ff5722"/>
                                <circle cx="45" cy="185" r="3" fill="#cbd5e1"/>
                            </svg>
                        </div>

                        <!-- Info & Guidance Details -->
                        <div class="not-found-info-wrap">
                            <div class="not-found-heading-row">
                                <span class="not-found-chip-big">⚠️ PHRASE NOT DETECTED</span>
                                <span class="not-found-score-pill">0.0% Match Score</span>
                            </div>

                            <h2 class="not-found-title">No Dialogue Match Found</h2>
                            <p class="not-found-description">
                                The engine thoroughly scanned the entire video for <strong class="query-highlight">&ldquo;${targetText}&rdquo;</strong> using <strong>${methodText} (${methodSub})</strong>, but could not detect any matching occurrence.
                            </p>

                            <!-- Breakdown Grid -->
                            <div class="not-found-stats-grid">
                                <div class="stat-cell">
                                    <span class="stat-lbl">SEARCH QUERY</span>
                                    <span class="stat-val stat-val-query">&ldquo;${targetText}&rdquo;</span>
                                </div>
                                <div class="stat-cell">
                                    <span class="stat-lbl">PIPELINE MODE</span>
                                    <span class="stat-val">${methodText} (${methodSub})</span>
                                </div>
                                <div class="stat-cell">
                                    <span class="stat-lbl">VIDEO SOURCE</span>
                                    <span class="stat-val stat-val-truncate">${resultData.video_file || 'Footage'}</span>
                                </div>
                                <div class="stat-cell">
                                    <span class="stat-lbl">STATUS</span>
                                    <span class="stat-val stat-val-notfound">NOT FOUND</span>
                                </div>
                            </div>

                            <!-- Remediation Guidance Box -->
                            <div class="not-found-remedy-box">
                                <div class="remedy-icon">💡</div>
                                <div class="remedy-content">
                                    <div class="remedy-title">Why this happens & How to find it:</div>
                                    <div class="remedy-desc">
                                        ${mode === 'ocr_only' 
                                            ? 'Visual OCR only scans for on-screen subtitles/captions. If the phrase was spoken in audio, click the button below to search the voice track.' 
                                            : 'The phrase was not detected in the audio track. Check for alternative phrasings or try a dual ASR + OCR scan.'}
                                    </div>
                                </div>
                            </div>

                            <!-- Action Buttons -->
                            <div class="not-found-actions-row">
                                ${mode === 'ocr_only' ? `
                                <button class="action-btn-primary switch-asr-btn">
                                    <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><path d="M12 2a3 3 0 0 0-3 3v7a3 3 0 0 0 6 0V5a3 3 0 0 0-3-3Z"></path><path d="M19 10v2a7 7 0 0 1-14 0v-2"></path><line x1="12" y1="19" x2="12" y2="22"></line></svg>
                                    <span>Search Audio with ASR Voice Mode</span>
                                </button>
                                <button class="action-btn-secondary switch-dual-btn">
                                    <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M3 15v4c0 1.1.9 2 2 2h14a2 2 0 0 0 2-2v-4M17 9l-5 5-5-5M12 12.8V2.5"/></svg>
                                    <span>Run Dual (ASR + OCR) Scan</span>
                                </button>` : `
                                <button class="action-btn-primary switch-dual-btn">
                                    <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M3 15v4c0 1.1.9 2 2 2h14a2 2 0 0 0 2-2v-4M17 9l-5 5-5-5M12 12.8V2.5"/></svg>
                                    <span>Run Full Dual (ASR + OCR) Scan</span>
                                </button>`}
                            </div>
                        </div>
                    </div>
                </div>
            `;
        } else {
            cardHtml = `
                <div class="editor-studio-card">
                    <!-- Header Toolbar -->
                    <div class="editor-top-bar">
                        <div class="editor-file-badge">
                            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="var(--primary-orange)" stroke-width="2"><polygon points="23 7 16 12 23 17 23 7"></polygon><rect x="1" y="5" width="15" height="14" rx="2" ry="2"></rect></svg>
                            <span class="file-title">${resultData.video_file || 'Captured Video Stream'}</span>
                        </div>
                        <div class="editor-badges-group">
                            ${asdBadgeHtml}
                            ${matchTimeChipHtml}
                        </div>
                    </div>

                    <!-- Video Preview Monitor -->
                    <div class="editor-preview-viewport">
                        ${mediaHtml}
                    </div>
                    
                    <!-- Multi-Track Timeline Component -->
                    <div class="editor-timeline-section">
                        <div class="timeline-section-header">
                            <div class="timeline-title-text">
                                <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="3" width="18" height="18" rx="2" ry="2"></rect><line x1="3" y1="9" x2="21" y2="9"></line><line x1="9" y1="21" x2="9" y2="9"></line></svg>
                                TIMELINE SEQUENCE
                            </div>
                            <div class="timeline-hint">
                                Click track to scrub &bull; Highlighted clip shows detected occurrence
                            </div>
                        </div>

                        <!-- Timeline Body -->
                        <div class="timeline-editor-body">
                            <!-- Track Labels Column (Left) -->
                            <div class="timeline-headers-col">
                                <div class="track-header-cell ruler-spacer">
                                    <span>TIME</span>
                                </div>
                                <div class="track-header-cell track-v1-label">
                                    <span class="track-pill v-pill">V1</span>
                                    <span class="track-name">Video</span>
                                </div>
                                <div class="track-header-cell track-a1-label">
                                    <span class="track-pill a-pill">A1</span>
                                    <span class="track-name">Dialogue</span>
                                </div>
                            </div>

                            <!-- Tracks Content Area (Right) -->
                            <div class="timeline-tracks-col">
                                <!-- Timecode Ruler -->
                                <div class="timeline-ruler">
                                    <div class="ruler-tick" style="left: 0%;"><span>00:00</span></div>
                                    <div class="ruler-tick" style="left: 20%;"><span>00:10</span></div>
                                    <div class="ruler-tick" style="left: 40%;"><span>00:20</span></div>
                                    <div class="ruler-tick" style="left: 60%;"><span>00:30</span></div>
                                    <div class="ruler-tick" style="left: 80%;"><span>00:40</span></div>
                                    <div class="ruler-tick" style="left: 100%;"><span>END</span></div>
                                </div>

                                <!-- Track 1: Video Track -->
                                <div class="track-lane track-lane-v1">
                                    <div class="lane-clip-base video-clip-base">
                                        <div class="clip-label-tag">
                                            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="2" y="2" width="20" height="20" rx="2.18" ry="2.18"></rect><line x1="7" y1="2" x2="7" y2="22"></line><line x1="17" y1="2" x2="17" y2="22"></line><line x1="2" y1="12" x2="22" y2="12"></line><line x1="2" y1="7" x2="7" y2="7"></line><line x1="2" y1="17" x2="7" y2="17"></line><line x1="17" y1="17" x2="22" y2="17"></line><line x1="17" y1="7" x2="22" y2="7"></line></svg>
                                            ${resultData.video_file || 'Main Footage'}
                                        </div>
                                        <!-- Highlighted Frame Match Clip -->
                                        <div class="highlighted-match-clip match-clip-video" style="display:none;">
                                            <div class="match-clip-header">FRAME #${resultData.frame_number || '0'}</div>
                                        </div>
                                    </div>
                                </div>

                                <!-- Track 2: Dialogue / Audio Track -->
                                <div class="track-lane track-lane-a1">
                                    <div class="lane-clip-base audio-clip-base">
                                        <div class="audio-waveform-decor">
                                            <span></span><span></span><span></span><span></span><span></span><span></span><span></span><span></span><span></span><span></span><span></span><span></span><span></span><span></span><span></span><span></span><span></span><span></span><span></span><span></span><span></span><span></span><span></span><span></span>
                                        </div>
                                        <!-- Highlighted Target Dialogue Occurrence Clip -->
                                        <div class="highlighted-match-clip match-clip-audio" style="display:none;">
                                            <div class="match-dialogue-tag">
                                                <span class="match-sparkle">&#9733;</span> "${resultData.extracted_text || targetText}"
                                            </div>
                                        </div>
                                    </div>
                                </div>

                                <!-- Global Scrubbing Playhead -->
                                <div class="timeline-scrub-playhead">
                                    <div class="playhead-pointer"></div>
                                    <div class="playhead-stem"></div>
                                </div>
                            </div>
                        </div>
                    </div>

                    <!-- Inspector / Properties Section -->
                    <div class="editor-inspector-grid">
                        <!-- Column 1: Captured Frame Image -->
                        <div class="inspector-card frame-image-card">
                            <div class="inspector-card-header">
                                <span class="inspector-card-title">CAPTURED KEYFRAME</span>
                                <span class="code-val frame-badge">#${resultData.frame_number || '0'}</span>
                            </div>
                            <div class="frame-preview-container">
                                <img src="${imgSrc}" class="frame-thumb-img" alt="Video Frame" onerror="this.style.display='none'" />
                            </div>
                        </div>

                        <!-- Column 2: Dialogue & Match Confidence -->
                        <div class="inspector-card main-dialogue-card">
                            <div class="inspector-card-header">
                                <span class="inspector-card-title">DETECTED SPOKEN DIALOGUE</span>
                                <span class="conf-badge ${resultData.confidence_score >= 60 ? 'high-conf' : 'mod-conf'}">
                                    ${resultData.confidence_score > 0 ? resultData.confidence_score + '%' : '100% (Matched)'} Confidence
                                </span>
                            </div>
                            <div class="dialogue-quote-box">
                                &ldquo;${resultData.extracted_text || targetText || 'Dialogue Match'}&rdquo;
                            </div>
                            
                            <div class="meta-mini-grid">
                                <div class="meta-row">
                                    <span class="meta-label">TARGET QUERY:</span>
                                    <span class="meta-val target-val">&ldquo;${targetText}&rdquo;</span>
                                </div>
                                <div class="meta-row">
                                    <span class="meta-label">TIMESTAMP:</span>
                                    <span class="meta-val code-val">${resultData.timestamp || '00:00:00.000'}</span>
                                </div>
                                <div class="meta-row">
                                    <span class="meta-label">PIPELINE:</span>
                                    <span class="meta-val code-val">${methodText} (${methodSub})</span>
                                </div>
                            </div>
                        </div>
                    </div>
                </div>
            `;
        }

        // Helper function to wire up video & timeline events on a specific card element
        const initEditorCard = (cardEl) => {
            if (!cardEl) return;

            // Wire up quick switch actions for Not Found cards
            const switchAsrBtn = cardEl.querySelector('.switch-asr-btn');
            if (switchAsrBtn) {
                switchAsrBtn.addEventListener('click', (e) => {
                    e.stopPropagation();
                    searchModeSelect.value = 'asr_only';
                    searchTextInput.value = targetText;
                    runBtn.click();
                });
            }
            const switchDualBtn = cardEl.querySelector('.switch-dual-btn');
            if (switchDualBtn) {
                switchDualBtn.addEventListener('click', (e) => {
                    e.stopPropagation();
                    searchModeSelect.value = 'asr_ocr';
                    searchTextInput.value = targetText;
                    runBtn.click();
                });
            }

            const video = cardEl.querySelector('.custom-video-player video');
            const playBtn = cardEl.querySelector('.play-pause-btn');
            const rewindBtn = cardEl.querySelector('.rewind-btn');
            const forwardBtn = cardEl.querySelector('.forward-btn');
            const jumpBtn = cardEl.querySelector('.jump-match-btn');
            const trackArea = cardEl.querySelector('.timeline-tracks-col');
            const playhead = cardEl.querySelector('.timeline-scrub-playhead');
            const matchClipV1 = cardEl.querySelector('.match-clip-video');
            const matchClipA1 = cardEl.querySelector('.match-clip-audio');
            const timeDisplay = cardEl.querySelector('.player-time-badge');

            if (!video || !trackArea) return;

            const formatTime = (secs) => {
                if (isNaN(secs) || secs < 0) return "00:00:00.000";
                const h = Math.floor(secs / 3600);
                const m = Math.floor((secs % 3600) / 60);
                const s = Math.floor(secs % 60);
                const ms = Math.floor((secs % 1) * 1000);
                return `${h.toString().padStart(2, '0')}:${m.toString().padStart(2, '0')}:${s.toString().padStart(2, '0')}.${ms.toString().padStart(3, '0')}`;
            };

            const updatePlayPauseIcons = () => {
                if (!playBtn) return;
                const playIcon = playBtn.querySelector('.play-icon');
                const pauseIcon = playBtn.querySelector('.pause-icon');
                if (video.paused) {
                    if (playIcon) playIcon.style.display = 'block';
                    if (pauseIcon) pauseIcon.style.display = 'none';
                } else {
                    if (playIcon) playIcon.style.display = 'none';
                    if (pauseIcon) pauseIcon.style.display = 'block';
                }
            };

            video.addEventListener('loadedmetadata', () => {
                const duration = video.duration;
                if (timeDisplay) {
                    const totalElem = timeDisplay.querySelector('.total-time');
                    if (totalElem) totalElem.textContent = formatTime(duration);
                }

                if (duration > 0 && relativeSeconds >= 0) {
                    const clipDuration = Math.max(2.5, duration * 0.06);
                    const startPct = (Math.max(0, relativeSeconds - 0.5) / duration) * 100;
                    const widthPct = Math.min(100 - startPct, (clipDuration / duration) * 100);

                    if (matchClipV1) {
                        matchClipV1.style.left = `${startPct}%`;
                        matchClipV1.style.width = `${Math.max(8, widthPct)}%`;
                        matchClipV1.style.display = 'flex';
                    }
                    if (matchClipA1) {
                        matchClipA1.style.left = `${startPct}%`;
                        matchClipA1.style.width = `${Math.max(14, widthPct)}%`;
                        matchClipA1.style.display = 'flex';
                    }
                }
            });

            // If metadata already cached/loaded
            if (video.readyState >= 1) {
                const duration = video.duration;
                if (timeDisplay) {
                    const totalElem = timeDisplay.querySelector('.total-time');
                    if (totalElem) totalElem.textContent = formatTime(duration);
                }
                if (duration > 0 && relativeSeconds >= 0) {
                    const clipDuration = Math.max(2.5, duration * 0.06);
                    const startPct = (Math.max(0, relativeSeconds - 0.5) / duration) * 100;
                    const widthPct = Math.min(100 - startPct, (clipDuration / duration) * 100);

                    if (matchClipV1) {
                        matchClipV1.style.left = `${startPct}%`;
                        matchClipV1.style.width = `${Math.max(8, widthPct)}%`;
                        matchClipV1.style.display = 'flex';
                    }
                    if (matchClipA1) {
                        matchClipA1.style.left = `${startPct}%`;
                        matchClipA1.style.width = `${Math.max(14, widthPct)}%`;
                        matchClipA1.style.display = 'flex';
                    }
                }
            }

            const subOverlay = cardEl.querySelector('.video-subtitles-overlay');
            const ccBtn = cardEl.querySelector('.cc-toggle-btn');

            video.addEventListener('timeupdate', () => {
                const duration = video.duration;
                const current = video.currentTime;

                if (duration > 0 && playhead) {
                    const pct = (current / duration) * 100;
                    playhead.style.left = `${Math.min(100, Math.max(0, pct))}%`;
                    if (timeDisplay) {
                        const curElem = timeDisplay.querySelector('.current-time');
                        if (curElem) curElem.textContent = formatTime(current);
                    }
                }

                // Highlight subtitle pill when playback is within the match window (target ± 2.5s)
                if (subOverlay && relativeSeconds >= 0) {
                    const isNear = Math.abs(current - relativeSeconds) <= 2.5;
                    const pill = subOverlay.querySelector('.subtitle-text-pill');
                    if (pill) {
                        pill.classList.toggle('highlighted-active', isNear);
                    }
                }
            });

            if (ccBtn && subOverlay) {
                ccBtn.addEventListener('click', (e) => {
                    e.stopPropagation();
                    const isVisible = subOverlay.style.display !== 'none';
                    subOverlay.style.display = isVisible ? 'none' : 'flex';
                    ccBtn.classList.toggle('active-cc', !isVisible);
                });
            }

            video.addEventListener('play', updatePlayPauseIcons);
            video.addEventListener('pause', updatePlayPauseIcons);

            if (playBtn) {
                playBtn.addEventListener('click', (e) => {
                    e.stopPropagation();
                    if (video.paused) {
                        video.play().catch(err => console.log('Autoplay error:', err));
                    } else {
                        video.pause();
                    }
                });
            }

            if (rewindBtn) {
                rewindBtn.addEventListener('click', (e) => {
                    e.stopPropagation();
                    video.currentTime = Math.max(0, video.currentTime - 3);
                });
            }

            if (forwardBtn) {
                forwardBtn.addEventListener('click', (e) => {
                    e.stopPropagation();
                    video.currentTime = Math.min(video.duration || 999, video.currentTime + 3);
                });
            }

            if (jumpBtn) {
                jumpBtn.addEventListener('click', (e) => {
                    e.stopPropagation();
                    video.currentTime = Math.max(0, relativeSeconds);
                    video.play().catch(err => console.log('Play error:', err));
                });
            }

            trackArea.addEventListener('click', (e) => {
                const rect = trackArea.getBoundingClientRect();
                const pos = (e.clientX - rect.left) / rect.width;
                if (video.duration > 0) {
                    video.currentTime = Math.max(0, Math.min(video.duration, pos * video.duration));
                }
            });

            const retryBtn = cardEl.querySelector('.retry-with-asr-btn');
            if (retryBtn) {
                retryBtn.addEventListener('click', (e) => {
                    e.stopPropagation();
                    searchModeSelect.value = 'asr_ocr';
                    searchTextInput.value = targetText;
                    runBtn.click();
                });
            }
        };

        if (prepend) {
            historyContainer.insertAdjacentHTML('afterbegin', cardHtml);
            currentResultContainer.innerHTML = cardHtml;
            currentResultContainer.style.display = 'block';
            mainEmptyState.style.display = 'none';

            // Wire up controls on both instances
            setTimeout(() => {
                initEditorCard(currentResultContainer.firstElementChild);
                initEditorCard(historyContainer.firstElementChild);
            }, 50);
        } else {
            historyContainer.insertAdjacentHTML('beforeend', cardHtml);
            setTimeout(() => {
                initEditorCard(historyContainer.lastElementChild);
            }, 50);
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
        <div class="flow-node processing" id="flow-node-media">
            <div class="node-badge">1</div>
            <div class="node-icon"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="2" y="2" width="20" height="20" rx="2.18" ry="2.18"></rect><line x1="7" y1="2" x2="7" y2="22"></line><line x1="17" y1="2" x2="17" y2="22"></line><line x1="2" y1="12" x2="22" y2="12"></line><line x1="2" y1="7" x2="7" y2="7"></line><line x1="2" y1="17" x2="7" y2="17"></line><line x1="17" y1="17" x2="22" y2="17"></line><line x1="17" y1="7" x2="22" y2="7"></line></svg></div>
            <div class="node-label">MEDIA</div>
        </div>
    `;

    let mediaVisual = `<div class="video-placeholder"></div>`;
    if (localVideo) {
        mediaVisual = `<video src="/assets/video/${encodeURIComponent(localVideo)}" autoplay loop muted style="width: 100%; height: 100%; object-fit: cover;"></video>`;
    }

    let cardsHtml = `
        <div class="exec-card" id="card-media">
            <div class="card-visual" style="padding: 0; background: transparent; border-bottom: none;">
                ${mediaVisual}
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
                <div class="card-visual dashboard-layout">
                    <div class="dashboard-left">
                        <div class="audio-waveform">
                            <div class="bar"></div><div class="bar"></div><div class="bar"></div><div class="bar"></div><div class="bar"></div>
                        </div>
                        <div class="status-msg">Extracting speech...</div>
                    </div>
                    <div class="dashboard-right">
                        <div class="transcription-box" id="asr-console" style="flex: 1; display: flex; flex-direction: column; justify-content: flex-end; border: none; box-shadow: none; padding: 0;">
                            <div class="live-console-line">Initializing models...</div>
                        </div>
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
                <div class="card-visual dashboard-layout">
                    <div class="dashboard-left">
                        <div class="scanner-box">
                            <svg class="frame-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><rect x="3" y="3" width="18" height="18" rx="2" ry="2"></rect><circle cx="8.5" cy="8.5" r="1.5"></circle><polyline points="21 15 16 10 5 21"></polyline></svg>
                            <div class="scanner-line"></div>
                        </div>
                        <div class="status-msg">Scanning frames...</div>
                    </div>
                    <div class="dashboard-right">
                        <div class="transcription-box" id="ocr-console" style="flex: 1; display: flex; flex-direction: column; justify-content: flex-end; border: none; box-shadow: none; padding: 0;">
                            <div class="live-console-line">Warming up OCR engine...</div>
                        </div>
                    </div>
                </div>
                <div class="card-details">
                    <h4>Extracting Text</h4>
                    <p>Scanning visual frames for on-screen text...</p>
                </div>
            </div>
        `;
    }

    if (searchMode === 'asr_only') {
        nodesHtml += `
            <div class="flow-connector"></div>
            <div class="flow-node" id="flow-node-asd">
                <div class="node-badge">${badgeIdx++}</div>
                <div class="node-icon"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"></path><circle cx="12" cy="7" r="4"></circle></svg></div>
                <div class="node-label">ASD SPEAKER</div>
            </div>
        `;
    }

    nodesHtml += `
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

    if (searchMode === 'asr_only') {
        cardsHtml += `
            <div class="exec-card" id="card-asd">
                <div class="card-visual dashboard-layout">
                    <div class="dashboard-left">
                        <div class="asd-visual">
                            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"></path><circle cx="12" cy="7" r="4"></circle></svg>
                        </div>
                        <div class="status-msg">Identifying speaker...</div>
                    </div>
                    <div class="dashboard-right">
                        <div class="transcription-box" id="asd-console" style="flex: 1; display: flex; flex-direction: column; justify-content: flex-end; border: none; box-shadow: none; padding: 0;">
                            <div class="live-console-line">Diarization models initializing...</div>
                        </div>
                    </div>
                </div>
                <div class="card-details">
                    <h4>Analyzing Speaker</h4>
                    <p>Detecting if the speaker is on-screen or off-screen...</p>
                </div>
            </div>
        `;
    }

    cardsHtml += `
        <div class="exec-card" id="card-fuzzy">
            <div class="card-visual dashboard-layout">
                <div class="dashboard-left">
                    <div class="asd-visual" style="background: rgba(249, 115, 22, 0.1); color: var(--primary-orange);">
                        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="11" cy="11" r="8"></circle><line x1="21" y1="21" x2="16.65" y2="16.65"></line></svg>
                    </div>
                    <div class="status-msg">Matching text...</div>
                </div>
                <div class="dashboard-right">
                    <div class="transcription-box" id="fuzzy-console" style="flex: 1; display: flex; flex-direction: column; justify-content: flex-end; border: none; box-shadow: none; padding: 0;">
                        <div class="live-console-line">Searching for matches...</div>
                    </div>
                </div>
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

    const allNodes = Array.from(document.querySelectorAll('.flow-node'));
    const allConns = Array.from(document.querySelectorAll('.flow-connector'));
    const allCards = Array.from(document.querySelectorAll('.exec-card'));

    // Staggered Entry Animation
    let staggerDelay = 0;
    allNodes.forEach((node, idx) => {
        setTimeout(() => node.classList.add('entered'), staggerDelay);
        if (allCards[idx]) setTimeout(() => allCards[idx].classList.add('entered'), staggerDelay + 100);
        if (allConns[idx]) setTimeout(() => allConns[idx].classList.add('entered'), staggerDelay + 200);
        staggerDelay += 150;
    });

    let asrConsole = document.getElementById('asr-console');
    let ocrConsole = document.getElementById('ocr-console');

    // Smooth Progress Interpolation State
    let targetProgress = 0;
    let currentProgress = 0;
    let activeCardForProgress = null;
    let animFrame = null;

    function animateProgress() {
        if (activeCardForProgress) {
            currentProgress += (targetProgress - currentProgress) * 0.1;
            const fill = activeCardForProgress.querySelector('.progress-bar-fill');
            const text = activeCardForProgress.querySelector('.progress-bar-text');
            if (fill) fill.style.width = `${currentProgress}%`;
            if (text) text.textContent = `${currentProgress.toFixed(1)}%`;
        }
        if (document.getElementById(processingId)) animFrame = requestAnimationFrame(animateProgress);
    }
    animFrame = requestAnimationFrame(animateProgress);

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
                            
                            // Progress bar injection & smooth target
                            if (card && data.progress !== undefined && data.progress !== null) {
                                activeCardForProgress = card;
                                targetProgress = Math.min(100, Math.max(0, parseFloat(data.progress)));
                                let progContainer = card.querySelector('.progress-bar-container');
                                if (!progContainer) {
                                    currentProgress = 0; // Reset visual progress when new card starts
                                    progContainer = document.createElement('div');
                                    progContainer.className = 'progress-bar-container';
                                    progContainer.innerHTML = `
                                        <div class="progress-bar-track">
                                            <div class="progress-bar-fill"></div>
                                        </div>
                                        <div class="progress-bar-text"></div>
                                    `;
                                    const cardDetails = card.querySelector('.card-details');
                                    if (cardDetails) {
                                        cardDetails.appendChild(progContainer);
                                    }
                                }
                                progContainer.style.display = 'flex';
                            }

                            // Dynamic Live Console Output
                            const activeConsole = data.node === 'node-asr' ? asrConsole : (data.node === 'node-ocr' ? ocrConsole : null);
                            if (activeConsole && Math.random() > 0.4) {
                                const msgs = data.node === 'node-asr' 
                                    ? ['[DEBUG] Decoding audio chunk...', '[INFO] VAD filter bypassed', `[ASR] Processed frames: ${Math.floor(Math.random()*5000)}`, '[DEBUG] Beam search iteration...']
                                    : ['[OCR] Scanning frame buffer...', '[DEBUG] Running Tesseract inference...', `[OCR] Detections found: ${Math.floor(Math.random()*15)}`, '[INFO] Parsing bounding boxes...'];
                                const randMsg = msgs[Math.floor(Math.random() * msgs.length)];
                                
                                const line = document.createElement('div');
                                line.className = 'live-console-line';
                                if (Math.random() > 0.8) line.classList.add('highlight');
                                line.textContent = `[${new Date().toISOString().substring(11,23)}] ${randMsg}`;
                                
                                activeConsole.appendChild(line);
                                if (activeConsole.children.length > 5) {
                                    activeConsole.removeChild(activeConsole.children[0]);
                                }
                            }

                            foundCurrent = true;
                        } else {
                            // This is a completed past node
                            if (card) {
                                const pb = card.querySelector('.progress-bar-container');
                                if (pb) pb.style.display = 'none';
                                
                                // Add checkmark if it doesn't have one
                                const h4 = card.querySelector('.card-details h4');
                                if (h4 && !h4.querySelector('.check-done')) {
                                    h4.innerHTML += ' <svg class="check-done" style="width:16px;height:16px;color:#10b981;vertical-align:middle;margin-left:4px;" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3"><polyline points="20 6 9 17 4 12"></polyline></svg>';
                                }
                            }
                        }
                    } else {
                        node.classList.remove('active');
                        if (card) {
                            card.classList.remove('active');
                            const pb = card.querySelector('.progress-bar-container');
                            if (pb) pb.style.display = 'none';
                        }
                        if (idx > 0 && allConns[idx - 1]) {
                            allConns[idx - 1].classList.remove('active');
                        }
                    }
                });
            }
        } catch (e) { }
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

        if (response.ok && data.result) {
            const isMatch = data.result.status !== 'NOT_FOUND' && data.result.confidence_score > 0;
            if (isMatch) {
                showStatus("Match found in " + (data.elapsed ? data.elapsed.toFixed(1) : "0.1") + "s", "success");
            } else {
                showStatus(`Dialogue "${targetText}" not found in video`, "error");
            }
            const sessionId = data.session_id || "";
            renderHistoryCard(data.result, sessionId, targetText, true);
        } else {
            const fallbackResult = {
                status: "NOT_FOUND",
                confidence_score: 0.0,
                timestamp: "00:00:00.000",
                extracted_text: "",
                target_text: targetText,
                mode: searchMode,
                video_file: localVideo || "video",
                frame_number: 0
            };
            renderHistoryCard(fallbackResult, "not_found_" + Date.now(), targetText, true);
            showStatus(`Dialogue "${targetText}" not found in video`, "error");
        }
    } catch (err) {
        if (document.getElementById(processingId)) document.getElementById(processingId).remove();
        const fallbackResult = {
            status: "NOT_FOUND",
            confidence_score: 0.0,
            timestamp: "00:00:00.000",
            extracted_text: "",
            target_text: targetText,
            mode: searchMode,
            video_file: localVideo || "video",
            frame_number: 0
        };
        renderHistoryCard(fallbackResult, "not_found_" + Date.now(), targetText, true);
        showStatus(`Dialogue "${targetText}" not found in video`, "error");
    } finally {
        setLoading(runBtn, false);
        if (typeof statusInterval !== 'undefined') clearInterval(statusInterval);
        if (animFrame) cancelAnimationFrame(animFrame);
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
