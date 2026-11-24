"""
Whatsapp wrapper, to upload files and send messages. Probably not compliant with the terms of service, and may
break at any time.

A lot of setup is required, and any of these steps may break at any time:

* Create a developer account at developers.facebook.com
* Create new business app at https://developers.facebook.com/apps/
* In the app dashboard, add Whatsapp integration
* In the Whatsapp integration there should be steps to get a temporary token and to test with curl. This includes
  enrolling the target phone numbers.
* Get the origin phone number from the dashboard, to be used as the source phone number for this app (or add your
  own number; this is probably safer)
* In the WhatsApp integration page, look for "Permanent token" (under configuration?)
    - https://developers.facebook.com/docs/whatsapp/business-management-api/get-started#1--acquire-an-access-token-using-a-system-user-or-facebook-login
    - https://stackoverflow.com/questions/72685327/how-to-get-permanent-token-for-using-whatsapp-cloud-api
  The permanent token is, basically, a password for your Facebook account
* Use the origin phone number and the permanent token to configure this object

Note you can't send arbitrary messages to a phone number, you will need to
1. Send a template message
2. Get the target number to interact via WhatsApp (this will let you send arbitrary messages only for a set period of
   time)
"""
import json
import requests
import logging

from zzmw_lib.logs import build_logger

log = build_logger("ZmwWA")

# Comment out to see requests to WA's API
logging.getLogger('urllib3.connectionpool').setLevel(logging.INFO)


class WhatsApp:
    """ WA integration, may be against WA ToS """

    def __init__(self, cfg, test_mode=True):
        self._test_mode = test_mode
        self._targets = cfg['notify_targets']
        self._timeout = cfg.get('wa_rq_timeout', 10)

        self._msg_url = f'https://graph.facebook.com/v15.0/{cfg["from_number"]}/messages'
        self._media_url = f'https://graph.facebook.com/v15.0/{cfg["from_number"]}/media'

        self._headers = {
            'Authorization': f'Bearer {cfg["tok"]}',
        }

        self._json_headers = {
            'Authorization': f'Bearer {cfg["tok"]}',
            'Content-Type': 'application/json',
        }

    def message_from_template(self, template_name):
        """ Send template to number. This works even if the target hasn't interacted first, but target must be
        enrolled in the test program || the origin should be a proper business account. """

        def _message_from_template(to_number, template_name):
            log.info('WA send template %s to %s', template_name, to_number)
            if self._test_mode:
                return None
            msg = {
                "to": to_number,
                "type": "template",
                "messaging_product": "whatsapp",
                "template": {
                    "name": template_name,
                    "language": {
                        "policy": "deterministic",
                        "code": "en_US"
                    },
                },
            }
            return requests.post(
                self._msg_url,
                headers=self._json_headers,
                data=json.dumps(msg),
                timeout=self._timeout)
        return [_message_from_template(num, template_name)
                for num in self._targets]

    def send_hello_world_msg(self):
        """ Use this to get a generic hello world message, to test the auth setup """
        return self.message_from_template("hello_world")

    def upload_image(self, fpath):
        """ Upload image to WA server, returns media ID to use when sending a message """
        log.info('WA uploaded image %s', fpath)
        if self._test_mode:
            return 'DUMMY_WA_IMAGE_ID'
        msg = {
            "messaging_product": "whatsapp",
            "type": "image/jpeg",
        }
        with open(fpath, 'rb') as fp:
            files = {'file': ('n.jpg', fp, 'image/jpeg', {'Expires': '0'})}
            req = requests.post(
                self._media_url,
                headers=self._headers,
                data=msg,
                files=files,
                timeout=self._timeout)
            jreq = json.loads(req.text)
        return jreq['id']

    def text(self, msg_text):
        """ Send text. This won't work unless the target has interacted with the origin number in the last N hours """

        def _text(to_number, msg_text):
            log.info('WA Text %s: %s', to_number, msg_text)
            if self._test_mode:
                return None
            msg = {
                "to": to_number,
                "messaging_product": "whatsapp",
                "recipient_type": "individual",
                "type": "text",
                "text": {
                    "preview_url": False,
                    "body": msg_text,
                }
            }
            return requests.post(
                self._msg_url,
                headers=self._json_headers,
                data=json.dumps(msg),
                timeout=self._timeout)

        return [_text(num, msg_text) for num in self._targets]

    def send_image(self, image_id):
        """ Send image to_number. Same restrictions as text() apply """

        def _send_image(to_number, image_id):
            log.info('WA send image to %s, id %s', to_number, image_id)
            if self._test_mode:
                return None
            msg = {
                "to": to_number,
                "messaging_product": "whatsapp",
                "recipient_type": "individual",
                "type": "image",
                "image": {
                    "id": image_id,
                    "caption": "your-image-caption"
                }
            }
            return requests.post(
                self._msg_url,
                headers=self._json_headers,
                data=json.dumps(msg),
                timeout=self._timeout)
        return [_send_image(num, image_id) for num in self._targets]

    def template_message_with_image(
            self,
            template_name,
            media_id,
            text_replace):
        """ Send a templated message, with one text and one media param. Same restrictions as
        message_from_template apply. The template name must be configured in the dashboard, eg
        https://business.facebook.com/wa/manage/message-templates/
        """

        def _message_from_params_template(to_number, media_id):
            log.info(
                'WA send template with media %s to %s',
                media_id,
                to_number)
            if self._test_mode:
                return None
            msg = {
                "to": to_number,
                "type": "template",
                "recipient_type": "individual",
                "messaging_product": "whatsapp",
                "template": {
                    "name": template_name,
                    "language": {
                        "policy": "deterministic",
                        "code": "en_us"
                    },
                    "components": [
                        {
                            "type": "header",
                            "parameters": [
                                {
                                    "type": "image",
                                    "image": {
                                        "id": media_id
                                    }
                                }
                            ]
                        },
                        {
                            "type": "body",
                            "parameters": [
                                {"type": "text", "text": text_replace},
                            ]
                        }
                    ],
                }
            }
            return requests.post(
                self._msg_url,
                headers=self._json_headers,
                data=json.dumps(msg),
                timeout=self._timeout)
        return [_message_from_params_template(
            num, media_id) for num in self._targets]

    def send_photo(
            self,
            img_path,
            caption,
            tmpl_name="sample_purchase_feedback"):
        """ A photo can't be sent on its own to a user that hasn't interacted with the WA bot,
        so instead we send a template message containing an image. Note the default template is
        a random message with some unrelated text. """
        imgid = None
        try:
            imgid = self.upload_image(img_path)
            log.info("Uploaded %s to WA", img_path)
        except (FileNotFoundError, PermissionError, IsADirectoryError):
            log.error("WA image upload failed, '%s' is not accessible", img_path, exc_info=True)
            return
        except (json.JSONDecodeError, KeyError):
            log.error("Failed WA image upload, bad WA reply", exc_info=True)
            return
        except (requests.ConnectionError, requests.Timeout):
            log.error("Failed WA image upload, network error (offline?)", exc_info=True)
            return
        except requests.HTTPError:
            log.error("Failed WA image upload, service returned error", exc_info=True)
            return
        except requests.RequestException:
            log.error("Failed WA image upload, request error", exc_info=True)
            return

        if imgid is not None:
            try:
                res = self.template_message_with_image(
                    tmpl_name, imgid, caption)
                log.info("Sent motion detect messages to WA: %s", str(res))
                # A 200 only means accepted: the body has each message's id and status (eg held for quality
                # assessment), the only trace of why a message isn't delivered
                for r in res or []:
                    if r is not None:
                        log.info("WA reply %s: %s", r.status_code, r.text[:500])
            except (json.JSONDecodeError, KeyError):
                log.error("Failed WA image send, bad template?", exc_info=True)
            except (requests.ConnectionError, requests.Timeout):
                log.error("Failed WA image send, network error (offline?)", exc_info=True)
            except requests.HTTPError:
                log.error("Failed WA image send, service returned error", exc_info=True)
            except requests.RequestException:
                log.error("Failed WA image send, request error", exc_info=True)
