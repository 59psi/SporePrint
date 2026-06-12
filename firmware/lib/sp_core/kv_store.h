#pragma once
//
// kv_store — minimal key/value persistence interface so config logic is
// host-testable. The device adapter (sp_device/nvs_kv_store) wraps ESP32
// Preferences/NVS; tests use an in-memory map.
//
// Native-safe: no Arduino headers.

#include <stdint.h>

#include <map>
#include <string>

namespace sp {

class KvStore {
public:
    virtual ~KvStore() = default;
    virtual std::string get_string(const char* key,
                                   const std::string& def = "") = 0;
    virtual void set_string(const char* key, const std::string& value) = 0;
    virtual int32_t get_int(const char* key, int32_t def = 0) = 0;
    virtual void set_int(const char* key, int32_t value) = 0;
    virtual bool get_bool(const char* key, bool def = false) = 0;
    virtual void set_bool(const char* key, bool value) = 0;
    virtual void erase_all() = 0;
};

// In-memory implementation for host tests (and a handy provisioning mock).
class MemKvStore : public KvStore {
public:
    std::string get_string(const char* key, const std::string& def) override {
        auto it = strings_.find(key);
        return it == strings_.end() ? def : it->second;
    }
    void set_string(const char* key, const std::string& value) override {
        strings_[key] = value;
    }
    int32_t get_int(const char* key, int32_t def) override {
        auto it = ints_.find(key);
        return it == ints_.end() ? def : it->second;
    }
    void set_int(const char* key, int32_t value) override { ints_[key] = value; }
    bool get_bool(const char* key, bool def) override {
        auto it = bools_.find(key);
        return it == bools_.end() ? def : it->second;
    }
    void set_bool(const char* key, bool value) override { bools_[key] = value; }
    void erase_all() override {
        strings_.clear();
        ints_.clear();
        bools_.clear();
    }

private:
    std::map<std::string, std::string> strings_;
    std::map<std::string, int32_t> ints_;
    std::map<std::string, bool> bools_;
};

}  // namespace sp
