include ../common.mk

rebuild_deps: pipenv_rebuild_deps_base
	pipenv install llama-cpp-python --verbose
	pipenv install -e "$(shell readlink -f "$(PWD)/../zz2m")"

models/7B/tinyllama-1.1b-chat-v1.0.Q4_K_M.gguf:
	mkdir -p models/7B
	wget -O models/7B/tinyllama-1.1b-chat-v1.0.Q4_K_M.gguf https://huggingface.co/TheBloke/TinyLlama-1.1B-Chat-v1.0-GGUF/resolve/main/tinyllama-1.1b-chat-v1.0.Q4_K_M.gguf

models/7B/Meta-Llama-3.1-8B-Instruct-Q4_K_M.gguf:
	mkdir -p models/7B
	wget -O models/7B/Meta-Llama-3.1-8B-Instruct-Q4_K_M.gguf https://huggingface.co/bartowski/Meta-Llama-3.1-8B-Instruct-GGUF/resolve/main/Meta-Llama-3.1-8B-Instruct-Q4_K_M.gguf


