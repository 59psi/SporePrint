#include "bounded_dns.h"

#include <freertos/FreeRTOS.h>
#include <freertos/semphr.h>
#include <lwip/dns.h>
#include <lwip/ip_addr.h>
#include <sdkconfig.h>
#ifdef CONFIG_LWIP_TCPIP_CORE_LOCKING
#include <lwip/priv/tcpip_priv.h>
#endif

#include "link_budget.h"

namespace sp_device {

namespace {

// One lookup in flight. lwIP calls on_found() from the TCP/IP task; a
// generation number ties each answer to the lookup that asked, so an answer
// that arrives after resolve_host() gave up is dropped.
portMUX_TYPE g_mux = portMUX_INITIALIZER_UNLOCKED;
SemaphoreHandle_t g_done = nullptr;
uint32_t g_gen = 0;
bool g_found = false;
ip_addr_t g_addr;

void on_found(const char* /*name*/, const ip_addr_t* ipaddr, void* arg) {
    const uint32_t gen = (uint32_t)(uintptr_t)arg;
    bool current = false;
    portENTER_CRITICAL(&g_mux);
    if (gen == g_gen) {
        current = true;
        g_found = (ipaddr != nullptr);
        if (ipaddr != nullptr) g_addr = *ipaddr;
    }
    portEXIT_CRITICAL(&g_mux);
    if (current) xSemaphoreGive(g_done);
}

// lwIP's raw API must run under the TCP/IP core lock (IDF 5 checks it), the
// same guard the core's configTime() takes.
class TcpipCoreLock {
public:
    TcpipCoreLock() {
#ifdef CONFIG_LWIP_TCPIP_CORE_LOCKING
        if (!sys_thread_tcpip(LWIP_CORE_LOCK_QUERY_HOLDER)) {
            LOCK_TCPIP_CORE();
            locked_ = true;
        }
#endif
    }
    ~TcpipCoreLock() {
#ifdef CONFIG_LWIP_TCPIP_CORE_LOCKING
        if (locked_) UNLOCK_TCPIP_CORE();
#endif
    }

private:
    bool locked_ = false;
};

IPAddress to_ip(const ip_addr_t& a) { return IPAddress(ip_2_ip4(&a)->addr); }

}  // namespace

uint32_t dns_timeout_ms() { return sp::kDnsWorstCaseS * 1000UL; }

bool resolve_host(const char* host, uint32_t timeout_ms, IPAddress* out) {
    if (host == nullptr || host[0] == '\0' || out == nullptr) return false;
    IPAddress literal;
    if (literal.fromString(host)) {  // no lookup, as hostByName() does
        *out = literal;
        return true;
    }
    if (g_done == nullptr) g_done = xSemaphoreCreateBinary();
    if (g_done == nullptr) return false;
    xSemaphoreTake(g_done, 0);  // drop a late answer to an abandoned lookup

    uint32_t gen;
    portENTER_CRITICAL(&g_mux);
    gen = ++g_gen;
    g_found = false;
    portEXIT_CRITICAL(&g_mux);

    ip_addr_t addr{};
    err_t err;
    {
        TcpipCoreLock lock;
#if LWIP_IPV4 && LWIP_IPV6
        err = dns_gethostbyname_addrtype(host, &addr, on_found,
                                         (void*)(uintptr_t)gen,
                                         LWIP_DNS_ADDRTYPE_IPV4);
#else
        err = dns_gethostbyname(host, &addr, on_found, (void*)(uintptr_t)gen);
#endif
    }
    if (err == ERR_OK) {  // lwIP's table already had it
        *out = to_ip(addr);
        return true;
    }
    if (err != ERR_INPROGRESS) return false;

    const bool answered =
        xSemaphoreTake(g_done, pdMS_TO_TICKS(timeout_ms)) == pdTRUE;
    bool found = false;
    ip_addr_t got{};
    portENTER_CRITICAL(&g_mux);
    if (answered && g_found) {
        found = true;
        got = g_addr;
    }
    ++g_gen;  // whatever lwIP answers later for this lookup is stale
    portEXIT_CRITICAL(&g_mux);
    if (found) *out = to_ip(got);
    return found;
}

}  // namespace sp_device
