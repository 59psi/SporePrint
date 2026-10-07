#include "wifi_provisioner.h"

#include <WebServer.h>
#include <WiFi.h>
#include <time.h>

#include <string>

#include "boot_policy.h"
#include "provisioning.h"

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

// `value` / `placeholder` are operator data (an SSID like "Bob's Lab") —
// always escaped, never spliced raw into the attribute.
// `attrs`: trusted literal attributes (client-side validation hints only —
// /save re-checks everything).
String text_field(const char* label, const char* name, const std::string& value,
                  const char* type = "text", const char* hint = "",
                  const std::string& placeholder = std::string(),
                  const char* attrs = "") {
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
    f += sp::html_escape(value).c_str();
    f += "'";
    if (!placeholder.empty()) {
        f += " placeholder='";
        f += sp::html_escape(placeholder).c_str();
        f += "'";
    }
    if (attrs[0]) {
        f += " ";
        f += attrs;
    }
    f += " style='width:100%;padding:8px;margin:4px 0 12px;'><br>";
    return f;
}

String checkbox(const char* name, bool checked, const char* label) {
    String f = "<label><input type='checkbox' name='";
    f += name;
    f += "' value='1'";
    if (checked) f += " checked";
    f += "> ";
    f += label;
    f += "</label><br>";
    return f;
}

std::string arg_str(WebServer& portal, const char* name) {
    return std::string(portal.arg(name).c_str());
}

const char kTlsIpNote[] =
    "Secure MQTT checks the Pi's certificate against the address typed "
    "here. An IP address only verifies if the Pi's certificate lists it "
    "(install.sh adds the Pi's IPs; a DHCP change moves the IP) &mdash; "
    "sporeprint.local is the most robust choice.";

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

    // A node id never written to NVS is the MAC-derived default: show it as a
    // placeholder so a blank field resolves to the MQTT username (the build
    // guide's "accept the default" used to land on an id the ACL denies).
    const bool node_id_auto = kv_.get_string("node_id", "").empty();
    const bool peripheral_opts = peripheral_opts_;
    const bool personality_opt = personality_opt_;

    // Secrets are never pre-filled from NVS. A refused /save, though, hands
    // the form back with what was just SUBMITTED — the operator's own values,
    // returned only to the client that sent them — so fixing the node id and
    // resubmitting saves exactly what was first intended. (The fields used to
    // come back blank: on a fresh node the resubmit silently stored no MQTT
    // password, no OTA password and no HMAC key — warn mode.)
    struct Submitted {
        std::string pass, mqtt_pass, ota_pass, hmac_key;
        bool open_net = false;
    };
    const Submitted none;

    auto render = [&](const NodeConfig& v, const std::string& node_id_value,
                      const char* error, const Submitted& echo) {
        String page = kFormHead;
        if (error != nullptr) {
            page += "<p style='color:#b00020;border:1px solid #b00020;"
                    "padding:8px;'><b>Not saved.</b> ";
            page += sp::html_escape(error).c_str();
            page += "</p>";
        }
        page += text_field("WiFi network (SSID)", "ssid", v.ssid, "text", "",
                           std::string(), "required maxlength='32'");
        page += text_field("WiFi password", "pass", echo.pass, "password",
                           "blank keeps the saved password");
        page += checkbox("open_net", echo.open_net, "Open network (no password)");
        page += "<br>";
        page += text_field("Pi address", "host", v.broker_host, "text",
                           "hostname or IP; default sporeprint.local");
        page += text_field("MQTT username", "mqtt_user", v.mqtt_user, "text",
                           "from add-node-mqtt-user.sh");
        page += text_field("MQTT password", "mqtt_pass", echo.mqtt_pass,
                           "password", "blank keeps the saved one");
        page += text_field("Node id", "node_id", node_id_value, "text",
                           "must equal the MQTT username; blank = use it",
                           node_id_auto ? current.node_id : std::string(),
                           "maxlength='32' pattern='[A-Za-z0-9_\\-]*' "
                           "title='letters, digits, - or _'");
        // Personality selector (node image only — the camera ignores it).
        if (personality_opt) {
            page += "<label>Node personality</label><br>"
                    "<select name='personality' style='width:100%;padding:8px;margin:4px 0 12px;'>";
            const char* opts[] = {"climate", "relay", "lighting"};
            for (const char* o : opts) {
                page += "<option value='";
                page += o;
                page += "'";
                if (strcmp(o, sp::personality_str(v.personality)) == 0)
                    page += " selected";
                page += ">";
                page += o;
                page += "</option>";
            }
            page += "</select><br>";
        }
        page += text_field("OTA password", "ota_pass", echo.ota_pass,
                           "password",
                           "min 12 chars; blank keeps the saved one; none "
                           "saved disables OTA");
        page += text_field("Command signing key (HMAC)", "hmac_key",
                           echo.hmac_key, "password",
                           "from the Pi's provision tool; blank keeps the "
                           "saved one; none saved = warn mode");
        page += checkbox("tls", v.tls_enabled,
                         "Secure MQTT (TLS \u2014 pins the Pi's certificate)");
        page += checkbox("tls_req", v.tls_required,
                         "Require TLS \u2014 if the Pi's certificate can't be "
                         "pinned, stay offline instead of falling back to "
                         "plaintext");
        page += "<small style='color:#666'>";
        page += kTlsIpNote;
        page += "</small><br><br>";
        page += text_field("NTP server", "ntp_host", v.ntp_host, "text",
                           "set to the Pi's address for airgapped rooms");
        if (peripheral_opts) {
            // Tier-3 drivers are built only when these NVS flags are set
            // (docs#0: there used to be no way to set them at all).
            page += "<fieldset style='margin:4px 0 12px;'>"
                    "<legend>Optional peripherals</legend>";
            page += checkbox("mhz19", v.mhz19_enabled,
                             "MH-Z19C CO2 sensor (UART)");
            page += checkbox("hx711", v.hx711_enabled,
                             "HX711 load-cell scale");
            page += checkbox("reed", v.reed_enabled, "Door reed switch");
            page += checkbox("reed_inv", v.reed_invert,
                             "&nbsp;&nbsp;Door contact wired on its NO "
                             "terminal (open with the door shut) \u2014 invert");
            page += "</fieldset>";
        }
        page += kFormTail;
        return page;
    };

    portal.on("/", HTTP_GET, [&]() {
        portal.send(200, "text/html",
                    render(current,
                           node_id_auto ? std::string() : current.node_id,
                           nullptr, none));
    });

    portal.on("/save", HTTP_POST, [&]() {
        NodeConfig cfg = current;
        cfg.ssid = arg_str(portal, "ssid");
        // Blank keeps the stored password on the same network (it used to
        // erase it); never carried over to a different SSID.
        cfg.pass = sp::resolve_wifi_pass(current.ssid, current.pass, cfg.ssid,
                                         arg_str(portal, "pass"),
                                         portal.arg("open_net") == "1");
        if (portal.arg("host").length()) cfg.broker_host = arg_str(portal, "host");
        cfg.mqtt_user = arg_str(portal, "mqtt_user");
        if (portal.arg("mqtt_pass").length())
            cfg.mqtt_pass = arg_str(portal, "mqtt_pass");
        sp::Personality p;
        if (personality_opt &&
            sp::personality_from_str(portal.arg("personality").c_str(), &p))
            cfg.personality = p;
        if (portal.arg("ota_pass").length()) cfg.ota_pass = arg_str(portal, "ota_pass");
        if (portal.arg("hmac_key").length()) cfg.hmac_key = arg_str(portal, "hmac_key");
        if (portal.arg("ntp_host").length()) cfg.ntp_host = arg_str(portal, "ntp_host");
        cfg.tls_enabled = portal.arg("tls") == "1";
        cfg.tls_required = portal.arg("tls_req") == "1";
        if (peripheral_opts) {
            // Unchecked boxes are absent from the POST, so "== 1" covers both.
            cfg.mhz19_enabled = portal.arg("mhz19") == "1";
            cfg.hx711_enabled = portal.arg("hx711") == "1";
            cfg.reed_enabled = portal.arg("reed") == "1";
            cfg.reed_invert = portal.arg("reed_inv") == "1";
        }

        const std::string form_node_id = arg_str(portal, "node_id");
        std::string node_id;
        const char* error =
            cfg.ssid.empty()
                ? "WiFi network (SSID) is required."
                : sp::resolve_node_id(form_node_id, cfg.mqtt_user,
                                      current.node_id, &node_id);
        if (error != nullptr) {
            // Nothing saved: hand the form back with the reason and exactly
            // what was submitted, secrets included (see Submitted).
            Submitted echo;
            echo.pass = arg_str(portal, "pass");
            echo.mqtt_pass = arg_str(portal, "mqtt_pass");
            echo.ota_pass = arg_str(portal, "ota_pass");
            echo.hmac_key = arg_str(portal, "hmac_key");
            echo.open_net = portal.arg("open_net") == "1";
            portal.send(400, "text/html",
                        render(cfg, form_node_id, error, echo));
            return;
        }
        cfg.node_id = node_id;
        // New settings must connect once before a later boot-time WiFi
        // failure is treated as transient (boot_policy.h): new credentials,
        // or Secure MQTT with no CA pinned yet (the CA fetch needs the link;
        // booting offline would leave the session on plaintext).
        if (sp::portal_save_needs_first_connect(
                cfg.ssid != current.ssid || cfg.pass != current.pass,
                cfg.tls_enabled, !kv_.get_string("broker_ca", "").empty()))
            cfg.wifi_verified = false;
        cfg.save(kv_);

        String saved =
            "<html><body style='font-family:sans-serif;max-width:420px;"
            "margin:40px auto;'><h2>Saved.</h2><p>Node id <b>";
        saved += sp::html_escape(cfg.node_id).c_str();
        saved += "</b>. Restarting and connecting&hellip;</p>";
        if (cfg.tls_enabled && sp::is_ipv4_literal(cfg.broker_host)) {
            saved += "<p><b>Note:</b> ";
            saved += kTlsIpNote;
            saved += "</p>";
        }
        saved += "</body></html>";
        portal.send(200, "text/html", saved);
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
