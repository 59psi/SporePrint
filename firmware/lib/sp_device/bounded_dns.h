#pragma once
//
// bounded_dns — host-name lookups with a HARD time bound, and the network
// clients that use them.
//
// The loop-WDT budget of one connect attempt (sp_core/link_budget.h) counts
// DNS at kDnsWorstCaseS = 15 s. arduino-esp32 2.x enforced that: hostByName()
// waited for lwIP's answer at most 15 s. On 3.x, Network.hostByName() is
// lwip_getaddrinfo(), which blocks until lwIP itself gives up — 7 s of
// retries (1 + 1 + 2 + 3 s) per configured DNS server, up to three servers
// (CONFIG_LWIP_DNS_MAX_SERVERS), so 21 s — and a connect attempt that also
// waits out its TCP / TLS / CONNACK timeouts would overrun the 30 s panic WDT.
//
// resolve_host() restores the 2.x bound: it asks lwIP for the name with a
// callback and waits at most `timeout_ms` (an IP literal returns at once).
// BoundedDnsClient / BoundedDnsSecureClient resolve through it and then
// connect to the address — the TLS client still hands the HOST NAME to the
// handshake, so SNI and certificate verification are exactly what
// NetworkClientSecure::connect(host, port) does. PubSubClient
// (connect(host, port)) and HTTPClient (connect(host, port, timeout)) reach
// these through the virtual Client / NetworkClient overloads.
//
// Single-caller: resolve_host() keeps one lookup in flight and is called from
// the loop task (and setup()) only.

#include <Arduino.h>
#include <NetworkClientSecure.h>
#include <WiFiClient.h>

namespace sp_device {

// Resolve `host` (IPv4) into *out within `timeout_ms`. False on lookup
// failure or timeout — the abandoned lookup's late answer is discarded.
bool resolve_host(const char* host, uint32_t timeout_ms, IPAddress* out);

// The cap every lookup below uses (link_budget.h kDnsWorstCaseS).
uint32_t dns_timeout_ms();

class BoundedDnsClient : public NetworkClient {
public:
    using NetworkClient::connect;
    int connect(const char* host, uint16_t port) override {
        return connect(host, port, _timeout);
    }
    int connect(const char* host, uint16_t port, int32_t timeout_ms) override {
        IPAddress ip;
        if (!resolve_host(host, dns_timeout_ms(), &ip)) return 0;
        return NetworkClient::connect(ip, port, timeout_ms);
    }
};

class BoundedDnsSecureClient : public NetworkClientSecure {
public:
    using NetworkClientSecure::connect;
    int connect(const char* host, uint16_t port) override {
        if (_pskIdent != nullptr && _psKey != nullptr)
            return NetworkClientSecure::connect(host, port);  // PSK: unused
        IPAddress ip;
        if (!resolve_host(host, dns_timeout_ms(), &ip)) return 0;
        return NetworkClientSecure::connect(ip, port, host, _CA_cert, _cert,
                                            _private_key);
    }
    int connect(const char* host, uint16_t port, int32_t timeout_ms) override {
        _timeout = timeout_ms;
        return connect(host, port);
    }
};

}  // namespace sp_device
