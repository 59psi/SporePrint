#pragma once

#include <Arduino.h>
#include <Preferences.h>

class ConfigStore {
public:
    ConfigStore(const char* ns = "sporeprint");

    String getString(const char* key, const String& defaultVal = "");
    void setString(const char* key, const String& value);
    int32_t getInt(const char* key, int32_t defaultVal = 0);
    void setInt(const char* key, int32_t value);
    bool getBool(const char* key, bool defaultVal = false);
    void setBool(const char* key, bool value);

    void factoryReset();

private:
    Preferences _prefs;
    const char* _namespace;
};
