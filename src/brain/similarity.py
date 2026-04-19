import re
from typing import Iterable

STOPWORDS = {
    'the', 'and', 'for', 'with', 'from', 'this', 'that', 'have', 'will',
    'should', 'would', 'could', 'been', 'when', 'where', 'which', 'while',
    'about', 'into', 'onto', 'issue', 'ticket', 'please', 'need', 'needs',
    'want', 'wants', 'make', 'makes', 'using', 'use', 'uses', 'add', 'adds',
    'fix', 'fixes', 'update', 'updates', 'feature', 'features',
    'decision', 'architectural', 'change', 'commit', 'merge', 'branch',
}


def tokenize(text: str) -> set:
    """Lowercase tokens, no stopwords, min length 3."""
    if not text:
        return set()
    words = re.findall(r'[a-z_][a-z0-9_]{2,}', text.lower())
    return {w for w in words if w not in STOPWORDS}


def jaccard(a: set, b: set) -> float:
    """Jaccard similarity: |A n B| / |A u B|."""
    if not a or not b:
        return 0.0
    inter = len(a & b)
    union = len(a | b)
    return inter / union if union else 0.0


def semantic_similar(content_a: str, content_b: str, threshold: float = 0.35) -> tuple:
    """
    Returns (is_similar, score).
    Considers two memories similar if Jaccard >= threshold.
    """
    tokens_a = tokenize(content_a)
    tokens_b = tokenize(content_b)
    score = jaccard(tokens_a, tokens_b)
    return score >= threshold, score


def find_similar_memories(new_content: str, candidates: Iterable[dict],
                          threshold: float = 0.35,
                          same_category: str = None) -> list:
    """
    Filters candidates keeping only semantically similar ones.
    Returns list of (memory, score) sorted by score desc.
    """
    new_tokens = tokenize(new_content)
    results = []
    for mem in candidates:
        if same_category and mem.get('category') != same_category:
            continue
        cand_tokens = tokenize(mem.get('content', ''))
        score = jaccard(new_tokens, cand_tokens)
        if score >= threshold:
            results.append((mem, score))
    results.sort(key=lambda x: x[1], reverse=True)
    return results