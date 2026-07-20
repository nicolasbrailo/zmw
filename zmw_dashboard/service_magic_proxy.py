""" Forward requests from a Flask http server to arbitrary downstream http services """
import aiohttp
import asyncio
import json
import os
import signal
import ssl
import time

from flask import request, Response
from zzmw_lib.logs import build_logger

log = build_logger("ServiceMagicProxy")

# Upstream services may legitimately take a while: eg ZmwSpeakerAnnounce blocks for up to 10s
# waiting on a ZmwTextToSpeech MQTT reply. Keep this above the slowest downstream budget, or
# every TTS cache miss looks like a proxy failure.
_UPSTREAM_TIMEOUT_SECS = 15


def _proxy_error(status, error, detail):
    """Build a JSON error response. The UI speaks JSON, so never let Flask's HTML error page
    reach it: mAjax would just dump a wall of markup into the global error banner."""
    body = json.dumps({'error': error, 'detail': detail, 'status': status})
    return Response(body, status=status, mimetype='application/json')

class ServiceMagicProxy:
    """ Proxy forwarder: will forward request from a local flask server to another http server based on
    service prefix """

    def __init__(self, service_map, www):
        self._service_map = service_map
        self._register_routes(www)

    def get_proxied_services(self):
        """Return the map of service names to their proxy URLs."""
        return self._service_map

    def on_service_announced_meta(self, svc_name, www_url):
        """Handle service announcement and restart if the www URL changed."""
        if www_url is None:
            # Service has no www, nothing to proxy so we can ignore
            return
        if svc_name not in self._service_map:
            # We don't care about this service, but let the user know that a new service is up, and we won't proxy it.
            # We could restart here to start proxying, but we'd get a lot of unnecessary restarts if a service is
            # discovered, becomes unstable, and its url changes (eg due to new port assignment)
            log.warning("New service '%s' discovered, but proxy already started. Ignoring service.", svc_name)
            return
        if self._service_map[svc_name] != www_url:
            log.error("Service '%s' changed its www path from '%s' to '%s', proxying will break. ",
                      svc_name, self._service_map[svc_name], www_url)
            log.info("This service will restart in a few seconds to trigger service-rediscovery...")
            time.sleep(3)
            os.kill(os.getpid(), signal.SIGTERM)
            time.sleep(1)
            log.critical("Sent SIGTERM, if you're seeing this something is broken...")

    def _register_routes(self, www):
        for svc_prefix, svc_route in self._service_map.items():
            log.info("Discovered route to service %s", svc_prefix)

            # Register catch-all route for this service
            route = f'/{svc_prefix}/<path:subpath>'

            # Create wrapper that properly handles async
            # We need a closure to capture the svc_prefix value
            def make_handler(prefix):
                # Use www.serve_url style registration which handles async
                async def handler(subpath):
                    return await self._forward_to_service(prefix, subpath)
                # Set the function name for Flask
                handler.__name__ = f'proxy_{prefix}'
                return handler

            handler_func = make_handler(svc_prefix)

            # Register using Flask's route decorator syntax which handles async properly
            www.route(
                route,
                methods=['GET', 'POST', 'PUT', 'DELETE', 'PATCH', 'HEAD', 'OPTIONS'],
                endpoint=f'proxy_{svc_prefix}'
            )(handler_func)
            log.info("Registered proxy route: %s -> %s", route, svc_route)

    async def _forward_to_service(self, svc_prefix, subpath):
        """Generic proxy handler that forwards requests to upstream services."""
        if svc_prefix not in self._service_map:
            log.error("Unknown service prefix: %s", svc_prefix)
            return _proxy_error(404, "Unknown service",
                                f"No service registered under '{svc_prefix}'")

        upstream_url = self._service_map[svc_prefix]
        target_url = f"{upstream_url}/{subpath}"

        # Preserve query string
        if request.query_string:
            target_url += f"?{request.query_string.decode('utf-8')}"

        log.debug("Proxying %s %s -> %s", request.method, request.path, target_url)

        req_start = time.monotonic()
        try:
            # Create SSL context that accepts self-signed certificates
            ssl_context = ssl.create_default_context()
            ssl_context.check_hostname = False
            ssl_context.verify_mode = ssl.CERT_NONE

            connector = aiohttp.TCPConnector(ssl=ssl_context)
            async with aiohttp.ClientSession(connector=connector) as session:
                # Prepare request kwargs
                kwargs = {
                    'timeout': aiohttp.ClientTimeout(total=_UPSTREAM_TIMEOUT_SECS),
                    'allow_redirects': False,
                }

                # Forward request headers (excluding hop-by-hop headers)
                headers = {}
                hop_by_hop = {'connection', 'keep-alive', 'proxy-authenticate',
                             'proxy-authorization', 'te', 'trailers', 'transfer-encoding', 'upgrade'}
                for key, value in request.headers:
                    if key.lower() not in hop_by_hop:
                        headers[key] = value
                kwargs['headers'] = headers

                # Forward request body for methods that support it
                if request.method in ['POST', 'PUT', 'PATCH']:
                    data = request.get_data()
                    if data:
                        kwargs['data'] = data

                # Make the request
                async with session.request(request.method, target_url, **kwargs) as resp:
                    # Read response body
                    body = await resp.read()

                    # Forward response headers (excluding hop-by-hop headers)
                    response_headers = {}
                    for key, value in resp.headers.items():
                        if key.lower() not in hop_by_hop:
                            response_headers[key] = value

                    # Create Flask response with upstream status code and headers
                    return Response(
                        body,
                        status=resp.status,
                        headers=response_headers
                    )

        # Must come before ClientError: a total-timeout raises bare asyncio.TimeoutError (not part
        # of aiohttp's hierarchy at all), while ServerTimeoutError subclasses both. Either way it's
        # a slow upstream, not a proxy bug, so don't log a traceback for it.
        except asyncio.TimeoutError:
            elapsed = time.monotonic() - req_start
            log.warning("Timed out after %.1fs proxying to %s", elapsed, target_url)
            return _proxy_error(
                504, f"'{svc_prefix}' took too long to respond",
                f"No response after {elapsed:.1f}s (limit {_UPSTREAM_TIMEOUT_SECS}s). "
                "The service may still be working on the request.")
        except aiohttp.ClientError as e:
            log.error("Error proxying to %s: %s", target_url, str(e))
            return _proxy_error(502, f"Can't reach '{svc_prefix}'",
                                f"{type(e).__name__}: {str(e)}")
        except Exception as e:  # pylint: disable=broad-exception-caught
            log.error("Unexpected error proxying to %s: %s", target_url, str(e), exc_info=True)
            # str() on many exceptions is empty, so always include the type
            return _proxy_error(500, "Internal proxy error",
                                f"{type(e).__name__}: {str(e)}")
