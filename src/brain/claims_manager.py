import yaml
from datetime import datetime, timezone, timedelta
from src.storage.paths import CLAIMS_PATH

DEFAULT_TTL_DAYS = 7


def _load_claims() -> dict:
    if not CLAIMS_PATH.exists():
        return {'active': []}
    try:
        with open(CLAIMS_PATH, 'r', encoding='utf-8') as f:
            data = yaml.safe_load(f) or {'active': []}
        return data
    except Exception:
        return {'active': []}


def _save_claims(data: dict):
    CLAIMS_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(CLAIMS_PATH, 'w', encoding='utf-8') as f:
        yaml.dump(data, f, default_flow_style=False, allow_unicode=True)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _expires_in(days: int) -> str:
    return (datetime.now(timezone.utc) + timedelta(days=days)).isoformat()


def _parse_iso(s: str):
    if not s:
        return None
    try:
        dt = datetime.fromisoformat(s.replace('Z', '+00:00'))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        return None


def _is_expired(claim: dict) -> bool:
    expires = _parse_iso(claim.get('expires_at'))
    if not expires:
        return False
    return datetime.now(timezone.utc) > expires


def _auto_expire(data: dict) -> dict:
    '''Marca come stale i claim scaduti, rimuove i released.'''
    cleaned = []
    for c in data.get('active', []):
        if c.get('status') == 'released':
            continue
        if _is_expired(c) and c.get('status') == 'active':
            c['status'] = 'stale'
        cleaned.append(c)
    data['active'] = cleaned
    return data


def claim_files(
    ticket_id: int,
    files: list,
    author: str,
    title: str = '',
    source: str = 'ticket_prediction',
    confidence: str = 'predicted',
    ttl_days: int = DEFAULT_TTL_DAYS,
) -> dict:
    '''Crea o aggiorna un claim per un ticket.'''
    data = _load_claims()
    data['active'] = [c for c in data['active'] if c['ticket'] != ticket_id]

    claim = {
        'ticket': ticket_id,
        'title': title,
        'author': author,
        'files': files,
        'status': 'active',
        'confidence': confidence,
        'source': source,
        'created_at': _now_iso(),
        'expires_at': _expires_in(ttl_days),
    }
    data['active'].append(claim)
    _save_claims(data)
    return claim


def release_claim(ticket_id: int) -> bool:
    '''Rilascia un claim (marca released, viene rimosso al prossimo load).'''
    data = _load_claims()
    found = False
    for c in data['active']:
        if c['ticket'] == ticket_id:
            c['status'] = 'released'
            c['released_at'] = _now_iso()
            found = True
    if found:
        _save_claims(data)
    return found


def get_active_claims() -> list:
    '''Tutti i claim attivi (auto-expire stale ed esclude released).'''
    data = _auto_expire(_load_claims())
    _save_claims(data)
    return [c for c in data.get('active', []) if c.get('status') in ('active', 'suspect')]


def get_claims_for_files(files: list) -> list:
    '''Claim attivi che toccano i file specificati.'''
    claims = get_active_claims()
    overlapping = []
    for claim in claims:
        shared = set(claim.get('files', [])) & set(files)
        if shared:
            overlapping.append({
                **claim,
                'overlap': list(shared),
            })
    return overlapping
