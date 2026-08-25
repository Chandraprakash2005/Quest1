const videoUrlInput = document.getElementById('video-url');
const videoSelect = document.getElementById('video-select');
const searchTextInput = document.getElementById('search-text');
const searchModeSelect = document.getElementById('search-mode');
const runBtn = document.getElementById('run-btn');
const statusMsg = document.getElementById('status-msg');

// States
const idleState = document.getElementById('idle-state');
const processingState = document.getElementById('processing-state');
const resultState = document.getElementById('result-state');

// Result Elements
const resStatus = document.getElementById('res-status');
const resTime = document.getElementById('res-time');
const resFrame = document.getElementById('res-frame');
const resConf = document.getElementById('res-conf');
const resText = document.getElementById('res-text');
const resImg = document.getElementById('res-img');
const metricTime = document.getElementById('metric-time');
const metricFrame = document.getElementById('metric-frame');
const metricConf = document.getElementById('metric-conf');
const resultImageContainer = document.querySelector('.result-image-container');

// Fetch cached videos on page load
window.addEventListener('DOMContentLoaded', async () => {
    try {
        const resp = await fetch('/api/videos');
        if (resp.ok) {
            const data = await resp.json();
            data.videos.forEach(vid => {
                const opt = document.createElement('option');
                opt.value = vid;
                opt.textContent = vid;
                opt.style.color = "black";
                videoSelect.appendChild(opt);
            });
        }
    } catch (e) {
        console.error("Failed to fetch videos", e);
    }
});

function switchState(stateId) {
    idleState.classList.add('hidden');
    processingState.classList.add('hidden');
    resultState.classList.add('hidden');
    
    document.getElementById(stateId).classList.remove('hidden');
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
    switchState('processing-state');

    try {
        // Send a single request to /api/search
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
        
        if (response.ok) {
            showStatus("Pipeline completed in " + data.elapsed.toFixed(1) + "s", "success");
            
            // Populate results
            let statusText = data.result.status;
            if (statusText === "NOT_FOUND") {
                statusText = "Not Found";
                resStatus.className = "status-badge error";
            } else {
                if (searchMode === "asr_only") statusText = "ASR Match";
                else if (searchMode === "ocr_only") statusText = "OCR Match";
                else if (searchMode === "asr_ocr") statusText = "ASR + OCR Match";
                else statusText = "Match Found";
                
                resStatus.className = "status-badge";
            }
            resStatus.textContent = statusText.toUpperCase();
            
            if (data.result.status === "NOT_FOUND") {
                metricTime.style.display = "none";
                metricFrame.style.display = "none";
                metricConf.style.display = "none";
                resultImageContainer.style.display = "none";
                resText.textContent = '"Not found in the video"';
            } else {
                metricTime.style.display = "flex";
                metricFrame.style.display = "flex";
                metricConf.style.display = "flex";
                resultImageContainer.style.display = "flex";
                
                resTime.textContent = data.result.timestamp;
                resFrame.textContent = data.result.frame_number;
                resConf.textContent = data.result.confidence_score + "%";
                resText.textContent = '"' + data.result.extracted_text + '"';
                
                // Add cache buster to image and use session_id for concurrency
                const sessionId = data.session_id || "";
                resImg.src = `/api/frame?id=${sessionId}&t=` + new Date().getTime();
            }
            
            switchState('result-state');
        } else {
            showStatus("Error: " + data.error, "error");
            switchState('idle-state'); // Revert back to idle on error
        }
    } catch (err) {
        showStatus("Network error occurred.", "error");
        switchState('idle-state');
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
