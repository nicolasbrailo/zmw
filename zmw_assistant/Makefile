include ../common.mk

playground_deps: pipenv_rebuild_deps_base
	pipenv install llama-cpp-python --verbose
playground:
	pipenv run python3 playground.py 2>&1 | tee playground.log
render_results:
	python3 render_results.py
update_svcs.json:
	curl http://10.0.0.10:4219/get_service_interfaces | jq > svcs.json

rebuild_deps: pipenv_rebuild_deps_base
	pipenv install llama-cpp-python --verbose
	pipenv install -e "$(shell readlink -f "$(PWD)/../zz2m")"

.PHONY: download_all_models
download_all_models: \
	models/7B/tinyllama-1.1b-chat-v1.0.Q4_K_M.gguf \
	models/7B/Meta-Llama-3.1-8B-Instruct-Q4_K_M.gguf \
	models/7B/Llama-3.2-1B-Instruct-Q4_K_M.gguf \
	models/7B/Llama-3.2-3B-Instruct-Q4_K_M.gguf \
	models/7B/qwen2.5-1.5b-instruct-q4_k_m.gguf \
	models/7B/smollm2-1.7b-instruct-q4_k_m.gguf \
	models/7B/gemma-3-1b-it-Q4_K_M.gguf

models/7B/tinyllama-1.1b-chat-v1.0.Q4_K_M.gguf:
	mkdir -p models/7B
	wget -O models/7B/tinyllama-1.1b-chat-v1.0.Q4_K_M.gguf https://huggingface.co/TheBloke/TinyLlama-1.1B-Chat-v1.0-GGUF/resolve/main/tinyllama-1.1b-chat-v1.0.Q4_K_M.gguf

models/7B/Meta-Llama-3.1-8B-Instruct-Q4_K_M.gguf:
	mkdir -p models/7B
	wget -O models/7B/Meta-Llama-3.1-8B-Instruct-Q4_K_M.gguf https://huggingface.co/bartowski/Meta-Llama-3.1-8B-Instruct-GGUF/resolve/main/Meta-Llama-3.1-8B-Instruct-Q4_K_M.gguf

models/7B/Llama-3.2-1B-Instruct-Q4_K_M.gguf:
	mkdir -p models/7B
	wget -O models/7B/Llama-3.2-1B-Instruct-Q4_K_M.gguf https://huggingface.co/bartowski/Llama-3.2-1B-Instruct-GGUF/resolve/main/Llama-3.2-1B-Instruct-Q4_K_M.gguf

models/7B/Llama-3.2-3B-Instruct-Q4_K_M.gguf:
	mkdir -p models/7B
	wget -O models/7B/Llama-3.2-3B-Instruct-Q4_K_M.gguf https://huggingface.co/bartowski/Llama-3.2-3B-Instruct-GGUF/resolve/main/Llama-3.2-3B-Instruct-Q4_K_M.gguf

models/7B/qwen2.5-1.5b-instruct-q4_k_m.gguf:
	mkdir -p models/7B
	wget -O models/7B/qwen2.5-1.5b-instruct-q4_k_m.gguf https://huggingface.co/Qwen/Qwen2.5-1.5B-Instruct-GGUF/resolve/main/qwen2.5-1.5b-instruct-q4_k_m.gguf

models/7B/smollm2-1.7b-instruct-q4_k_m.gguf:
	mkdir -p models/7B
	wget -O models/7B/smollm2-1.7b-instruct-q4_k_m.gguf https://huggingface.co/HuggingFaceTB/SmolLM2-1.7B-Instruct-GGUF/resolve/main/smollm2-1.7b-instruct-q4_k_m.gguf

models/7B/gemma-3-1b-it-Q4_K_M.gguf:
	mkdir -p models/7B
	wget -O models/7B/gemma-3-1b-it-Q4_K_M.gguf https://huggingface.co/ggml-org/gemma-3-1b-it-GGUF/resolve/main/gemma-3-1b-it-Q4_K_M.gguf

