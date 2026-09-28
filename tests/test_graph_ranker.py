import pytest

from src.brain.graph_ranker import build_file_adjacency, personalized_pagerank


def _graph():
    return {
        'files': {
            'src/controller.py': {
                'imports_to': [
                    {'resolved': 'src/validator.py'},
                    {'resolved': 'src/service.py'},
                ],
                'calls_out': [],
            },
            'src/validator.py': {
                'imports_to': [],
                'calls_out': [],
            },
            'src/service.py': {
                'imports_to': [],
                'calls_out': [
                    {'resolves_to': ['src/repository.py']},
                ],
            },
            'src/repository.py': {
                'imports_to': [],
                'calls_out': [],
            },
        }
    }


def test_adjacency_is_bidirectional_for_imports_and_calls():
    adjacency = build_file_adjacency(_graph())

    assert adjacency['src/controller.py']['src/validator.py'] > 0
    assert adjacency['src/validator.py']['src/controller.py'] > 0
    assert adjacency['src/service.py']['src/repository.py'] > 0
    assert adjacency['src/repository.py']['src/service.py'] > 0


def test_personalized_pagerank_discovers_forward_dependencies():
    scores = personalized_pagerank(
        _graph(),
        {'src/controller.py': 1.0},
        damping=0.72,
        iterations=30,
    )

    assert scores['src/controller.py'] == max(scores.values())
    assert scores['src/validator.py'] > 0
    assert scores['src/service.py'] > 0
    assert scores['src/repository.py'] > 0
    assert sum(scores.values()) == pytest.approx(1.0, abs=1e-8)


def test_personalized_pagerank_is_deterministic_and_ignores_unknown_seeds():
    first = personalized_pagerank(
        _graph(), {'missing.py': 100.0, 'src/controller.py': 2.0}
    )
    second = personalized_pagerank(
        _graph(), {'src/controller.py': 2.0, 'missing.py': 100.0}
    )

    assert first == second
    assert 'missing.py' not in first


def test_empty_or_invalid_inputs_return_empty_scores():
    assert personalized_pagerank({}, {'src/a.py': 1.0}) == {}
    assert personalized_pagerank(_graph(), {}) == {}
    assert personalized_pagerank(_graph(), {'missing.py': 1.0}) == {}
