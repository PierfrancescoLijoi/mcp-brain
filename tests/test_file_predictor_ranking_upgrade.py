import pytest

from src.brain.file_indexer import _finalize_index, save_index
from src.brain.file_predictor import predict_files_explained


@pytest.fixture
def fake_index(tmp_brain):
    def _make(files_data):
        for _, d in files_data.items():
            d.setdefault('mtime', 0.0)
        idx = _finalize_index(files_data)
        save_index(idx)
        return idx
    return _make


def test_dotted_module_path_boost_ranks_exact_file(fake_index):
    fake_index({
        'astropy/modeling/core.py': {'symbols': ['compoundmodel'], 'identifiers': ['separable']},
        'astropy/modeling/separable.py': {'symbols': ['separability_matrix'], 'identifiers': []},
    })
    res = predict_files_explained('Bug in astropy.modeling.separable with CompoundModel')
    assert res[0]['file'] == 'astropy/modeling/separable.py'
    assert 'path' in res[0]['matches']


def test_test_file_mention_maps_to_source_file(fake_index):
    fake_index({
        'pkg/parser.py': {'symbols': ['parse_config'], 'identifiers': []},
        'pkg/tests/test_parser.py': {'symbols': ['test_parse_config'], 'identifiers': ['parse_config']},
    })
    res = predict_files_explained('Failure in pkg/tests/test_parser.py')
    assert res[0]['file'] == 'pkg/parser.py'
    assert 'test-to-source' in res[0]['why']


def test_breakdown_is_exposed_for_debugging(fake_index):
    fake_index({
        'src/auth.py': {'symbols': ['login'], 'identifiers': []},
    })
    res = predict_files_explained('login')
    assert 'breakdown' in res[0]
    assert 'bm25_terms' in res[0]['breakdown']
