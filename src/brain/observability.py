"""
STEP 7 — Observability collector.

Un registro in-memory thread-safe di metriche per tool call. Ogni wrapping
`@observed("tool_name")` aggiunge automaticamente:

  - count di chiamate
  - count di errori
  - latenze p50 / p95 / p99 / avg
  - dimensione media dell'output (char)
  - timestamp last call

Le metriche vivono nel processo del server mcp-brain. Sono un ROLLING
WINDOW (default 500 chiamate per tool) per evitare memory leak su server
long-running. Quando il server riparte, ripartono da zero.

Per metriche persistenti → STEP 5 (`feedback_stats`) o dump periodico su
file (fuori scope di questo step).

Structured JSON logging opzionale via env `MCP_BRAIN_JSON_LOGS=1`:
  ogni tool call scrive UN record JSON su `LOG_PATH` tipo:
    {"ts":"2026-...","tool":"brain_predict_files","ms":42,"ok":true,"size":512}
  comodo per grep/jq o ingestion in ELK/Loki/Datadog.
"""
from __future__ import annotations

import functools
import json
import logging
import os
import threading
import time
from collections import deque
from datetime import datetime, timezone
from typing import Any, Callable, Deque, Dict, List, Optional

# ------------------------------------------------------------------
# Storage: rolling windows per-tool
# ------------------------------------------------------------------
_LOCK = threading.Lock()
_WINDOW_SIZE = 500  # per-tool max samples


class _ToolMetrics:
    """Rolling-window metrics for a single tool."""
    __slots__ = ('count', 'errors', 'durations_ms', 'sizes', 'last_call_at',
                 'last_error', 'errors_by_type')

    def __init__(self):
        self.count: int = 0
        self.errors: int = 0
        self.durations_ms: Deque[float] = deque(maxlen=_WINDOW_SIZE)
        self.sizes: Deque[int] = deque(maxlen=_WINDOW_SIZE)
        self.last_call_at: Optional[str] = None
        self.last_error: Optional[str] = None
        self.errors_by_type: Dict[str, int] = {}


_REGISTRY: Dict[str, _ToolMetrics] = {}


# ------------------------------------------------------------------
# Public API — recording
# ------------------------------------------------------------------
def record_call(
    tool: str,
    duration_ms: float,
    output_size: int,
    error: Optional[Exception] = None,
) -> None:
    """Registra una chiamata. Thread-safe, bounded memory."""
    with _LOCK:
        m = _REGISTRY.get(tool)
        if m is None:
            m = _ToolMetrics()
            _REGISTRY[tool] = m
        m.count += 1
        m.durations_ms.append(float(duration_ms))
        m.sizes.append(int(output_size))
        m.last_call_at = datetime.now(timezone.utc).isoformat()
        if error is not None:
            m.errors += 1
            etype = error.__class__.__name__
            m.errors_by_type[etype] = m.errors_by_type.get(etype, 0) + 1
            m.last_error = f'{etype}: {str(error)[:160]}'


def reset() -> None:
    """Azzera tutto il registro (utile in test)."""
    with _LOCK:
        _REGISTRY.clear()


# ------------------------------------------------------------------
# Percentiles (self-contained, no numpy)
# ------------------------------------------------------------------
def _percentile(sorted_values: List[float], pct: float) -> float:
    if not sorted_values:
        return 0.0
    if len(sorted_values) == 1:
        return sorted_values[0]
    # Interpolazione lineare standard
    k = (len(sorted_values) - 1) * pct / 100.0
    f = int(k)
    c = min(f + 1, len(sorted_values) - 1)
    if f == c:
        return sorted_values[int(k)]
    return sorted_values[f] + (sorted_values[c] - sorted_values[f]) * (k - f)


def _summarize(m: _ToolMetrics) -> Dict[str, Any]:
    durations = sorted(m.durations_ms)
    sizes = list(m.sizes)
    summary: Dict[str, Any] = {
        'count': m.count,
        'errors': m.errors,
        'error_rate': round(m.errors / m.count, 3) if m.count else 0.0,
        'last_call_at': m.last_call_at,
    }
    if durations:
        summary['latency_ms'] = {
            'avg': round(sum(durations) / len(durations), 2),
            'p50': round(_percentile(durations, 50), 2),
            'p95': round(_percentile(durations, 95), 2),
            'p99': round(_percentile(durations, 99), 2),
            'max': round(max(durations), 2),
        }
    if sizes:
        summary['output_chars'] = {
            'avg': int(sum(sizes) / len(sizes)),
            'max': max(sizes),
        }
    if m.errors_by_type:
        summary['errors_by_type'] = dict(m.errors_by_type)
    if m.last_error:
        summary['last_error'] = m.last_error
    return summary


# ------------------------------------------------------------------
# Public API — reading
# ------------------------------------------------------------------
def get_snapshot() -> Dict[str, Dict[str, Any]]:
    """Snapshot corrente di tutte le metriche, tool-by-tool."""
    with _LOCK:
        return {name: _summarize(m) for name, m in _REGISTRY.items()}


def get_tool_stats(tool: str) -> Optional[Dict[str, Any]]:
    with _LOCK:
        m = _REGISTRY.get(tool)
        return _summarize(m) if m else None


def get_window_size() -> int:
    return _WINDOW_SIZE


# ------------------------------------------------------------------
# Decorator
# ------------------------------------------------------------------
def observed(tool_name: Optional[str] = None) -> Callable:
    """
    Decoratore che istrumenta un callable (tool MCP, funzione pura, etc.).
    Intercetta return string/length-able, tempi, eccezioni.

    Uso:
        @observed('brain_my_tool')
        def brain_my_tool(...): ...

    Se tool_name non è passato, usa __name__ della funzione.
    """
    def _decorate(fn: Callable) -> Callable:
        name = tool_name or fn.__name__

        @functools.wraps(fn)
        def _wrapper(*args, **kwargs):
            start = time.perf_counter()
            error: Optional[Exception] = None
            result: Any = None
            try:
                result = fn(*args, **kwargs)
                return result
            except Exception as e:
                error = e
                raise
            finally:
                duration_ms = (time.perf_counter() - start) * 1000.0
                try:
                    size = len(result) if isinstance(result, str) else (
                        len(json.dumps(result, default=str)) if result is not None else 0
                    )
                except Exception:
                    size = 0
                record_call(name, duration_ms, size, error)
                _emit_structured_log(name, duration_ms, size, error)

        return _wrapper
    return _decorate


# ------------------------------------------------------------------
# Optional structured JSON logging
# ------------------------------------------------------------------
def _structured_logs_enabled() -> bool:
    return os.environ.get('MCP_BRAIN_JSON_LOGS', '0') == '1'


def _emit_structured_log(
    tool: str, duration_ms: float, size: int, error: Optional[Exception]
) -> None:
    if not _structured_logs_enabled():
        return
    try:
        payload = {
            'ts': datetime.now(timezone.utc).isoformat(),
            'tool': tool,
            'ms': round(duration_ms, 2),
            'size': size,
            'ok': error is None,
        }
        if error is not None:
            payload['err'] = error.__class__.__name__
            payload['msg'] = str(error)[:240]
        logging.info('MCPB_METRIC %s', json.dumps(payload, default=str))
    except Exception:
        # Never break the tool call because of logging
        pass
