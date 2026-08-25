import re
from rapidfuzz import fuzz

SHORT_WORD_EXACT_LENGTH = 2
MEDIUM_WORD_MIN_SIMILARITY = 75
LONG_WORD_MIN_SIMILARITY = 75

def _normalize_text(text: str) -> str:
    """
    1. Convert Unicode text consistently.
    2. Convert to lowercase.
    3. Remove or normalize punctuation.
    4. Normalize whitespace.
    5. Remove leading/trailing whitespace.
    6. Preserve word boundaries.
    """
    if not text:
        return ""
    # Convert to lowercase
    text = text.lower()
    # Remove punctuation but preserve alphanumeric and spaces
    text = re.sub(r'[^a-z0-9\s]', ' ', text)
    # Normalize whitespace
    text = re.sub(r'\s+', ' ', text)
    return text.strip()

def _tokenize(text: str) -> list[str]:
    """Split normalized text into words."""
    return text.split()

def _exact_word_match(target_word: str, ocr_word: str) -> bool:
    """Check if two words match exactly."""
    return target_word == ocr_word

def _fuzzy_word_similarity(target_word: str, ocr_word: str) -> float:
    """Calculate fuzzy similarity between two words."""
    if _exact_word_match(target_word, ocr_word):
        return 100.0
        
    length = len(target_word)
    # Short words (1-2 chars) require exact matching because fuzzy matching them leads to dangerous false positives (e.g. 'at' vs 'as')
    if length <= SHORT_WORD_EXACT_LENGTH:
        return 0.0 
        
    score = fuzz.ratio(target_word, ocr_word)
    
    # OCR character errors (e.g., 'mind' -> 'mlnd') are tolerated using these length-based thresholds
    # Medium words require high similarity to tolerate exactly 1-2 character errors
    if length <= 4:
        if score >= MEDIUM_WORD_MIN_SIMILARITY:
            return score
        return 0.0
        
    if score >= LONG_WORD_MIN_SIMILARITY:
        return score
        
    return 0.0

def _match_word_sequence(target_words: list[str], ocr_words: list[str]) -> tuple[float, float, float]:
    """
    Matches the target word sequence against the OCR word sequence.
    Returns: (word_match_quality, coverage, order_quality)
    """
    if not target_words or not ocr_words:
        return 0.0, 0.0, 0.0

    n_target = len(target_words)
    n_ocr = len(ocr_words)
    
    # We want to find the best contiguous-ish subsegment of ocr_words that matches target_words
    # Sliding window over OCR words
    best_overall_score = 0.0
    best_coverage = 0.0
    best_order = 0.0
    best_word_quality = 0.0
    
    window_size = min(n_target + 3, n_ocr) # Allow some extra words
    
    # If the ocr string is shorter than the target, just evaluate it as one window
    if n_ocr <= window_size:
        windows = [ocr_words]
    else:
        windows = [ocr_words[i:i + window_size] for i in range(n_ocr - window_size + 1)]
    
    for window in windows:
        # Greedy match target words in order within this window
        matched_count = 0
        total_word_score = 0.0
        last_matched_idx = -1
        order_penalties = 0
        
        for t_word in target_words:
            best_t_score = 0.0
            best_o_idx = -1
            
            for j, o_word in enumerate(window):
                score = _fuzzy_word_similarity(t_word, o_word)
                if score > best_t_score:
                    best_t_score = score
                    best_o_idx = j
                    
            if best_t_score > 0:
                matched_count += 1
                total_word_score += best_t_score
                if best_o_idx < last_matched_idx:
                    order_penalties += 1
                last_matched_idx = best_o_idx
                
        coverage = matched_count / n_target
        word_quality = (total_word_score / matched_count) if matched_count > 0 else 0.0
        order_quality = max(0.0, 1.0 - (order_penalties / n_target))
        
        # Calculate a combined window score to find the best window
        window_score = word_quality * coverage * order_quality
        if window_score >= best_overall_score:
            best_overall_score = window_score
            best_coverage = coverage
            best_order = order_quality
            best_word_quality = word_quality

    return best_word_quality, best_coverage, best_order

def calculate_ocr_match_score(target: str, ocr_text: str) -> float:
    """
    Evaluates whether the target dialogue is present in the OCR text.
    Returns a confidence score from 0.0 to 100.0.
    """
    norm_target = _normalize_text(target)
    norm_ocr = _normalize_text(ocr_text)
    
    if not norm_target or not norm_ocr:
        return 0.0
        
    target_words = _tokenize(norm_target)
    ocr_words = _tokenize(norm_ocr)
    
    # Fast path for exact word sequence match
    # Word boundaries matter: 'cat' must not match 'category'
    n_target = len(target_words)
    n_ocr = len(ocr_words)
    
    if n_ocr >= n_target:
        for i in range(n_ocr - n_target + 1):
            if ocr_words[i:i+n_target] == target_words:
                return 100.0
        
    word_match_quality, coverage, order_quality = _match_word_sequence(target_words, ocr_words)
    
    # Missing words heavily penalize the score via coverage
    if coverage < 0.5:
        return 0.0
        
    # Final confidence score is calculated multiplicatively:
    # word_quality * coverage * order_quality
    # This ensures that wrong word order or low coverage drastically reduce the final score, preventing false positives
    final_score = (word_match_quality / 100.0) * coverage * order_quality * 100.0
    return final_score
