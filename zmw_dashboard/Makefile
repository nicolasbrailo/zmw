include ../common.mk

devrun::
	/usr/bin/authbind --deep pipenv run python3 ./zmw_dashboard.py

install_svc::
	../scripts/install_svc.sh . "/usr/bin/authbind --deep "

rebuild_ui::
	echo "SPEC TGT"
	$(MAKE) -C ../zzmw_lib/www js
	cat \
		../zmw_doorman/www/app.js \
		../zmw_heating/www/app.js \
		../zmw_lights/www/app.js \
		../zmw_sensormon/www/app.js \
		../zmw_sonos_ctrl/www/app.js \
		../zmw_speaker_announce/www/app.js \
		./www/app.js \
		> ./www/app.cat.js
	../zzmw_lib/www/babel_compile_single.sh ./www/app.cat.js ./www/app.rel.js
	@# Bundle and cache bust
	$(MAKE) _rebuild_ui_finalize

rebuild_deps: pipenv_rebuild_deps_base
	pipenv install requests
	pipenv install aiohttp
	pipenv install "flask[async]"

