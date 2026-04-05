#include "config_store.h"

ConfigStore::ConfigStore(const char* ns) : _namespace(ns) {}

String ConfigStore::getString(const char* key, const String& defaultVal) {
    _prefs.begin(_namespace, true);
    String val = _prefs.getString(key, defaultVal);
    _prefs.end();
    return val;
}

void ConfigStore::setString(const char* key, const String& value) {
    _prefs.begin(_namespace, false);
    _prefs.putString(key, value);
    _prefs.end();
}

int32_t ConfigStore::getInt(const char* key, int32_t defaultVal) {
    _prefs.begin(_namespace, true);
    int32_t val = _prefs.getInt(key, defaultVal);
    _prefs.end();
    return val;
}

void ConfigStore::setInt(const char* key, int32_t value) {
    _prefs.begin(_namespace, false);
    _prefs.putInt(key, value);
    _prefs.end();
}

bool ConfigStore::getBool(const char* key, bool defaultVal) {
    _prefs.begin(_namespace, true);
    bool val = _prefs.getBool(key, defaultVal);
    _prefs.end();
    return val;
}

void ConfigStore::setBool(const char* key, bool value) {
    _prefs.begin(_namespace, false);
    _prefs.putBool(key, value);
    _prefs.end();
}

void ConfigStore::factoryReset() {
    _prefs.begin(_namespace, false);
    _prefs.clear();
    _prefs.end();

    // Also clear wifi namespace
    _prefs.begin("wifi", false);
    _prefs.clear();
    _prefs.end();

    _prefs.begin("mqtt", false);
    _prefs.clear();
    _prefs.end();

    Serial.println("[CONFIG] Factory reset complete. Restarting...");
    delay(1000);
    ESP.restart();
}
