"""One TLS context for the server's short-lived outbound HTTP clients.

Building an httpx client builds a TLS context and loads the CA bundle
(several milliseconds, synchronously, on the event loop that runs MQTT ingest
and the rules), even for a plain-http URL. The notifier and the weather and
Aranet clients make a client per request, so they share this one context
instead: `httpx.AsyncClient(verify=tls_context())`. Built once, on first use,
the way httpx builds its default (SSL_CERT_FILE / SSL_CERT_DIR honoured).

A leaf module: httpx only.
"""

import functools
import ssl

import httpx


@functools.cache
def tls_context() -> ssl.SSLContext:
    return httpx.create_ssl_context()
