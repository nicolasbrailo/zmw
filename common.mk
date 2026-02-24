# Common Makefile targets for all subdirectory projects
# Include this file in subdirectory Makefiles with: include ../common.mk

.PHONY: devrun
devrun::
	# Run the service corresponding to the active directory
	pipenv run python3 ./$(notdir $(CURDIR)).py

.PHONY: test
test::
	@if find tests -name '*.py' 2>/dev/null | grep -q .; then \
		pipenv run pytest tests/* -v --cov=. --cov-report=term-missing --cov-report=html; \
	else \
		echo "No tests found, skipping"; \
	fi

.PHONY: rebuild_ui
rebuild_ui::
	@# Ensure common framework is up to date
	echo "COMMON TGT"
	$(MAKE) -C ../zzmw_lib/www js
	@# Build app js for this service
	../zzmw_lib/www/babel_compile_single.sh ./www/app.js ./www/app.rel.js
	@# Bundle and cache bust
	$(MAKE) _rebuild_ui_finalize

# Finalize UI build: bundle zmw.js, hash filename, update HTML
# Expects ./www/app.rel.js to already exist
.PHONY: _rebuild_ui_finalize
_rebuild_ui_finalize:
	@# Bundle everything in one big js file
	@echo "Deleting old cache-busted files:" ./www/app.rel.*.js 2>/dev/null || echo "(none)"
	rm -f ./www/app.rel.*.js
	cat ../zzmw_lib/www/zmw.js ./www/app.rel.js > ./www/app.rel.combined.js
	mv ./www/app.rel.combined.js ./www/app.rel.js
	@# Cache busting: add a hash to the filename, to force refetch by browsers
	@# Update html targets with cache busted version (all in one line to keep var in scope)
	HASH=$$(md5sum ./www/app.rel.js | cut -d' ' -f1 | head -c8) && \
		cp ./www/app.rel.js "./www/app.rel.$$HASH.js" && \
		for f in ./www/*.html; do \
			echo "Updating $$f hash to $$HASH"; \
			sed -i "s|app\.rel[^\"]*\.js|app.rel.$$HASH.js|g" "$$f"; \
		done

.PHONY: install_svc
install_svc::
	../scripts/install_svc.sh .

.PHONY: pipenv_rebuild_deps_base pipenv_rebuild_deps_base_geo
pipenv_rebuild_deps_base: ZZMW_LIB_EXTRAS =
pipenv_rebuild_deps_base_geo: ZZMW_LIB_EXTRAS = [geo]
pipenv_rebuild_deps_base pipenv_rebuild_deps_base_geo:
	rm -f Pipfile Pipfile.lock
	pipenv --rm || true
	pipenv --python python3
	pipenv install -e "$(shell readlink -f "$(PWD)/../zzmw_lib")$(ZZMW_LIB_EXTRAS)"
	pipenv install --dev pylint
	pipenv install --dev pytest
	pipenv install --dev pytest-cov

.PHONY: lint
lint: *.py
	echo '' > lint
	pipenv run pylint --max-line-length=120 --disable=C0411 *.py >> lint | true
	cat lint
