#include "wifi_provisioner.h"

#include <WebServer.h>
#include <WiFi.h>
#include <time.h>

namespace sp_device {

namespace {

constexpr uint32_t kPortalCeilingMs = 10UL * 60UL * 1000UL;

const char kFormHead[] =
    "<html><head><meta name='viewport' content='width=device-width,initial-scale=1'>"
    "<title>SporePrint Setup</title></head>"
    "<body style='font-family:sans-serif;max-width:420px;margin:40px auto;padding:0 12px;'>"
    "<h2>SporePrint Node Setup</h2>"
    "<form method='post' action='/save'>";

const char kFormTail[] =
    "<button type='submit' style='padding:10px 24px;margin-top:14px;'>"
    "Save &amp; Connect</button></form></body></html>";

String text_field(const char* label, const char* name, const String& value,
                  const char* type = "text", const char* hint = "") {
    String f;
    f += "<label>";
    f += label;
    if (hint[0]) {
        f += " <small style='color:#666'>";
        f += hint;
        f += "</small>";
    }
    f += "</label><br><input name='";
    f += name;
    f += "' type='";
    f += type;
    f += "' value='";
    f += value;
    f += "' style='width:100%;padding:8px;margin:4px 0 12px;'><br>";
    return f;
}

}  // namespace

bool WifiProvisioner::connect(const NodeConfig& cfg, uint32_t timeout_ms) {
    if (cfg.ssid.empty()) return false;
    Serial.printf("[WIFI] Connecting to '%s'...\n", cfg.ssid.c_str());
    WiFi.mode(WIFI_STA);
    WiFi.begin(cfg.ssid.c_str(), cfg.pass.c_str());
    uint32_t deadline = millis() + timeout_ms;
    while (WiFi.status() != WL_CONNECTED && (int32_t)(millis() - deadline) < 0) {
        delay(250);
    }
    if (WiFi.status() == WL_CONNECTED) {
        Serial.printf("[WIFI] Connected. IP: %s\n",
                      WiFi.localIP().toString().c_str());
        return true;
    }
    Serial.println("[WIFI] Connect timed out.");
    return false;
}

void WifiProvisioner::start_ntp(const NodeConfig& cfg) {
    configTime(0, 0, cfg.ntp_host.c_str(), "time.google.com");
    // Bounded best-effort wait; the HMAC path stays clock-gated regardless.
    for (int i = 0; i < 10; ++i) {
        time_t now = time(nullptr);
        if (now > 1577836800) {  // 2020-01-01
            Serial.printf("[TIME] SNTP synced at %ld\n", (long)now);
            return;
        }
        delay(200);
    }
    Serial.println("[TIME] SNTP not yet synced — signed commands stay "
                   "rejected until the clock is sane.");
}

void WifiProvisioner::run_portal(const NodeConfig& current) {
    WiFi.mode(WIFI_AP);
    WiFi.softAP("SporePrint-Setup");
    Serial.printf("[WIFI] Setup AP up. Join 'SporePrint-Setup', open http://%s/\n",
                  WiFi.softAPIP().toString().c_str());

    WebServer portal(80);
    bool done = false;

    portal.on("/", HTTP_GET, [&]() {
        String page = kFormHead;
        page += text_field("WiFi network (SSID)", "ssid",
                           String(current.ssid.c_str()));
        page += text_field("WiFi password", "pass", "", "password");
        page += text_field("Pi address", "host",
                           String(current.broker_host.c_str()), "text",
                           "hostname or IP; default sporeprint.local");
        page += text_field("MQTT username", "mqtt_user",
                           String(current.mqtt_user.c_str()), "text",
                           "optional");
        page += text_field("MQTT password", "mqtt_pass", "", "password",
                           "optional");
        page += text_field("Node id", "node_id",
                           String(current.node_id.c_str()), "text",
                           "optional; auto from MAC");
        // Personality selector.
        page += "<label>Node personality</label><br>"
                "<select name='personality' style='width:100%;padding:8px;margin:4px 0 12px;'>";
        const char* opts[] = {"climate", "relay", "lighting"};
        for (const char* o : opts) {
            page += "<option value='";
            page += o;
            page += "'";
            if (strcmp(o, sp::personality_str(current.personality)) == 0)
                page += " selected";
            page += ">";
            page += o;
            page += "</option>";
        }
        page += "</select><br>";
        page += text_field("OTA password", "ota_pass", "", "password",
                           "min 12 chars; empty disables OTA");
        page += text_field("Command signing key (HMAC)", "hmac_key", "",
                           "password",
                           "from the Pi's provision tool; empty = warn mode");
        page += "<label><input type='checkbox' name='tls' value='1'";
        if (current.tls_enabled) page += " checked";
        page += "> Secure MQTT (TLS \u2014 pins the Pi's certificate)"
                "</label><br><br>";
        page += text_field("NTP server", "ntp_host",
                           String(current.ntp_host.c_str()), "text",
                           "set to the Pi's address for airgapped rooms");
        page += kFormTail;
        portal.send(200, "text/html", page);
    });

    portal.on("/save", HTTP_POST, [&]() {
        NodeConfig cfg = current;
        cfg.ssid = portal.arg("ssid").c_str();
        cfg.pass = portal.arg("pass").c_str();
        if (portal.arg("host").length()) cfg.broker_host = portal.arg("host").c_str();
        cfg.mqtt_user = portal.arg("mqtt_user").c_str();
        if (portal.arg("mqtt_pass").length())
            cfg.mqtt_pass = portal.arg("mqtt_pass").c_str();
        if (portal.arg("node_id").length()) cfg.node_id = portal.arg("node_id").c_str();
        sp::Personality p;
        if (sp::personality_from_str(portal.arg("personality").c_str(), &p))
            cfg.personality = p;
        if (portal.arg("ota_pass").length()) cfg.ota_pass = portal.arg("ota_pass").c_str();
        if (portal.arg("hmac_key").length()) cfg.hmac_key = portal.arg("hmac_key").c_str();
        if (portal.arg("ntp_host").length()) cfg.ntp_host = portal.arg("ntp_host").c_str();
        cfg.tls_enabled = portal.arg("tls") == "1";
        cfg.save(kv_);
        portal.send(200, "text/html",
                    "<html><body style='font-family:sans-serif;max-width:420px;"
                    "margin:40px auto;'><h2>Saved.</h2><p>Restarting and "
                    "connecting&hellip;</p></body></html>");
        done = true;
    });

    portal.begin();

    // No WDT is armed here — the only hang protection needed is the
    // ceiling: an abandoned portal reboots to retry stored credentials.
    uint32_t started = millis();
    while (!done) {
        portal.handleClient();
        delay(10);
        if (millis() - started > kPortalCeilingMs) {
            Serial.println("[WIFI] Portal ceiling (10 min) — rebooting.");
            break;
        }
    }
    delay(1500);  // let the success page flush
    ESP.restart();
    while (true) {}  // unreachable
}

}  // namespace sp_device
