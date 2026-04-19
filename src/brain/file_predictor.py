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
    '''Legacy API: ritorna solo lista file.'''
    return [p['file'] for p in predict_files_explained(title, body)]


def predict_files_explained(title: str, body: str = '') -> list:
    '''Predict con spiegazione: ritorna file + why + confidence.'''
    keywords = _extract_keywords(f'{title} {body}')
    if not keywords:
        return []

    index = get_or_build_index()
    if not index or not index.get('inverted'):
        return []

    inverted = index['inverted']
    files_meta = index.get('files', {})

    scores = {}  # file -> {'score': N, 'matches': {kw: reason}}

    for kw in keywords:
        entries = inverted.get(kw, [])
        for entry in entries:
            file = entry['file']
            weight = entry['weight']
            reason_type = 'symbol' if weight >= 3 else 'identifier'

            if file not in scores:
                scores[file] = {'score': 0, 'matches': {}}
            scores[file]['score'] += weight
            if reason_type not in scores[file]['matches']:
                scores[file]['matches'][reason_type] = []
            scores[file]['matches'][reason_type].append(kw)

        for file in files_meta.keys():
            if kw in file.lower():
                if file not in scores:
                    scores[file] = {'score': 0, 'matches': {}}
                scores[file]['score'] += 5
                scores[file]['matches'].setdefault('filename', []).append(kw)

    ranked = sorted(scores.items(), key=lambda x: x[1]['score'], reverse=True)

    results = []
    if ranked:
        max_score = ranked[0][1]['score']
    else:
        max_score = 1

    for file, data in ranked[:10]:
        score = data['score']
        confidence = 'high' if score >= max_score * 0.7 else ('medium' if score >= max_score * 0.4 else 'low')

        why_parts = []
        if 'symbol' in data['matches']:
            syms = data['matches']['symbol'][:3]
            why_parts.append(f"matched symbol(s) {', '.join(syms)}")
        if 'filename' in data['matches']:
            why_parts.append(f"filename matches {data['matches']['filename'][0]}")
        if 'identifier' in data['matches'] and not why_parts:
            why_parts.append(f"identifier match: {data['matches']['identifier'][0]}")

        results.append({
            'file': file,
            'confidence': confidence,
            'why': '; '.join(why_parts) if why_parts else 'keyword match',
            'score': score,
        })

    return results
