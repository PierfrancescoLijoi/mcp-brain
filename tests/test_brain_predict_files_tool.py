"""
Test STEP 2.4 — Tool MCP brain_predict_files.

Testiamo la funzione `predict_files_impl` (la logica, senza FastMCP) e la
registrazione del tool con un mock minimale di `mcp`.
"""
import yaml
import pytest

from src.brain.file_indexer import _finalize_index, save_index
from src.tools.predict_files_tool import (
    predict_files_impl,
    register_predict_files_tool,
)


@pytest.fixture
def fake_index(tmp_brain):
    def _make(files_data):
        for _, d in files_data.items():
            d.setdefault('mtime', 0.0)
        idx = _finalize_index(files_data)
        save_index(idx)
        return idx
    return _make


# ======================================================================
# predict_files_impl (pure)
# ======================================================================
class TestPredictFilesImpl:
    def test_returns_yaml_with_predictions(self, fake_index):
        fake_index({
            'src/auth.py': {'symbols': ['login'], 'identifiers': []},
        })
        out = predict_files_impl('login')
        data = yaml.safe_load(out)
        assert 'predictions' in data
        assert isinstance(data['predictions'], list)
        assert data['predictions'][0]['file'] == 'src/auth.py'

    def test_schema_fields_present(self, fake_index):
        fake_index({
            'src/auth.py': {'symbols': ['login'], 'identifiers': []},
        })
        out = predict_files_impl('login')
        data = yaml.safe_load(out)
        pred = data['predictions'][0]
        for key in ('file', 'confidence', 'score', 'source', 'hops', 'why'):
            assert key in pred, f'missing key: {key}'

    def test_empty_title_returns_error(self, fake_index):
        fake_index({'src/a.py': {'symbols': ['x'], 'identifiers': []}})
        assert predict_files_impl('').startswith('error')
        assert predict_files_impl('   ').startswith('error')

    def test_no_matches_returns_hint(self, fake_index):
        fake_index({'src/a.py': {'symbols': ['x'], 'identifiers': []}})
        out = predict_files_impl('kubernetes autoscaling orchestration')
        data = yaml.safe_load(out)
        assert data['predictions'] == []
        # Deve esserci un hint utile
        assert 'hint' in data

    def test_respects_max_hops(self, fake_index):
        fake_index({
            'src/a.py': {'symbols': ['login'], 'identifiers': []},
        })
        out = predict_files_impl('login', max_hops=0)
        data = yaml.safe_load(out)
        # Nessun hop > 0 atteso
        assert all(p.get('hops', 0) == 0 for p in data['predictions'])

    def test_respects_top_k(self, fake_index):
        files = {
            f'src/f{i}.py': {'symbols': ['auth'], 'identifiers': []}
            for i in range(25)
        }
        fake_index(files)
        out = predict_files_impl('auth', top_k=3)
        data = yaml.safe_load(out)
        assert len(data['predictions']) == 3

    def test_use_semantic_parameter_accepted(self, fake_index, monkeypatch):
        monkeypatch.setenv('MCP_BRAIN_SEMANTIC', '0')
        fake_index({
            'src/auth.py': {'symbols': ['login'], 'identifiers': []},
        })
        # Non deve crashare anche se la lib non è installata
        out = predict_files_impl('login', use_semantic=True)
        data = yaml.safe_load(out)
        assert data['predictions'][0]['file'] == 'src/auth.py'

    def test_body_is_used_for_keywords(self, fake_index):
        """Il body deve contribuire alle keyword, non solo il title."""
        fake_index({
            'src/auth.py': {'symbols': ['jwt_validator'], 'identifiers': []},
            'src/misc.py': {'symbols': ['unrelated'], 'identifiers': []},
        })
        # Title generico, body con keyword specifica
        out = predict_files_impl('bug fix', body='fix jwt_validator on login')
        data = yaml.safe_load(out)
        assert data['predictions'][0]['file'] == 'src/auth.py'

    def test_yaml_is_well_formed(self, fake_index):
        fake_index({
            'src/auth.py': {'symbols': ['login'], 'identifiers': []},
        })
        out = predict_files_impl('login')
        # Non deve lanciare eccezione
        parsed = yaml.safe_load(out)
        assert parsed is not None


# ======================================================================
# register_predict_files_tool (integrazione FastMCP)
# ======================================================================
class FakeMCP:
    """Mock minimale per testare la registrazione di tool."""
    def __init__(self):
        self.registered = []

    def tool(self):
        def decorator(fn):
            self.registered.append(fn)
            return fn
        return decorator


class TestRegistration:
    def test_register_adds_one_tool(self):
        mcp = FakeMCP()
        register_predict_files_tool(mcp)
        assert len(mcp.registered) == 1

    def test_registered_tool_is_callable(self):
        mcp = FakeMCP()
        register_predict_files_tool(mcp)
        tool_fn = mcp.registered[0]
        assert callable(tool_fn)
        assert tool_fn.__name__ == 'brain_predict_files'

    def test_registered_tool_has_docstring(self):
        mcp = FakeMCP()
        register_predict_files_tool(mcp)
        tool_fn = mcp.registered[0]
        assert tool_fn.__doc__ and len(tool_fn.__doc__) > 20

    def test_tool_invocation_returns_yaml(self, fake_index):
        mcp = FakeMCP()
        register_predict_files_tool(mcp)
        tool_fn = mcp.registered[0]

        fake_index({
            'src/auth.py': {'symbols': ['login'], 'identifiers': []},
        })
        result = tool_fn(project='demo', title='login fix')
        data = yaml.safe_load(result)
        assert 'predictions' in data
        assert data['predictions'][0]['file'] == 'src/auth.py'

    def test_tool_catches_exceptions(self, fake_index):
        mcp = FakeMCP()
        register_predict_files_tool(mcp)
        tool_fn = mcp.registered[0]

        # Non esiste index → fake_index non chiamato
        # deve ritornare 'no matches' o 'error' senza raise
        result = tool_fn(project='demo', title='login fix')
        assert isinstance(result, str)
