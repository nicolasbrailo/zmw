You are optimizing a system prompt for a small local LLM (1-3B params) used as a home assistant. The LLM receives a system message with a preamble + available services, and should respond with a JSON command or DONT_KNOW.

The preamble is `_LLM_PREAMBLE` in `zmw_assistant.py` (this directory).

## Workflow

1. Run: `bash run_benchmark.sh`
2. Analyze PASS/FAIL results
3. Suggest a change to `_LLM_PREAMBLE` (show me the diff)
4. Wait for my approval before applying
5. After I approve, apply the change and go back to step 1

## Constraints

- The model is very small — shorter/simpler preambles work better
- Few-shot examples are critical but more than 3 hurts performance
- The model tends to echo context back instead of reasoning over it
- Keep the expected JSON format: `{"service": "...", "command": "...", "args": {...}}`
- The few-shot examples should cover different patterns: action commands, query commands, and unknown requests

## Scope

This session focuses **only on the preamble** (`_LLM_PREAMBLE`). Do not modify context formatting in `z2m_tracker.py` or `services_tracker.py`.

Once the preamble is stable, a separate session will optimize context formatting (service descriptions, Z2M device format, parameter verbosity, etc.).
