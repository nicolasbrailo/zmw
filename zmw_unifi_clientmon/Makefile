include ../common.mk

rebuild_deps: pipenv_rebuild_deps_base
	pipenv install requests
	pipenv install flask

test_ls:
	mosquitto_pub -t 'zmw_unifi_clientmon/ls' -m '{}'

test_history:
	mosquitto_pub -t 'zmw_unifi_clientmon/get_history' -m '{}'

sub_svc:
	mosquitto_sub -h localhost -p 1883 -t 'zmw_unifi_clientmon/#' -v
