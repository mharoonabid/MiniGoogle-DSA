#pragma once

#include <filesystem>
#include "json.hpp"
#include <fstream>
#include <stdexcept>
namespace fs = std::filesystem;
using json = nlohmann::json;


// Load config.json from backend directory

inline json loadConfig(const fs::path &backendDir) {
    fs::path configPath = backendDir / "config.json";
    std::ifstream file(configPath);
    if (!file.is_open()) {
        throw std::runtime_error("Cannot open config.json at " + configPath.string());
    }

    json config;
    try {
        file >> config;
    } catch (const json::parse_error& e) {
        throw std::runtime_error(std::string("JSON parse error: ") + e.what());
    }

    return config;
}


// Find pmc-json folder under data_dir recursively
inline fs::path findPMCJSONFolder(const fs::path& dataDir, const std::string& filename) {
    for (auto& p : fs::recursive_directory_iterator(dataDir)) {
        if (p.is_directory() && p.path().filename() == filename) {
            return p.path();
        }
    }
    throw std::runtime_error(filename + " folder not found under data directory");
}

