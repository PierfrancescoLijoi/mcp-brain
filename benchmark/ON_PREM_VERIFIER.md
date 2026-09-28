# On-prem verifier contract

## Iteration compact

- **Goal:** rerank the localizer shortlist without sending repository code or issue text outside the operator's infrastructure.
- **Decision changed:** which candidate file is placed at rank 1 for the coding agent.
- **Primary metric:** SWE-bench file-localization Hit@1.
- **Guardrails:** Hit@3/5/10, valid-response rate, explicit failure rate, p95 latency, peak memory, and no public-network endpoint by default.
- **Unacceptable mistakes:** silently treating an invalid model response as a successful verification; returning a path outside the candidate set; transmitting code to a public endpoint without explicit opt-in.
- **Fallback:** preserve the deterministic retriever order and report `verification.status: error` or `abstained`.
- **Baseline (SWE-bench Lite, 300):** retriever 64.67/82.33/86.00/91.00 and Sonnet verifier v2 71.00/85.67/88.33/92.67 at Hit@1/3/5/10.
- **Local evaluation (repo-mixed 100, not promoted):** Qwen3-4B Q5_K_M policy v4 produced 100/100 valid responses but changed retriever Hit@1/3/5/10 from 68/85/86/89 to 66/83/86/89. It made 25 top-file changes (8 gains, 10 losses, 7 neutral), with 2.10 s p50 and 2.67 s p95 verifier latency. This model/policy is therefore rejected for automatic reranking; local reranking remains opt-in and experimental.
- **Coder-model evaluation (same 100, not promoted):** Qwen2.5-Coder-7B-Instruct Q4_K_M also produced 100/100 valid responses but changed Hit@1/3/5/10 to 67/84/86/89. Its 25 top-file changes contained 8 gains, 9 losses, and 8 neutral changes; p50/p95 verifier latency was 3.15/4.01 s. Confidence was 0.9 for every change, so a confidence-only gate cannot calibrate this model. The 7B configuration is also rejected for automatic reranking.
- **Model-domain warning:** the shipped LambdaMART artifact was trained on Python repositories. Multi-language parsing and serving are supported, but cross-language quality requires separate promotion data.

## Runtime architecture

```text
MCP tool / benchmark
        |
        v
strict verifier contract + confidence gate
        |
        v
OpenAI-compatible API on a private address
        |
        +-- llama.cpp / llama-server (reference runtime)
        +-- Ollama (set OLLAMA_NO_CLOUD=1)
        +-- vLLM (Linux GPU / high throughput)
        +-- LocalAI (gateway deployments)
```

The Python client uses only the standard library. It requests JSON constrained by
a schema, validates paths and fields again locally, and never accepts a path that
was not supplied by the retriever.

## Minimal llama.cpp setup

Provision the `llama-server` binary and a commercially compatible GGUF model on
disk before moving into an air-gapped environment. Record the SHA-256 hashes and
the separate licenses for the runtime and model weights.

```powershell
llama-server -m C:\models\code-model.gguf --host 127.0.0.1 --port 8080 --reasoning off
$env:MCP_BRAIN_VERIFIER_URL = "http://127.0.0.1:8080/v1"
$env:MCP_BRAIN_VERIFIER_MODEL = "code-model"
$env:MCP_BRAIN_VERIFIER_MIN_CONFIDENCE = "0.75"
$env:MCP_BRAIN_VERIFIER_MAX_CANDIDATES = "5"
$env:MCP_BRAIN_VERIFIER_MAX_PROMPT_CHARS = "8000"
$env:MCP_BRAIN_VERIFIER_MAX_OUTPUT_TOKENS = "256"
mcp-brain doctor
```

Then call `brain_predict_files` with `verify_local=true`. When local verification
is disabled or unavailable, the tool continues to return the deterministic
retriever ranking and evidence cards.

For Ollama, use `http://127.0.0.1:11434/v1` and explicitly disable its optional
cloud features:

```powershell
$env:OLLAMA_NO_CLOUD = "1"
```

## Reproducible v3 benchmark

```powershell
python -m benchmark.loclab_verify `
  --ranking benchmark/tmp/loclab/rank_v4d.json `
  --backend openai-compatible `
  --base-url http://127.0.0.1:8080/v1 `
  --model code-model `
  --top 15 --jobs 1
```

Cache identity includes backend, model, top-k, verified-head size, confidence
gate, prompt/output budgets, card version, and policy version. Successful records
carry verifier metadata. Transport, timeout, and schema failures go to a separate
`*.failures.json` ledger and are excluded from quality metrics.

## Promotion gates

Do not promote a local verifier merely because one aggregate score improves.

1. Valid structured responses >= 99%; no hidden failures.
2. Hit@1 improves the deterministic retriever by at least 3 percentage points.
3. Hit@10 regresses by no more than 0.5 percentage points.
4. Report per-repository results and confidence-gate gain/loss counts.
5. Record runtime version, model file hash, prompt/card version, hardware, p50/p95 latency, and peak memory.
6. Before claiming general multi-language quality, evaluate at least three language families on held-out repositories. The Python SWE-bench result alone is not sufficient.

Rollback requires no model change: set `verify_local=false` or remove the two
`MCP_BRAIN_VERIFIER_*` variables. The deterministic retriever remains the known
good artifact.

## Security and licensing

- Public hosts are rejected unless `MCP_BRAIN_ALLOW_REMOTE_VERIFIER=1` is set.
- Bind the runtime to loopback unless LAN access is required; use firewall/ACL controls for LAN serving.
- Do not log prompts, source cards, API keys, or raw model output in production.
- Runtime and model licenses are separate. Preserve both license texts, exact versions, and hashes.
- Pre-provision binaries, tokenizers, chat templates, and weights; never depend on runtime downloads in an air-gapped deployment.

Primary runtime references: [llama.cpp server](https://github.com/ggml-org/llama.cpp/blob/master/tools/server/README.md), [Ollama OpenAI compatibility](https://github.com/ollama/ollama/blob/main/docs/api/openai-compatibility.mdx), [Ollama local-only mode](https://docs.ollama.com/faq#how-do-i-disable-ollama-s-cloud-features), and [vLLM OpenAI server](https://docs.vllm.ai/en/latest/serving/online_serving/openai_compatible_server/).
