#pragma once

#include <filesystem>
#include "json.hpp"

namespace fs = std::filesystem;
using json = nlohmann::json;


// Load config.json from backend directory

json loadConfig(const fs::path& backendDir);
fs::path findPMCJSONFolder(const fs::path& dataDir, const std::string& filename);
