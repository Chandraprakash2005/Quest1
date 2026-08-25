from src.core.config import log

_WHISPER_MODEL = None

def get_whisper_model(model_size: str = "medium.en"):
    """Returns a cached Whisper model, preferring GPU."""
    global _WHISPER_MODEL
    if _WHISPER_MODEL is not None:
        return _WHISPER_MODEL
    
    from faster_whisper import WhisperModel
    try:
        log.info("Loading faster-whisper '%s' on CUDA GPU...", model_size)
        _WHISPER_MODEL = WhisperModel(model_size, device="cuda", compute_type="float16")
    except Exception as e:
        log.warning("GPU load failed (%s). Falling back to CPU.", str(e)[:60])
        _WHISPER_MODEL = WhisperModel(model_size, device="cpu", compute_type="int8")
        
    return _WHISPER_MODEL
