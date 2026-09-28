import subprocess

from src.brain.cochange_graph import build_cochange_graph
from src.brain.graph_ranker import build_file_adjacency


def _git(repo, *args):
    return subprocess.run(
        ['git', '-C', str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
    )


def _commit(repo, message, files):
    for name, content in files.items():
        path = repo / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding='utf-8')
    _git(repo, 'add', '.')
    _git(repo, 'commit', '-qm', message)


def test_cochange_weights_repeated_small_commits_more_strongly(tmp_path):
    repo = tmp_path / 'repo'
    repo.mkdir()
    _git(repo, 'init', '-q')
    _git(repo, 'config', 'user.email', 'test@example.com')
    _git(repo, 'config', 'user.name', 'Test User')
    _commit(repo, 'initial', {
        'src/a.py': 'a = 1\n',
        'src/b.py': 'b = 1\n',
        'src/c.py': 'c = 1\n',
    })
    _commit(repo, 'change a and b', {
        'src/a.py': 'a = 2\n',
        'src/b.py': 'b = 2\n',
    })
    _commit(repo, 'change a and b again', {
        'src/a.py': 'a = 3\n',
        'src/b.py': 'b = 3\n',
    })
    _commit(repo, 'change a and c', {
        'src/a.py': 'a = 4\n',
        'src/c.py': 'c = 2\n',
    })

    graph = build_cochange_graph(repo, max_commits=20, half_life_commits=1000)

    assert graph['src/a.py']['src/b.py'] > graph['src/a.py']['src/c.py']
    assert graph['src/a.py']['src/b.py'] == graph['src/b.py']['src/a.py']


def test_file_adjacency_includes_cochange_edges():
    graph = {
        'files': {
            'src/a.py': {'imports_to': [], 'calls_out': []},
            'src/b.py': {'imports_to': [], 'calls_out': []},
        },
        'cochange': {
            'src/a.py': {'src/b.py': 2.0},
            'src/b.py': {'src/a.py': 2.0},
        },
    }

    adjacency = build_file_adjacency(graph)

    assert adjacency['src/a.py']['src/b.py'] > 0


def test_non_git_directory_has_empty_cochange_graph(tmp_path):
    assert build_cochange_graph(tmp_path) == {}
