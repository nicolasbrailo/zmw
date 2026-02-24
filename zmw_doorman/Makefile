include ../common.mk

rebuild_deps: pipenv_rebuild_deps_base_geo
	pipenv install -e "$(shell readlink -f "$(PWD)/../zz2m")"

tst_door_open:
	mosquitto_pub -h localhost -p 1883 -t "zmw_contactmon/ContactSensor_FrontDoor/contact" \
		-m '{"sensor": "ContactSensor_FrontDoor", "contact": false, "prev_contact": true, "entering_non_normal": true}'

tst_door_close:
	mosquitto_pub -h localhost -p 1883 -t "zmw_contactmon/ContactSensor_FrontDoor/contact" \
		-m '{"sensor": "ContactSensor_FrontDoor", "contact": true, "prev_contact": false, "entering_non_normal": false}'

