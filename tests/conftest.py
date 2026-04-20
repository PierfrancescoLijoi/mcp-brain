"""
Fixture condivise per tutta la test suite.

Due fixture principali:
  - tmp_brain: isola DB, index e claims in una dir temporanea (monkeypatch
    sui percorsi globali, così ogni test ha stato pulito e parallelo-safe)
  - git_repo: crea un repo git reale in tmp_path con commit veri,
    usato per testare git_reader.get_repo_snapshot
"""
import os
import subprocess
import pytest


@pytest.fixture
def tmp_brain(tmp_path, monkeypatch):
    """
    Isola tutto lo stato mcp-brain in tmp_path.
    Rimpiazza i percorsi globali (DB_PATH, INDEX_PATH, CLAIMS_PATH) in tutti
    i moduli che li importano a livello modulo — così i test non si
    influenzano l'un l'altro e non toccano il DB reale dell'utente.
    """
    brain_root = tmp_path / '.brain'
    shared = brain_root / 'shared'
    local = brain_root / 'local'
    shared.mkdir(parents=True)
    local.mkdir(parents=True)

    db_path = local / 'memory.db'
    index_path = local / 'file_index.json'
    claims_path = shared / 'claims.yaml'

    # Patch su paths.py
    from src.storage import paths
    monkeypatch.setattr(paths, 'BRAIN_ROOT', brain_root)
    monkeypatch.setattr(paths, 'SHARED_DIR', shared)
    monkeypatch.setattr(paths, 'LOCAL_DIR', local)
    monkeypatch.setattr(paths, 'DB_PATH', db_path)
    monkeypatch.setattr(paths, 'INDEX_PATH', index_path)
    monkeypatch.setattr(paths, 'CLAIMS_PATH', claims_path)

    # Patch sui moduli che hanno già importato questi nomi
    from src.storage import db as db_mod
    monkeypatch.setattr(db_mod, 'DB_PATH', db_path)

    from src.brain import claims_manager
    monkeypatch.setattr(claims_manager, 'CLAIMS_PATH', claims_path)

    from src.brain import file_indexer
    monkeypatch.setattr(file_indexer, 'INDEX_PATH', index_path)

    monkeypatch.setenv('MCP_BRAIN_REPO', str(tmp_path))

    # Inizializza schema
    db_mod.init_db()

    yield tmp_path


@pytest.fixture
def git_repo(tmp_path, monkeypatch):
    """
    Crea un repo git vero in tmp_path con 3 commit + 1 file untracked.
    Ritorna il path del repo. MCP_BRAIN_REPO punta qui.
    """
    repo = tmp_path / 'repo'
    repo.mkdir()

    def _run(*args, cwd=repo):
        subprocess.run(['git', *args], cwd=cwd, check=True,
                       capture_output=True)

    _run('init', '-q', '-b', 'main')
    _run('config', 'user.email', 't@t.com')
    _run('config', 'user.name', 'Test')

    for i, msg in enumerate(['init: first', 'feat: add login', 'fix: broken auth']):
        (repo / f'file_{i}.py').write_text(f'# content {i}\n')
        _run('add', '.')
        _run('commit', '-qm', msg)

    # File untracked (non committato) → finisce in changed_files
    (repo / 'dirty.py').write_text('# wip\n')

    monkeypatch.setenv('MCP_BRAIN_REPO', str(repo))

    # Forza i moduli a leggere il nuovo REPO_PATH
    import importlib
    from src.capture import git_reader
    importlib.reload(git_reader)

    yield repo
