from src.capture.github_reader import list_open_prs
from src.brain.claims_manager import get_claims_for_files


def detect_conflicts(target_files: list, exclude_author: str = None) -> dict:
    '''
    Identifica conflitti su target_files:
      - PR aperte che toccano quegli stessi file
      - Claim attivi di altri developer
    '''
    conflicts = {
        'pr_conflicts': [],
        'claim_conflicts': [],
    }

    # PR aperte
    prs = list_open_prs()
    target_set = set(target_files)
    for pr in prs:
        shared = target_set & set(pr['files'])
        if shared:
            if exclude_author and pr['author'] == exclude_author:
                continue
            conflicts['pr_conflicts'].append({
                'pr': pr['number'],
                'title': pr['title'],
                'author': pr['author'],
                'branch': pr['branch'],
                'overlapping_files': list(shared),
            })

    # Claim attivi
    claims = get_claims_for_files(target_files)
    for claim in claims:
        if exclude_author and claim['author'] == exclude_author:
            continue
        conflicts['claim_conflicts'].append({
            'ticket': claim['ticket'],
            'title': claim.get('title', ''),
            'author': claim['author'],
            'overlapping_files': claim['overlap'],
        })

    return conflicts


def build_warnings(conflicts: dict) -> list:
    '''Converte conflitti in stringhe di warning leggibili.'''
    warnings = []
    for pr in conflicts.get('pr_conflicts', []):
        files_str = ', '.join(pr['overlapping_files'][:3])
        warnings.append(
            f"PR #{pr['pr']} ({pr['author']}): '{pr['title']}' touches {files_str}"
        )
    for c in conflicts.get('claim_conflicts', []):
        files_str = ', '.join(c['overlapping_files'][:3])
        warnings.append(
            f"Ticket #{c['ticket']} ({c['author']}): '{c['title']}' claimed {files_str}"
        )
    return warnings
