# Auto-discover all subdirectories with Makefiles
DIRS_WITH_MKFILE := $(patsubst %/Makefile,%,$(wildcard */Makefile))
TEST_DIRS := $(patsubst %/tests,%,$(wildcard */tests))

.PHONY: systemdeps
systemdeps:
	sudo apt-get install -y python3-pkgconfig libsystemd-dev pylint autopep8

.PHONY: test
test:
	@echo "Running test on all projects..."
	@for dir in $(TEST_DIRS); do \
		make -C $$dir test || true; \
	done

.PHONY: install_all_services
install_all_services:
	@echo "This will reset and restart all services, if you're sure you want this uncomment this target in the Makefile"
	@for dir in $(DIRS_WITH_MKFILE); do \
		make -C $$dir install_svc ; \
	done

# Rebuild every service's Pipfile/venv, in parallel (one job per CPU). --keep-going lets
# the rest finish if one fails; make lists the failures at the end. -O keeps each
# service's output together. Uses cd instead of make -C: common.mk relies on $(PWD).
.PHONY: rebuild_all_deps
rebuild_all_deps:
	@$(MAKE) --no-print-directory -j$(shell nproc) -O --keep-going $(addprefix _rebuild_deps-,$(DIRS_WITH_MKFILE))

_rebuild_deps-%:
	cd $* && $(MAKE) --no-print-directory rebuild_deps

.PHONY: rebuild_all_ui
rebuild_all_ui:
	@echo "Running rebuild_ui on all projects..."
	@for dir in $(DIRS_WITH_MKFILE); do \
		make -C $$dir rebuild_ui || true; \
	done

.PHONY: lint
lint:
	@echo "Running lint on all projects..."
	@for dir in $(DIRS_WITH_MKFILE); do \
		make -C $$dir lint || true; \
	done
	@for dir in $(DIRS_WITH_MKFILE); do \
		if [ -f $$dir/lint ]; then \
			score=$$(grep "rated at" $$dir/lint | tail -1); \
			if [ -n "$$score" ]; then \
				printf "%-30s %s\n" "$$dir:" "$$score"; \
			fi; \
		fi; \
	done

.PHONY: cat-lints
cat-lints:
	@for dir in $(DIRS_WITH_MKFILE); do \
		if [ -f $$dir/lint ]; then \
			echo "==================== $$dir ===================="; \
			cat $$dir/lint; \
		fi; \
	done

