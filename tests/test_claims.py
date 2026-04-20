"""Test del sistema di soft-claims (team coordination)."""
from datetime import datetime, timezone, timedelta

import yaml


def _read_claims_file(tmp_brain):
    from src.storage.paths import CLAIMS_PATH
    return yaml.safe_load(CLAIMS_PATH.read_text())


class TestClaimFiles:
    def test_create_claim(self, tmp_brain):
        from src.brain.claims_manager import claim_files, get_active_claims
        claim_files(42, ['auth.py', 'middleware.py'], author='alice', title='Fix auth')
        active = get_active_claims()
        assert len(active) == 1
        assert active[0]['ticket'] == 42
        assert active[0]['author'] == 'alice'
        assert active[0]['status'] == 'active'

    def test_claim_replaces_existing_for_same_ticket(self, tmp_brain):
        from src.brain.claims_manager import claim_files, get_active_claims
        claim_files(42, ['a.py'], author='alice')
        claim_files(42, ['b.py'], author='alice')  # stesso ticket, file diverso
        active = get_active_claims()
        assert len(active) == 1
        assert active[0]['files'] == ['b.py']

    def test_multiple_tickets_coexist(self, tmp_brain):
        from src.brain.claims_manager import claim_files, get_active_claims
        claim_files(1, ['a.py'], author='alice')
        claim_files(2, ['b.py'], author='bob')
        active = get_active_claims()
        assert {c['ticket'] for c in active} == {1, 2}


class TestReleaseClaim:
    def test_release_removes_from_active(self, tmp_brain):
        from src.brain.claims_manager import claim_files, release_claim, get_active_claims
        claim_files(42, ['a.py'], author='alice')
        assert release_claim(42) is True
        assert get_active_claims() == []

    def test_release_nonexistent_is_false(self, tmp_brain):
        from src.brain.claims_manager import release_claim
        assert release_claim(999) is False


class TestAutoExpiry:
    def test_expired_claim_marked_stale_on_disk(self, tmp_brain):
        """
        Claim oltre TTL → status='stale' persistito a disco.
        get_active_claims filtra i 'stale', quindi per verificare lo
        status salvato leggiamo direttamente il file yaml.
        """
        from src.brain import claims_manager

        # Scrivo a mano un claim scaduto 1 giorno fa
        past = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
        claims_manager._save_claims({
            'active': [{
                'ticket': 99,
                'files': ['a.py'],
                'author': 'alice',
                'status': 'active',
                'expires_at': past,
                'created_at': past,
            }]
        })

        # Trigger dell'auto-expire (salva il nuovo status sul file)
        claims_manager.get_active_claims()

        # Verifico sul file
        data = _read_claims_file(tmp_brain)
        claim_99 = next(c for c in data['active'] if c['ticket'] == 99)
        assert claim_99['status'] == 'stale'

    def test_expired_claim_excluded_from_active(self, tmp_brain):
        """get_active_claims non deve ritornare claim stale."""
        from src.brain import claims_manager

        past = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
        claims_manager._save_claims({
            'active': [{
                'ticket': 99,
                'files': ['a.py'],
                'author': 'alice',
                'status': 'active',
                'expires_at': past,
                'created_at': past,
            }]
        })

        active = claims_manager.get_active_claims()
        assert all(c['ticket'] != 99 for c in active)


class TestGetClaimsForFiles:
    def test_returns_only_overlapping(self, tmp_brain):
        from src.brain.claims_manager import claim_files, get_claims_for_files
        claim_files(1, ['auth.py', 'login.py'], author='alice')
        claim_files(2, ['db.py'], author='bob')

        overlap = get_claims_for_files(['login.py'])
        tickets = [c['ticket'] for c in overlap]
        assert tickets == [1]
        assert overlap[0]['overlap'] == ['login.py']
