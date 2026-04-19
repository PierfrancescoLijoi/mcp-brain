import re
from src.brain.file_indexer import get_or_build_index

STOPWORDS = {
    'the', 'and', 'for', 'with', 'from', 'this', 'that', 'have', 'will',
    'should', 'would', 'could', 'been', 'when', 'where', 'which', 'while',
    'about', 'into', 'onto', 'issue', 'ticket', 'please', 'need', 'needs',
    'want', 'wants', 'make', 'makes', 'using', 'use', 'uses', 'add', 'adds',
    'fix', 'fixes', 'update', 'updates', 'feature', 'features',
}


def _extract_keywords(text: str) -> set:
    words = re.findall(r'[a-z_][a-z0-9_]{3,}', text.lower())
    return set(w for w in words if w not in STOPWORDS)


def predict_files_from_issue(title: str, body: str = '') -> list:
    '''Usa indice inverso. O(n_keywords) invece di O(n_files).'''
    keywords = _extract_keywords(f'{title} {body}')
    if not keywords:
        return []

    index = get_or_build_index()
    if not index or not index.get('inverted'):
        return []

    inverted = index['inverted']
    scores = {}

    for kw in keywords:
        entries = inverted.get(kw, [])
        for entry in entries:
            file = entry['file']
            weight = entry['weight']
            scores[file] = scores.get(file, 0) + weight

        # Bonus match parziale nel nome file
        for file in index.get('files', {}).keys():
            if kw in file.lower():
                scores[file] = scores.get(file, 0) + 5

    ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)
    return [f for f, _ in ranked[:10]]
