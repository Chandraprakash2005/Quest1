from dataclasses import dataclass

@dataclass
class VideoMeta:
    fps: float = 0.0
    duration: float = 0.0
    width: int = 0
    height: int = 0
    video_path: str = ""
    audio_path: str = ""

@dataclass
class MatchResult:
    timestamp: float = 0.0
    frame_number: int = 0
    extracted_text: str = ""
    confidence: float = 0.0
    status: str = "NOT_FOUND"
    asd_status: str = ""

@dataclass
class SearchWindow:
    start: float = 0.0
    end: float = 0.0
