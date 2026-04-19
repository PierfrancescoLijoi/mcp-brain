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
    '''Predice file coinvolti usando l indice pre-computato. Velocissimo.'''
    keywords = _extract_keywords(f'{title} {body}')
    if not keywords:
        return []

    index = get_or_build_index()
    if not index or not index.get('files'):
        return []

    scored = []
    for file, tokens in index['files'].items():
        token_set = set(tokens)
        matches = keywords & token_set
        if matches:
            score = len(matches)
            name_lower = file.lower()
            for kw in keywords:
                if kw in name_lower:
                    score += 3
            scored.append({'file': file, 'score': score})

    scored.sort(key=lambda x: x['score'], reverse=True)
    return [s['file'] for s in scored[:10]]
