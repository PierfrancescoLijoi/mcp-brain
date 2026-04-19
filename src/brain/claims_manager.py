import os
import yaml
from pathlib import Path
from datetime import datetime, timezone

REPO_CWD = os.environ.get('MCP_BRAIN_REPO', os.getcwd())
from src.storage.paths import CLAIMS_PATH


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


def claim_files(ticket_id: int, files: list, author: str, title: str = '') -> dict:
    '''Aggiunge un claim per un ticket su una lista di file.'''
    data = _load_claims()
    data['active'] = [c for c in data['active'] if c['ticket'] != ticket_id]
    claim = {
        'ticket': ticket_id,
        'title': title,
        'author': author,
        'files': files,
        'claimed_at': datetime.now(timezone.utc).isoformat(),
    }
    data['active'].append(claim)
    _save_claims(data)
    return claim


def release_claim(ticket_id: int) -> bool:
    '''Rilascia il claim per un ticket.'''
    data = _load_claims()
    before = len(data['active'])
    data['active'] = [c for c in data['active'] if c['ticket'] != ticket_id]
    _save_claims(data)
    return len(data['active']) < before


def get_active_claims() -> list:
    '''Tutti i claim attivi.'''
    return _load_claims().get('active', [])


def get_claims_for_files(files: list) -> list:
    '''Claim attivi che toccano i file specificati.'''
    claims = get_active_claims()
    overlapping = []
    for claim in claims:
        shared = set(claim['files']) & set(files)
        if shared:
            overlapping.append({
                **claim,
                'overlap': list(shared),
            })
    return overlapping
