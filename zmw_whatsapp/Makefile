include ../common.mk

rebuild_deps: pipenv_rebuild_deps_base
	pipenv install requests
	pipenv install flask

test_send:
	mosquitto_pub -t 'zmw_whatsapp/send_photo' -m '{"path": "/home/batman/nvrish/cam_snaps/doorbell/doorbell_snap.jpg", "msg": "HOLA"}'

sub_svc_bcast:
	mosquitto_sub -h localhost -p 1883 -t 'svc_announce_bcast/#' -v

