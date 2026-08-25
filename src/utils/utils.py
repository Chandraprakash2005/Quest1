import re
import cv2
import numpy as np

def clean_text(text: str) -> str:
    return re.sub(r'[^\w\s]', ' ', text).lower()

def crop_subtitle_region(frame: np.ndarray) -> np.ndarray:
    h = frame.shape[0]
    top = int(h * 0.70)
    return frame[top:h, :]
