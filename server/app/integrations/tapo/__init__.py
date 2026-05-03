"""TP-Link Tapo integration (dual transport — local + cloud).

Tapo is TP-Link's newer smart-plug line (post-2020). Two transports:

- **Local mode** (free): KLAP handshake + AES-128-CBC encrypted commands
  on TCP/80. Newer firmware (≥1.1.x on most models) exposes the
  `/app/handshake1` and `/app/handshake2` endpoints; older firmware
  uses the legacy "secure_passthrough" RSA path which is currently
  out of scope (use cloud transport instead).

- **Cloud mode** (premium): tplinkcloud.com OAuth flow with
  `passthrough` device commands. Works regardless of firmware version
  but routes through TP-Link's cloud — credentials live on the Pi
  (encrypted at rest). Premium per ``feedback_tier_model``.

⚠ **Live-device verification needed** for the local KLAP path. The
on-wire shape is documented but cipher-key-derivation specifics
benefit from real hardware; the parser is tolerant by design and the
driver records the response shape on first contact so refinements can
be additive.
"""

from .driver import TapoDriver

driver = TapoDriver()

from .. import _registry as _registry_module
_registry_module.register(driver)


__all__ = ["TapoDriver", "driver"]
