#include "wifi_manager.h"

static WebServer* _portal = nullptr;
static bool _portalDone = false;
static String _portalSSID;
static String _portalPass;

WiFiManager::WiFiManager(ConfigStore& config) : _config(config) {}

void WiFiManager::begin() {
    String ssid = _config.getString("ssid");
    String pass = _config.getString("pass");

    if (ssid.length() == 0) {
        Serial.println("[WIFI] No credentials stored. Starting captive portal...");
        _startCaptivePortal();
        return;
    }

    if (_tryConnect()) {
        return;
    }

    Serial.println("[WIFI] Could not connect with stored credentials. Starting portal...");
    _startCaptivePortal();
}

bool WiFiManager::_tryConnect() {
    String ssid = _config.getString("ssid");
    String pass = _config.getString("pass");

    Serial.printf("[WIFI] Connecting to '%s'...\n", ssid.c_str());
    WiFi.mode(WIFI_STA);
    WiFi.begin(ssid.c_str(), pass.c_str());

    int attempts = 0;
    while (WiFi.status() != WL_CONNECTED && attempts < 40) {
        delay(500);
        Serial.print(".");
        attempts++;
    }
    Serial.println();

    if (WiFi.status() == WL_CONNECTED) {
        _connected = true;
        Serial.printf("[WIFI] Connected! IP: %s\n", WiFi.localIP().toString().c_str());
        return true;
    }

    return false;
}

void WiFiManager::_startCaptivePortal() {
    WiFi.mode(WIFI_AP);
    WiFi.softAP("SporePrint-Setup");
    Serial.printf("[WIFI] AP started. Connect to 'SporePrint-Setup' and go to %s\n",
                  WiFi.softAPIP().toString().c_str());

    _portal = new WebServer(80);
    _portalDone = false;

    ConfigStore& cfg = _config;

    _portal->on("/", HTTP_GET, []() {
        _portal->send(200, "text/html",
            "<html><body style='font-family:sans-serif;max-width:400px;margin:50px auto;'>"
            "<h2>SporePrint WiFi Setup</h2>"
            "<form method='post' action='/save'>"
            "<label>SSID:</label><br><input name='ssid' style='width:100%;padding:8px;margin:4px 0 12px;'><br>"
            "<label>Password:</label><br><input name='pass' type='password' style='width:100%;padding:8px;margin:4px 0 12px;'><br>"
            "<button type='submit' style='padding:10px 20px;'>Save & Connect</button>"
            "</form></body></html>");
    });

    _portal->on("/save", HTTP_POST, [&cfg]() {
        _portalSSID = _portal->arg("ssid");
        _portalPass = _portal->arg("pass");
        cfg.setString("ssid", _portalSSID);
        cfg.setString("pass", _portalPass);
        _portal->send(200, "text/html",
            "<html><body style='font-family:sans-serif;max-width:400px;margin:50px auto;'>"
            "<h2>Saved!</h2><p>Restarting...</p></body></html>");
        _portalDone = true;
    });

    _portal->begin();

    // Hard ceiling on how long the node sits in captive-portal mode. Without
    // this, a user who opens the portal page, gets distracted, and never
    // submits the form leaves the node stuck in AP mode forever. After 10
    // minutes with no submit, reboot so the node re-attempts its saved
    // credentials (or, if none, comes back into the portal fresh).
    const unsigned long PORTAL_TIMEOUT_MS = 10UL * 60UL * 1000UL;
    unsigned long portalStart = millis();

    while (!_portalDone) {
        _portal->handleClient();
        delay(10);

        if (millis() - portalStart > PORTAL_TIMEOUT_MS) {
            Serial.println("[WIFI] Captive portal timed out — rebooting to retry");
            delete _portal;
            _portal = nullptr;
            delay(500);
            ESP.restart();
            return;  // unreachable; ESP.restart() does not return
        }
    }

    delay(2000);
    delete _portal;
    _portal = nullptr;
    ESP.restart();
}

bool WiFiManager::isConnected() {
    return WiFi.status() == WL_CONNECTED;
}

String WiFiManager::getIP() {
    return WiFi.localIP().toString();
}

int WiFiManager::getRSSI() {
    return WiFi.RSSI();
}
