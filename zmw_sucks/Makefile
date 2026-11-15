include ../common.mk

ROOMBAPY_REPO = https://github.com/pschmitt/roombapy.git
ROOMBAPY_DIR = ../zext_libs/roombapy

rebuild_deps: pipenv_rebuild_deps_base
	pipenv install -e "$(shell readlink -f "$(PWD)/$(ROOMBAPY_DIR)")"

# Vendor a copy (not a submodule) of whatever is on roombapy's default branch right now
.PHONY: roombapy_dep_update
roombapy_dep_update:
	rm -rf "$(ROOMBAPY_DIR).tmp"
	git clone --depth 1 "$(ROOMBAPY_REPO)" "$(ROOMBAPY_DIR).tmp"
	git -C "$(ROOMBAPY_DIR).tmp" log -1 --format='$(ROOMBAPY_REPO) %H %cI' > "$(ROOMBAPY_DIR).tmp/VENDORED_FROM"
	rm -rf "$(ROOMBAPY_DIR).tmp/.git"
	rm -rf "$(ROOMBAPY_DIR)"
	mv "$(ROOMBAPY_DIR).tmp" "$(ROOMBAPY_DIR)"
	cat "$(ROOMBAPY_DIR)/VENDORED_FROM"

# One-off, for robots that won't give their password locally. Usage: make get_cloud_password EMAIL=you@example.com
get_cloud_password:
	pipenv run python3 ./get_cloud_password.py "$(EMAIL)"

test_listen_all:
	mosquitto_sub -v -h 127.0.0.1 -t 'zmw_sucks/#'

test_get_state:
	mosquitto_pub -t 'zmw_sucks/get_state' -m '{}'

ALIAS ?= Roomba
test_start:
	mosquitto_pub -t 'zmw_sucks/start' -m '{"alias": "$(ALIAS)"}'

test_pause:
	mosquitto_pub -t 'zmw_sucks/pause' -m '{"alias": "$(ALIAS)"}'

test_dock:
	mosquitto_pub -t 'zmw_sucks/dock' -m '{"alias": "$(ALIAS)"}'

test_find:
	mosquitto_pub -t 'zmw_sucks/find' -m '{"alias": "$(ALIAS)"}'

SETTING ?= bin_pause
VALUE ?= true
test_set_setting:
	mosquitto_pub -t 'zmw_sucks/set_setting' -m '{"alias": "$(ALIAS)", "setting": "$(SETTING)", "value": "$(VALUE)"}'

test_get_raw_state:
	mosquitto_pub -t 'zmw_sucks/get_raw_state' -m '{"alias": "$(ALIAS)"}'

test_get_mqtt_description:
	mosquitto_pub -t 'zmw_sucks/get_mqtt_description' -m '{}'
