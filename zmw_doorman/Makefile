ZZMW_LIB_EXTRAS = [geo,z2m]
include ../common.mk

rebuild_deps: pipenv_rebuild_deps_base

tst_door_open:
	mosquitto_pub -h localhost -p 1883 -t "zmw_contactmon/ContactSensor_FrontDoor/contact" \
		-m '{"sensor": "ContactSensor_FrontDoor", "contact": false, "prev_contact": true, "entering_non_normal": true}'

tst_door_close:
	mosquitto_pub -h localhost -p 1883 -t "zmw_contactmon/ContactSensor_FrontDoor/contact" \
		-m '{"sensor": "ContactSensor_FrontDoor", "contact": true, "prev_contact": false, "entering_non_normal": false}'

