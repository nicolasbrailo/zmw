""" One-off: get the local MQTT password of all robots in an iRobot account, from the iRobot cloud.

Only needed for robots that won't give their password locally (HOME button + roombapy.RoombaPassword). Once
the password is known, the service doesn't need the cloud. Same flow as dorita980/Roomba980-Python: iRobot
endpoint discovery -> Gigya account login -> iRobot login, which returns each robot's BLID and password.

Usage: get_cloud_password.py <email> (asks for the iRobot account password)
"""
import getpass
import json
import sys
import urllib.parse
import urllib.request

_DISCOVERY_URL = "https://disc-prod.iot.irobotapi.com/v1/discover/endpoints?country_code=US"
_APP_ID = "ANDROID-C7FB240E-DF34-42D7-AE4E-A8C17079A294"


def _get_json(url, data=None, as_json=False):
    headers = {}
    if data is not None:
        if as_json:
            data = json.dumps(data).encode()
            headers["Content-Type"] = "application/json"
        else:
            data = urllib.parse.urlencode(data).encode()
    req = urllib.request.Request(url, data=data, headers=headers)
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read())


def get_cloud_passwords(email, password):
    """ Returns {blid: {name, sku, password}} for all robots in the account """
    endpoints = _get_json(_DISCOVERY_URL)
    http_base = endpoints["deployments"][endpoints["current_deployment"]]["httpBase"]
    gigya = endpoints["gigya"]

    gigya_login = _get_json(f"https://accounts.{gigya['datacenter_domain']}/accounts.login", {
        "apiKey": gigya["api_key"],
        "targetenv": "mobile",
        "loginID": email,
        "password": password,
        "format": "json",
        "targetEnv": "mobile",
    })
    if gigya_login.get("errorCode", 0) != 0:
        raise RuntimeError(f"iRobot account login failed: {gigya_login.get('errorMessage')}")

    irobot_login = _get_json(f"{http_base}/v2/login", {
        "app_id": _APP_ID,
        "assume_robot_ownership": "0",
        "gigya": {
            "signature": gigya_login["UIDSignature"],
            "timestamp": gigya_login["signatureTimestamp"],
            "uid": gigya_login["UID"],
        },
    }, as_json=True)
    return irobot_login.get("robots", {})


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(__doc__)
        sys.exit(1)
    robots = get_cloud_passwords(sys.argv[1], getpass.getpass("iRobot account password: "))
    if not robots:
        print("No robots in this account")
    for blid, info in robots.items():
        print(f"{info.get('name')} ({info.get('sku')}): blid={blid} password={info.get('password')}")
