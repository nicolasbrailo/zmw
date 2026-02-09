#!/bin/bash
ssh bati.casa "cd /home/batman/src/BatiCasa/zigbee2mqtt2web/zmw_assistant && PYTHONUNBUFFERED=1 pipenv run python3 zmw_assistant.py" 2>/dev/null
