# ZmwServicemon

Monitors all other running z2m services, tracks their status (up/down), and monitors systemd journal for errors. Provides a dashboard view of system health.

![](README_screenshot.png)

This service will let you know the health of your ZMW services at a glance. It will

* Display the list of running services (or when a service was last seen, if it's not running).
* Let you read detailed logs of each service.
* Provide a quick link to each service.
* Display the systemd status of a service (a systemd service may be running, but not registered as a ZMW service. A ZMW service may also be running, but not registered to systemd).
* Display a list of errors: ZmwServicemon will tail the journal for each ZMW service, and will capture errors and warnings. These will be displayed in ZmwServicemon www.
* Optional Telegram integration: integrates with ZmwTelegram to send you a message when the system encounters an error. Errors from services listed in `telegram_ignore_services` (config) are still captured and displayed, but never sent to Telegram; useful for noisy services.

