const loadBtn = document.getElementById('load-btn');
const videoUrlInput = document.getElementById('video-url');
const loadStatus = document.getElementById('load-status');

const searchSection = document.getElementById('search-section');
const searchBtn = document.getElementById('search-btn');
const searchTextInput = document.getElementById('search-text');
const searchStatus = document.getElementById('search-status');

const resultSection = document.getElementById('result-section');
const resStatus = document.getElementById('res-status');
const resTime = document.getElementById('res-time');
const resConf = document.getElementById('res-conf');
const resText = document.getElementById('res-text');
const resImg = document.getElementById('res-img');

loadBtn.addEventListener('click', async () => {
    const url = videoUrlInput.value.trim();
    if (!url) {
        showStatus(loadStatus, "Please enter a valid URL.", "error");
        return;
    }

    setLoading(loadBtn, true);
    showStatus(loadStatus, "Downloading video and extracting audio... This may take a minute.", "");
    searchSection.classList.add("disabled");
    resultSection.classList.add("hidden");

    try {
        const response = await fetch('/api/load', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ url: url })
        });
        
        const data = await response.json();
        if (response.ok) {
            showStatus(loadStatus, "Video downloaded and cached successfully!", "success");
            searchSection.classList.remove("disabled");
        } else {
            showStatus(loadStatus, "Error: " + data.error, "error");
        }
    } catch (err) {
        showStatus(loadStatus, "Network error occurred.", "error");
    } finally {
        setLoading(loadBtn, false);
    }
});

searchBtn.addEventListener('click', async () => {
    const targetText = searchTextInput.value.trim();
    if (!targetText) {
        showStatus(searchStatus, "Please enter a target dialogue.", "error");
        return;
    }

    setLoading(searchBtn, true);
    showStatus(searchStatus, "Running ASR & OCR pipeline... Analyzing frames...", "");
    resultSection.classList.add("hidden");

    try {
        const searchMode = document.getElementById('search-mode').value;
        const response = await fetch('/api/search', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ 
                target: targetText,
                url: videoUrlInput.value.trim(),
                mode: searchMode
            })
        });
        
        const data = await response.json();
        if (response.ok) {
            showStatus(searchStatus, "Pipeline completed in " + data.elapsed.toFixed(1) + "s", "success");
            
            // Populate results
            let statusText = data.result.status;
            if (statusText === "NOT_FOUND") {
                statusText = "Not Found";
            } else {
                if (searchMode === "asr_only") {
                    statusText = "ASR Match";
                } else if (searchMode === "ocr_only") {
                    statusText = "OCR Match";
                } else if (searchMode === "asr_ocr") {
                    statusText = "ASR + OCR Match";
                } else {
                    statusText = "Match Found";
                }
            }
            resStatus.textContent = statusText;
            resStatus.className = "value " + (data.result.status === "NOT_FOUND" ? "error" : "highlight");
            
            resTime.textContent = data.result.timestamp;
            resConf.textContent = data.result.confidence_score + "%";
            console.log(data.result.confidence_score);
            resText.textContent = '"' + data.result.extracted_text + '"';
            
            // Add cache buster to image and use session_id for concurrency
            const sessionId = data.session_id || "";
            resImg.src = `/api/frame?id=${sessionId}&t=` + new Date().getTime();
            
            resultSection.classList.remove("hidden");
        } else {
            showStatus(searchStatus, "Error: " + data.error, "error");
        }
    } catch (err) {
        showStatus(searchStatus, "Network error occurred.", "error");
    } finally {
        setLoading(searchBtn, false);
    }
});

function showStatus(element, message, type) {
    element.textContent = message;
    element.className = "status-msg " + type;
}

function setLoading(button, isLoading) {
    if (isLoading) {
        button.disabled = true;
        button.dataset.originalText = button.textContent;
        button.textContent = "Processing";
        button.classList.add("loading");
    } else {
        button.disabled = false;
        button.textContent = button.dataset.originalText;
        button.classList.remove("loading");
    }
}
