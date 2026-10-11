# ZMW Assistant

Local LLM home assistant: maps natural language ("turn kitchen lights on") to a ZMW MQTT service call
(`{"service": "ZmwLights", "command": "all_lights_on", "args": {"prefix": "kitchen"}}`) or `DONT_KNOW`.
Runs CPU-only on `bati.casa` with small Q4_K_M GGUF models via `llama-cpp-python`.

## How it works

1. Input arrives via `/assistant_ask` (web UI) or `zmw_speech_to_text` MQTT messages.
2. System prompt = `_LLM_PREAMBLE` (with few-shot examples) + compacted interfaces of all discovered services.
   Services add known entities (light names, speakers, ...) through `llm_context_extra` in their MQTT description.
3. A GBNF grammar built from the same interfaces constrains output to valid service/command/args or `DONT_KNOW`
   (toggle with `llm_use_grammar`).
4. The reply is executed over MQTT and logged to `/get_history`.

## Files

- `zmw_assistant.py`: service, preamble, `LazyLlama` wrapper, endpoints, CLI overrides
  (`--llm-model-path`, `--llm-use-grammar`).
- `services_tracker.py`: service discovery, `compact_ifaces_for_llm`, `build_gbnf_grammar`, `_SKIP_SERVICES`
  (services with no useful LLM actions).
- `models/`: GGUF models (`make download_all_models`) and old model comparison results.

## Models (Q4_K_M)

Qwen 2.5 1.5B was the best, with Llama 3.2 1B a close second (faster, but worse on ambiguous prompts).
SmolLM2 1.7B was passable but slow. Llama 3.2 3B and TinyLlama hallucinated or were too slow, Gemma 3 1B
was useless, and Llama 3.1 8B OOMs on the target. Without the grammar, all small models hallucinate.

## Small-model lessons

- More than about 3 few-shot examples hurts accuracy.
- A static system prompt lets `llama-cpp-python` reuse the KV cache, so queries after the first are 2-3x faster.
  Avoid per-query context changes.
- Run with `PYTHONUNBUFFERED=1` when piping output over SSH.

## Debugging

- `/debug_llm_context` shows the exact system prompt, token count and grammar; `/update_llm_context` rediscovers
  services first. A wrong answer is usually missing or ambiguous context, or the grammar allowing only bad options.
- Run with `--llm-use-grammar=false` to see what the model wants to say unconstrained.
- Pass `logprobs=True, top_logprobs=3` to `create_chat_completion` to see per-token confidence and alternatives.
