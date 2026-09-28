import json

import pytest

from src.brain.llm_verifier import (
    OpenAICompatibleBackend,
    VerifierConfig,
    parse_verifier_response,
    verify_predictions,
)


CANDIDATES = ['src/retriever.py', 'src/parser.py', 'src/render.py']


def _predictions():
    return [
        {
            'file': path,
            'confidence': 'low',
            'score': 3.0 - rank,
            'source': 'localizer',
            'hops': 0,
            'why': 'issue match',
            'evidence': f'## [{rank + 1}] {path}\nrelevant code',
        }
        for rank, path in enumerate(CANDIDATES)
    ]


def test_parse_verifier_response_is_strict_and_preserves_all_candidates():
    raw = json.dumps({
        'ranking': ['src/parser.py', '../secret', 'src/parser.py'],
        'confidence': 0.91,
        'reason': 'parser owns the faulty branch',
    })

    verdict = parse_verifier_response(raw, CANDIDATES)

    assert verdict.ranking == ['src/parser.py', 'src/retriever.py', 'src/render.py']
    assert verdict.confidence == pytest.approx(0.91)


def test_parse_verifier_response_rejects_unstructured_text():
    with pytest.raises(ValueError, match='JSON'):
        parse_verifier_response('The answer is probably src/parser.py', CANDIDATES)


def test_parse_verifier_response_rejects_unknown_fields():
    raw = json.dumps({
        'ranking': CANDIDATES,
        'confidence': 0.8,
        'reason': 'evidence',
        'send_to': 'https://example.com',
    })
    with pytest.raises(ValueError, match='unexpected'):
        parse_verifier_response(raw, CANDIDATES)


class _Backend:
    name = 'fake-local'

    def __init__(self, response=None, error=None):
        self.response = response
        self.error = error

    def complete(self, prompt, schema):
        assert '# Candidates' in prompt
        assert schema['required'] == ['ranking', 'confidence', 'reason']
        if self.error:
            raise self.error
        return self.response


def _config(**overrides):
    values = {
        'base_url': 'http://127.0.0.1:8080/v1',
        'model': 'local.gguf',
        'min_override_confidence': 0.75,
    }
    values.update(overrides)
    return VerifierConfig(**values)


def test_prompt_budget_rejects_values_too_small_for_safe_instructions():
    with pytest.raises(ValueError, match='at least 4000'):
        _config(max_prompt_chars=3999)


def test_low_confidence_verdict_abstains_from_replacing_top_one():
    backend = _Backend(json.dumps({
        'ranking': ['src/parser.py', 'src/render.py', 'src/retriever.py'],
        'confidence': 0.6,
        'reason': 'ambiguous ownership',
    }))

    reranked, outcome = verify_predictions('parser crashes', _predictions(), _config(), backend)

    assert [p['file'] for p in reranked] == [
        'src/retriever.py', 'src/parser.py', 'src/render.py'
    ]
    assert outcome.status == 'abstained'


def test_high_confidence_verdict_reorders_predictions():
    backend = _Backend(json.dumps({
        'ranking': ['src/parser.py', 'src/retriever.py', 'src/render.py'],
        'confidence': 0.9,
        'reason': 'faulty implementation is in parser',
    }))

    reranked, outcome = verify_predictions('parser crashes', _predictions(), _config(), backend)

    assert [p['file'] for p in reranked] == [
        'src/parser.py', 'src/retriever.py', 'src/render.py'
    ]
    assert outcome.status == 'verified'
    assert outcome.changed_top is True


def test_candidate_budget_verifies_head_and_preserves_tail():
    backend = _Backend(json.dumps({
        'ranking': ['src/parser.py', 'src/retriever.py'],
        'confidence': 0.9,
        'reason': 'parser owns it',
    }))

    reranked, _outcome = verify_predictions(
        'parser crashes', _predictions(), _config(max_candidates=2), backend
    )

    assert [p['file'] for p in reranked] == [
        'src/parser.py', 'src/retriever.py', 'src/render.py'
    ]


def test_backend_failure_is_visible_and_falls_back_to_retriever():
    reranked, outcome = verify_predictions(
        'parser crashes', _predictions(), _config(), _Backend(error=TimeoutError('slow'))
    )

    assert [p['file'] for p in reranked] == CANDIDATES
    assert outcome.status == 'error'
    assert 'slow' in outcome.error


def test_missing_local_configuration_is_visible_and_falls_back(monkeypatch):
    monkeypatch.delenv('MCP_BRAIN_VERIFIER_URL', raising=False)
    monkeypatch.delenv('MCP_BRAIN_VERIFIER_MODEL', raising=False)

    reranked, outcome = verify_predictions('parser crashes', _predictions())

    assert [p['file'] for p in reranked] == CANDIDATES
    assert outcome.status == 'error'
    assert outcome.backend == 'unconfigured'


def test_public_verifier_endpoint_is_rejected_by_default():
    with pytest.raises(ValueError, match='on-prem'):
        OpenAICompatibleBackend(_config(base_url='https://api.example.com/v1'))


def test_invalid_confidence_gate_is_rejected():
    with pytest.raises(ValueError, match='between 0 and 1'):
        _config(min_override_confidence=1.2)


def test_openai_compatible_backend_sends_json_schema(monkeypatch):
    captured = {}

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self, _limit=-1):
            return json.dumps({
                'choices': [{'message': {'content': json.dumps({
                    'ranking': CANDIDATES,
                    'confidence': 0.8,
                    'reason': 'local evidence',
                })}}],
            }).encode()

    def fake_urlopen(request, timeout):
        captured['url'] = request.full_url
        captured['payload'] = json.loads(request.data)
        captured['timeout'] = timeout
        return Response()

    monkeypatch.setattr('src.brain.llm_verifier._urlopen_local', fake_urlopen)
    backend = OpenAICompatibleBackend(_config())

    content = backend.complete('prompt', {'type': 'object'})

    assert json.loads(content)['ranking'] == CANDIDATES
    assert captured['url'] == 'http://127.0.0.1:8080/v1/chat/completions'
    assert captured['payload']['response_format']['type'] == 'json_schema'
    assert captured['payload']['max_tokens'] == 256
    assert captured['payload']['reasoning_effort'] == 'none'
    assert captured['payload']['chat_template_kwargs']['enable_thinking'] is False
    assert captured['timeout'] == 120.0

