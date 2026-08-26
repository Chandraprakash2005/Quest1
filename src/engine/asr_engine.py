from src.core.config import log

_WHISPER_MODELS = {}

def get_whisper_model(model_size: str = "small.en"):
    """Returns a cached Whisper model, preferring GPU."""
    global _WHISPER_MODELS
    if model_size in _WHISPER_MODELS:
        log.info(f"[ASR_ENGINE] Model '{model_size}' found in RAM cache.")
        return _WHISPER_MODELS[model_size]
    
    log.info(f"[ASR_ENGINE] Importing faster_whisper for '{model_size}'...")
    try:
        from faster_whisper import WhisperModel
        log.info("[ASR_ENGINE] faster_whisper imported successfully.")
    except Exception as e:
        log.error(f"[ASR_ENGINE] Failed to import faster_whisper: {e}")
        raise e
        
    try:
        log.info(f"[ASR_ENGINE] Attempting to load faster-whisper '{model_size}' on GPU (cuda) with float16...")
        _WHISPER_MODELS[model_size] = WhisperModel(model_size, device="cuda", compute_type="float16")
        log.info("[ASR_ENGINE] GPU load successful (float16).")
    except Exception as e_cuda_fp16:
        log.warning(f"[ASR_ENGINE] GPU float16 load failed ({e_cuda_fp16}). Trying GPU float32...")
        try:
            _WHISPER_MODELS[model_size] = WhisperModel(model_size, device="cuda", compute_type="float32")
            log.info("[ASR_ENGINE] GPU load successful (float32).")
        except Exception as e_cuda_fp32:
            log.warning(f"[ASR_ENGINE] GPU load failed entirely ({e_cuda_fp32}). Falling back to CPU...")
            try:
                _WHISPER_MODELS[model_size] = WhisperModel(model_size, device="cpu", compute_type="int8")
                log.info("[ASR_ENGINE] CPU load successful.")
            except Exception as e_cpu:
                log.error(f"[ASR_ENGINE] CPU load failed: {e_cpu}")
                raise e_cpu
        
    return _WHISPER_MODELS[model_size]
