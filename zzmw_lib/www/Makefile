build:
	mkdir -p build/npm
	mkdir -p build/extjs

.PHONY: js css
js: build/zmw.js
	cp build/zmw.js ./zmw.js
css: build/zmw.css
	cp build/zmw.css ./zmw.css

build/zmw.js: build build/extjs/react.dom.js build/extjs/react.js js/*
	@# Order is important (eg we need to define react before zmw)
	cat build/extjs/react.js \
			build/extjs/react.dom.js \
			js/localStorageManager.js \
			js/DebouncedRange.js \
			js/z2m.js \
		> build/zmw.big.js
	./babel_compile_single.sh build/zmw.big.js build/zmw.js

build/zmw.css: ./css/* build
	./build/npm/node_modules/.bin/uglifycss ./css/* > build/zmw.css

build/extjs/react.js:
	wget -O "$@.unsafe" https://unpkg.com/react@18.3.1/umd/react.production.min.js
	sha384sum $@.unsafe
	echo "0c6c8bc40ca3ab47fd48fa557af0fa220ced085967305ea85bf5d01a67def88b19f13a84883adc1e430b288e9f881fd9 $@.unsafe" | sha384sum --check --strict
	# If checksum fails, this won't run
	cp $@.unsafe $@
	rm $@.unsafe

build/extjs/react.dom.js:
	wget -O "$@.unsafe" https://unpkg.com/react-dom@18.3.1/umd/react-dom.production.min.js
	sha384sum $@.unsafe
	echo "8131b1873db595519834c71d24ecaad3511d8348e19ff736da7b31d24caa3f44f1695e5655db121f57d20d47f96098f5 $@.unsafe" | sha384sum --check --strict
	# If checksum fails, this won't run
	cp $@.unsafe $@
	rm $@.unsafe

build/extjs/dygraph.js:
	wget -O "$@.unsafe" https://cdnjs.cloudflare.com/ajax/libs/dygraph/2.1.0/dygraph.min.js
	sha384sum $@.unsafe
	echo "4a2c3ad87927d12d230531399c76e394fbe0daca08a8a80e9e9e2a516e3d3f3e6c3a310eb9ee5de8dcc2c9dc93b1dda7 $@.unsafe" | sha384sum --check --strict
	# If checksum fails, this won't run
	cp $@.unsafe $@
	rm $@.unsafe

rebuild-deps: build
	sudo npm install uglifycss -g
	npm install --save-dev --prefix ./build/npm  @babel/core @babel/cli @babel/preset-env @babel/preset-react babel-preset-minify uglifycss

