# ZMW Assistant

Local LLM-based home automation assistant. Takes natural language commands ("turn kitchen lights on") and maps them to MQTT service calls (`{"service": "ZmwLights", "command": "all_lights_on", "args": {"prefix": "kitchen"}}`).

Runs on a resource-constrained host (`bati.casa`) using small quantized models (1-3B params, Q4_K_M GGUF) via `llama-cpp-python`. No GPU — CPU-only inference.

## How it works

1. **User says something** (via web UI, Telegram voice, etc.)
2. **Context assembly** — service descriptions are compacted, enriched with known entities (light names, sensor names, speaker names, etc.), and optionally filtered by keyword to the top 3 services.
3. **System prompt** = preamble + service descriptions + few-shot examples.
4. **GBNF grammar constraint** forces the LLM to output only valid JSON matching real service/command/arg combinations, or `DONT_KNOW`. Built dynamically from the services in context. Params with known values (light names, speaker names, etc.) are constrained to valid options.
5. **LLM responds** with a structured JSON command or `DONT_KNOW`.

## Files

- `zmw_assistant.py` — Main service. Preamble (`_LLM_PREAMBLE`), `LazyLlama` wrapper, `/assistant_ask` endpoint, benchmark harness.
- `services_tracker.py` — MQTT service discovery, interface compacting (`compact_ifaces_for_llm`), keyword filtering (`get_svcs_llm_context_filtered`), GBNF grammar generation (`build_gbnf_grammar`). Shared helpers: `_tokenize_query`, `_score_keywords`, `_normalize_word`.
- `z2m_tracker.py` — Zigbee2MQTT device tracking via `Z2MProxy`. Compacts things grouped by type (lights, switches, sensors). Keyword filtering (`get_z2m_llm_context_filtered`). Imports shared helpers from `services_tracker`.
- `playground.py` — Standalone benchmark for prompt/preamble tuning. Loads JSON snapshot (`svcs.json`) instead of live MQTT. Self-contained copies of all compacting/grammar/enrichment logic. Runs all prompts against Qwen 2.5 1.5B (no compact, full context), reports OK/FAIL per prompt with expected vs actual service+command, shows score and system context. KV cache is prewarmed so all queries run at cached speed.
- `render_results.py` — Parses `playground.log` and renders an HTML comparison table (`results.html`). Cells are clickable to show full context. First column is the reference; matching responses in other columns show `=`.
- `svcs.json` — Snapshot of live service interfaces for offline use in playground.
- `BENCHMARK_PROMPT.md` — Instructions for Claude Code preamble-tuning sessions.
- `run_benchmark.sh` — Runs the full service on `bati.casa` with benchmark mode (SSH + `PYTHONUNBUFFERED=1`).
- `run_cmp_models.sh` — Runs benchmark across multiple models for comparison. Results go to `models/`.

## Models tested (all Q4_K_M GGUF)

| Model | Size | Result |
|---|---|---|
| **Qwen 2.5 1.5B Instruct** | 1.5B | Best option. Slightly better accuracy than Llama, slightly slower (~2-3s/query with KV cache) |
| Llama 3.2 1B Instruct | 1B | Close second. Slightly faster but worse on nuanced prompts |
| SmolLM2 1.7B Instruct | 1.7B | Passable (7/8) with grammar, ~50s |
| Llama 3.2 3B Instruct | 3B | Bad, hallucinations, ~90s |
| Gemma 3 1B IT | 1B | Useless — all DONT_KNOW with grammar, all hallucinations without |
| TinyLlama 1.1B Chat | 1.1B | Super slow and useless |
| Meta Llama 3.1 8B Instruct | 8B | OOMs on target hardware |

Grammar constraint is essential — without it, all small models hallucinate.

Between Qwen and Llama, Qwen has slightly better accuracy on ambiguous prompts. For example, "announce it's time to go" → Qwen picks `ZmwSpeakerAnnounce.tts(msg="It is time to go")` while Llama picks `ZmwSpeakerAnnounce.announcement_history` (wrong). Qwen is the default model in `playground.py`.

## Context format

Services use a compact format for consistent LLM pattern matching:
```
## ServiceName
Description
[Enriched entity lists: lights, sensors, speakers, etc.]
Commands:
- command_name(required_param): Description
- command_no_args: Description
```

Per-service enrichers (`_SVC_ENRICHERS`) add known entities to the context (light names/groups, sensor names, speaker names/groups, camera aliases, contact sensor states). Per-service grammar value extractors (`_SVC_GRAMMAR_VALUES`) constrain params to valid values in the GBNF grammar.

Filtering skips: `get_mqtt_description` commands, `_SKIP_SERVICES` (services with no useful LLM actions, e.g. ZmwShellyPlug, ZmwSpeechToText).

## Keyword filtering

Optional per-query filtering reduces the service context to the top 3 matches (`compact_svcs` config flag). Purpose and tradeoffs:

- **Reduces confusion** for small models (1-3B) by narrowing the choice set. With 15+ services, models are more likely to pick a wrong-but-valid option. With 3 focused services, accuracy improves.
- **Risk of excluding the right service** — if keyword matching misses (e.g. the user refers to a light by name but the keyword index doesn't include it), the model can't pick the correct answer. Enrichment data and grammar values are included in the keyword index to mitigate this.
- **Speed is worse with filtering** — without filtering, the system prompt is identical for every query, so `llama-cpp-python` reuses the KV cache. With filtering, the prompt changes per query and the cache is invalidated every time. In benchmarks, unfiltered queries are 2-3x faster after the first (cold cache) query.
- **Can be removed** if benchmark results show similar accuracy without filtering. The grammar constraint already prevents hallucinated service/command/arg names, so filtering is mainly about reducing choice confusion.

## Key constraints for small models

- More than 3 few-shot examples degrades performance
- Keyword filtering uses whole-word matching (set-based) — substring matching causes false positives
- Strip punctuation before tokenization
- `PYTHONUNBUFFERED=1` required when running over SSH pipes

## Debugging LLM responses

Small models (1-3B) can't explain their reasoning — they lack self-reflection ability, and the GBNF grammar constraint prevents free-text output anyway. Instead, debug by inspecting the inputs and probabilities:

**Log probabilities (`logprobs`)** — Pass `logprobs=True` and `top_logprobs=3` to `create_chat_completion` to see per-token confidence and what alternatives the model considered. Low logprobs mean the model was uncertain and the grammar forced a choice.

**Run without grammar** — In `playground.py`, comment out the `grammar=` parameter to see what the model wants to say unconstrained. Reveals whether the model understood the intent but the grammar pushed it down a wrong path.

**Check filtered context** — Most common root cause for wrong answers. If keyword filtering excluded the right service, the model can't pick it. Print `_tokenize_query(prompt)` to see what survived stopword removal, and inspect the filtered system context.

**Check the grammar** — Print `build_gbnf_grammar(svc_ifaces)` to see what the model was allowed to output. With few services in the filtered set, a wrong answer may just be the "least bad" option the grammar permits.

| Symptom | Likely cause | Debug with |
|---|---|---|
| Wrong service picked | Right service filtered out | Print filtered context + grammar |
| Wrong command on right service | Model confused by descriptions | logprobs to see alternatives |
| DONT_KNOW when it should match | Keyword filtering too aggressive | Print `_tokenize_query` + scores |
| Hallucinated garbage | Grammar not applied | Verify grammar is passed |

## Running

```bash
make playground_deps   # first time: install llama-cpp-python
make playground        # run playground.py locally (output to playground.log)
make render_results    # render playground.log to results.html
make download_all_models  # download all GGUF models
make devrun            # run full service (needs MQTT, Z2M, etc.)
bash run_benchmark.sh  # run benchmark on bati.casa
```
