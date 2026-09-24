# zzmw_lib is not a service, so this doesn't include ../common.mk: the top-level Makefile runs install_svc,
# rebuild_ui and lint on every dir with a Makefile, and the service versions of those targets don't apply here.

.PHONY: test
test:
	pipenv run pytest tests/* -v --cov=zzmw_lib --cov-report=term-missing --cov-report=html

.PHONY: rebuild_deps
rebuild_deps:
	rm -f Pipfile Pipfile.lock
	pipenv --rm || true
	pipenv --python python3
	pipenv install -e ".[geo,z2m]"
	pipenv install --dev pylint
	pipenv install --dev pytest
	pipenv install --dev pytest-cov

.PHONY: lint
lint:
	echo '' > lint
	pipenv run pylint --max-line-length=120 --disable=C0411 zzmw_lib >> lint | true
	cat lint

.PHONY: devrun install_svc rebuild_ui
devrun install_svc rebuild_ui:
	@echo "zzmw_lib is a library, not a service: skipping $@"
