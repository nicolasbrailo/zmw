include ../common.mk

rebuild_deps: pipenv_rebuild_deps_base
	pipenv install requests
	pipenv install flask

test_send:
	mosquitto_pub -t 'zmw_whatsapp/send_photo' -m '{"path": "/home/batman/nvrish/cam_snaps/doorbell/snap_20261122_110315.jpg", "msg": "HOLA"}'

sub_svc_bcast:
	mosquitto_sub -h localhost -p 1883 -t 'svc_announce_bcast/#' -v

