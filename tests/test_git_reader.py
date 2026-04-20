"""Test git_reader contro un vero repo git (fixture git_repo)."""


class TestGetRepoSnapshot:
    def test_returns_branch_and_commits(self, git_repo):
        from src.capture.git_reader import get_repo_snapshot
        snap = get_repo_snapshot()
        assert snap['branch'] == 'main'
        assert len(snap['recent_commits']) == 3
        # Il più recente deve essere in testa
        assert snap['recent_commits'][0]['message'] == 'fix: broken auth'

    def test_ahead_behind_when_no_upstream(self, git_repo):
        from src.capture.git_reader import get_repo_snapshot
        snap = get_repo_snapshot()
        # Nessun remote configurato → 0/0
        assert snap['status'] == {'ahead': 0, 'behind': 0}

    def test_untracked_file_in_changed(self, git_repo):
        from src.capture.git_reader import get_repo_snapshot
        snap = get_repo_snapshot()
        paths = [f['file'] for f in snap['changed_files']]
        assert 'dirty.py' in paths

    def test_recent_commits_limit(self, git_repo):
        from src.capture.git_reader import get_repo_snapshot
        snap = get_repo_snapshot(recent_commits=2)
        assert len(snap['recent_commits']) == 2

    def test_current_branch_shortcut(self, git_repo):
        from src.capture.git_reader import get_current_branch
        assert get_current_branch() == 'main'

    def test_changed_files_since(self, git_repo):
        from src.capture.git_reader import get_changed_files_since
        files = get_changed_files_since('HEAD~2')
        assert 'file_1.py' in files
        assert 'file_2.py' in files
        # file_0 non è incluso perché HEAD~2 lo esclude dal range aperto
