"""Test STEP 7 — tool MCP brain_observability + auto_instrument."""
import yaml
import pytest

from src.brain.observability import reset, record_call
from src.tools.observability_tool import (
    observability_impl,
    register_observability_tool,
    auto_instrument_existing_tools,
)


@pytest.fixture(autouse=True)
def clean_registry():
    reset()
    yield
    reset()


# ======================================================================
# 1. observability_impl structure
# ======================================================================
class TestImpl:
    def test_returns_yaml(self, tmp_brain):
        out = observability_impl('demo')
        data = yaml.safe_load(out)
        assert 'system' in data
        assert 'tools' in data

    def test_system_fields(self, tmp_brain):
        out = observability_impl('demo')
        data = yaml.safe_load(out)
        sys_info = data['system']
        for k in ('python', 'pid', 'uptime_seconds', 'timestamp'):
            assert k in sys_info

    def test_tools_empty_message(self, tmp_brain):
        out = observability_impl('demo')
        data = yaml.safe_load(out)
        # Nessuna tool call registrata
        assert data['tools'] == 'no tool calls recorded yet'

    def test_tools_populated_after_calls(self, tmp_brain):
        record_call('brain_demo', 42.0, 500)
        out = observability_impl('demo')
        data = yaml.safe_load(out)
        assert isinstance(data['tools'], dict)
        assert 'brain_demo' in data['tools']
        assert data['tools']['brain_demo']['count'] == 1

    def test_tools_sorted_by_count_desc(self, tmp_brain):
        record_call('b', 1.0, 1)
        for _ in range(3):
            record_call('a', 1.0, 1)
        for _ in range(2):
            record_call('c', 1.0, 1)
        out = observability_impl('demo')
        data = yaml.safe_load(out)
        tools_order = list(data['tools'].keys())
        # a(3) > c(2) > b(1)
        assert tools_order == ['a', 'c', 'b']

    def test_includes_graph_section_if_present(self, tmp_brain, monkeypatch):
        # Forziamo load_graph a ritornare None per rendere il test deterministico
        # indipendentemente da dove è installato il repo dell'utente.
        import src.tools.observability_tool as mod
        monkeypatch.setattr(mod, '_collect_graph_stats',
                            lambda: {'present': False})
        out = observability_impl('demo')
        data = yaml.safe_load(out)
        assert 'code_graph' in data
        assert data['code_graph']['present'] is False

    def test_includes_index_section_if_present(self, tmp_brain):
        out = observability_impl('demo')
        data = yaml.safe_load(out)
        assert 'file_index' in data

    def test_memory_counters_present(self, tmp_brain):
        from src.storage.db import save_memory
        save_memory('demo', 1, 'decision', 'd: x', status='active')
        save_memory('demo', 1, 'avoid', 'a: y', status='suspect')
        out = observability_impl('demo')
        data = yaml.safe_load(out)
        assert 'memories' in data
        assert data['memories']['by_status'].get('active', 0) >= 1
        assert data['memories']['by_status'].get('suspect', 0) >= 1

    def test_feedback_section_when_step5_present(self, tmp_brain):
        from src.brain.feedback_store import init_feedback_schema
        init_feedback_schema()
        out = observability_impl('demo', since_days=7)
        data = yaml.safe_load(out)
        assert 'feedback' in data
        assert data['feedback']['window_days'] == 7


# ======================================================================
# 2. Registration
# ======================================================================
class FakeMCP:
    def __init__(self):
        self.registered = []

    def tool(self):
        def deco(fn):
            self.registered.append(fn)
            return fn
        return deco


class TestRegistration:
    def test_registers_one_tool(self):
        mcp = FakeMCP()
        register_observability_tool(mcp)
        assert len(mcp.registered) == 1
        assert mcp.registered[0].__name__ == 'brain_observability'

    def test_tool_is_itself_observed(self, tmp_brain):
        """brain_observability must self-record: calling it should add
        the tool to the snapshot."""
        mcp = FakeMCP()
        register_observability_tool(mcp)
        fn = mcp.registered[0]
        result = fn(project='demo')
        assert isinstance(result, str)
        # Dopo la call, snapshot contiene brain_observability
        from src.brain.observability import get_snapshot
        assert 'brain_observability' in get_snapshot()


# ======================================================================
# 3. auto_instrument — dict-based registry
# ======================================================================
class FakeToolRegistry:
    """Mock che espone _tool_manager._tools come dict."""
    class _TM:
        def __init__(self):
            self._tools = {}
    def __init__(self):
        self._tool_manager = self._TM()


class TestAutoInstrument:
    def test_empty_registry_returns_zero(self):
        mcp = FakeToolRegistry()
        assert auto_instrument_existing_tools(mcp) == 0

    def test_instruments_callable_tools(self):
        from src.brain.observability import get_snapshot, reset
        reset()

        mcp = FakeToolRegistry()
        # Aggiungo 2 tool come callable diretti
        def tool_a(x):
            return f'a-{x}'
        def tool_b(x):
            return f'b-{x}'
        mcp._tool_manager._tools['tool_a'] = tool_a
        mcp._tool_manager._tools['tool_b'] = tool_b

        count = auto_instrument_existing_tools(mcp)
        assert count == 2

        # Chiamo i tool istrumentati
        wrapped_a = mcp._tool_manager._tools['tool_a']
        assert wrapped_a('x') == 'a-x'
        snap = get_snapshot()
        assert 'tool_a' in snap
        assert snap['tool_a']['count'] == 1

    def test_idempotent(self):
        mcp = FakeToolRegistry()
        def tool_a():
            return 'ok'
        mcp._tool_manager._tools['tool_a'] = tool_a
        auto_instrument_existing_tools(mcp)
        # Seconda chiamata: 0 nuovi tool istrumentati
        assert auto_instrument_existing_tools(mcp) == 0

    def test_no_registry_returns_zero(self):
        class Barebone:
            pass
        assert auto_instrument_existing_tools(Barebone()) == 0

    def test_instruments_objects_with_fn(self):
        """Alcune versioni di FastMCP usano wrapper con attributo `.fn`."""
        from src.brain.observability import get_snapshot

        class ToolWrapper:
            def __init__(self, fn):
                self.fn = fn

        mcp = FakeToolRegistry()
        def real(): return 'wrapped'
        mcp._tool_manager._tools['wrapped_tool'] = ToolWrapper(real)

        count = auto_instrument_existing_tools(mcp)
        assert count == 1
        # Chiama la fn istrumentata
        mcp._tool_manager._tools['wrapped_tool'].fn()
        snap = get_snapshot()
        assert 'wrapped_tool' in snap
