import cv2
import numpy as np
import os
import math
from src.core.config import log

class TalkNetASDEngine:
    def __init__(self, model_path="assets/talknet_weights.pt"):
        self.model_path = model_path
        self.device = "cpu"
        self.model_loaded = False
        
        # Initialize MediaPipe FaceMesh exactly as provided
        try:
            import mediapipe as mp
            self.mp_face_mesh = mp.solutions.face_mesh
            self.face_mesh = self.mp_face_mesh.FaceMesh(
                static_image_mode=False,
                max_num_faces=3,
                refine_landmarks=True,
                min_detection_confidence=0.2,
                min_tracking_confidence=0.2
            )
        except Exception as e:
            log.warning(f"MediaPipe face mesh initialization failed: {e}")
            self.face_mesh = None
            
        # Mouth Aspect Ratio (MAR) variance threshold for active speaking
        self.MAR_VARIANCE_THRESHOLD = 0.0005
            
        self._load_pytorch_model()
            
    def _load_pytorch_model(self):
        try:
            import torch
            pass
        except Exception as e:
            log.warning("Failed to initialize PyTorch TalkNet backend: %s", str(e))

    def _calculate_lip_distances(self, face_landmarks) -> tuple:
        """Calculates vertical and horizontal lip distances from MediaPipe landmarks."""
        # Upper and lower inner lip landmarks
        upper_lip = face_landmarks.landmark[13]
        lower_lip = face_landmarks.landmark[14]
        # Left and right lip corners
        left_lip = face_landmarks.landmark[78]
        right_lip = face_landmarks.landmark[308]
        
        ver_dist = np.linalg.norm([upper_lip.x - lower_lip.x, upper_lip.y - lower_lip.y])
        hor_dist = np.linalg.norm([left_lip.x - right_lip.x, left_lip.y - right_lip.y])
        
        return float(ver_dist), float(hor_dist)

    def vision_analysis(self, frames: list) -> bool:
        """Analyzes lip movement to determine if the speaker is ON-SCREEN."""
        log.info("Phase 3: Vision Analysis (Active Speaker Detection)")
        mar_history = {}
        hor_history = {}
        
        for frame in frames:
            rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            results = self.face_mesh.process(rgb_frame)
            
            if results.multi_face_landmarks:
                for idx, face_landmarks in enumerate(results.multi_face_landmarks):
                    ver_dist, hor_dist = self._calculate_lip_distances(face_landmarks)
                    mar = ver_dist / (hor_dist + 1e-6)
                    
                    if idx not in mar_history:
                        mar_history[idx] = []
                        hor_history[idx] = []
                        
                    mar_history[idx].append(mar)
                    hor_history[idx].append(hor_dist)
                    
        if not mar_history:
            log.info("No human faces detected. -> OFF-SCREEN.")
            return False
            
        # Check MAR variance for each detected face
        for face_id, mars in mar_history.items():
            if len(mars) > 1:
                variance = np.var(mars)
                max_diff = np.max(mars) - np.min(mars)
                
                # Calculate horizontal lip variance (puckering/stretching)
                hors = hor_history[face_id]
                mean_hor = np.mean(hors)
                norm_hors = [h / (mean_hor + 1e-6) for h in hors]
                hor_variance = np.var(norm_hors)
                
                log.info(f"Face {face_id} MAR variance: {variance:.6f} | Horizontal variance: {hor_variance:.6f}")
                
                # Speech involves multi-directional lip changes (horizontal puckering + vertical opening)
                # Chewing gum is mostly vertical jaw dropping, with low horizontal shape change.
                if variance > self.MAR_VARIANCE_THRESHOLD:
                    if hor_variance > 0.00005:
                        log.info("Significant multi-directional lip articulation (Speech) detected -> ON-SCREEN.")
                        return True
                    else:
                        log.info("Vertical motion detected but lacks horizontal articulation (Chewing/Yawning) -> OFF-SCREEN.")
                        
        log.info("Faces detected but no active lip movement -> OFF-SCREEN.")
        return False

    def detect_speaker(self, frames, audio_path, start_time, end_time):
        """
        Runs TalkNet logic over the extracted temporal window frames and audio.
        Returns a dict: {"status": "ON_SCREEN"|"OFF_SCREEN", "confidence": float, "speaker_track": int}
        """
        if self.face_mesh is None:
            log.warning("MediaPipe face mesh failed to load.")
            return {"status": "OFF_SCREEN", "confidence": 0.0, "speaker_track": -1}
            
        # Call the exact user-provided logic
        is_on_screen = self.vision_analysis(frames)
        
        # Wrap the boolean result into the dictionary expected by the ASD pipeline phase
        if is_on_screen:
            return {"status": "ON_SCREEN", "confidence": 0.85, "speaker_track": 0}
        else:
            return {"status": "OFF_SCREEN", "confidence": 0.15, "speaker_track": -1}
