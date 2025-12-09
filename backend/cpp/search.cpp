#include <iostream>
#include <fstream>
#include <string>
#include <vector>
#include <unordered_map>
#include <algorithm>
#include <filesystem>

#include "json.hpp"
#include "config.hpp"

namespace fs = std::filesystem;
using json = nlohmann::json;

// ---------------------- Helper: Find backend directory ----------------------
// We assume executables run from backend/cpp/build.
// This function walks upwards until it finds a folder that has config.json.
fs::path findBackendDir() {
    fs::path current = fs::current_path();  // e.g. .../MiniGoogle-DSA/backend/cpp/build

    while (true) {
        fs::path candidate = current / "config.json";
        if (fs::exists(candidate)) {
            // We are directly in backend/
            return current;
        }

        if (!current.has_parent_path()) {
            throw std::runtime_error("Backend directory with config.json not found.");
        }

        current = current.parent_path(); // build -> cpp -> backend
    }
}

// ---------------------- Helper: Load lexicon ----------------------
json loadLexicon(const fs::path &backendDir, const json &config) {
    std::string indexesDirName = config.at("indexes_dir").get<std::string>();
    std::string lexiconFileName = config.at("lexicon_file").get<std::string>();

    fs::path lexiconPath = backendDir / indexesDirName / lexiconFileName;

    std::ifstream in(lexiconPath);
    if (!in.is_open()) {
        throw std::runtime_error("Cannot open lexicon.json at " + lexiconPath.string());
    }

    json lexicon;
    in >> lexicon;
    return lexicon;
}

// ---------------------- Helper: Get lemma ID from lexicon ----------------------
bool getLemmaIdForWord(const json &lexicon, const std::string &word, int &lemmaIdOut) {
    if (!lexicon.contains("wordID")) {
        throw std::runtime_error("lexicon.json does not contain 'wordID' object.");
    }

    const json &wordID = lexicon["wordID"]; // word -> lemmaId

    auto it = wordID.find(word);
    if (it == wordID.end()) {
        return false; // word not found
    }

    lemmaIdOut = it.value().get<int>();
    return true;
}

// ---------------------- Data structure for search results ----------------------
struct DocPosting {
    std::string docId;
    int tf; // term frequency in this document
};

// ---------------------- Helper: Search all barrels for lemma ----------------------
bool findPostingInBarrels(
    const fs::path &backendDir,
    const json &config,
    int lemmaId,
    json &postingOut,
    int &barrelFound
) {
    std::string indexesDirName = config.at("indexes_dir").get<std::string>();
    std::string barrelsDirName = config.at("barrels_dir").get<std::string>();

    fs::path barrelsRoot = backendDir / indexesDirName / barrelsDirName;

    // We know barrel files are named: inverted_barrel_n.json where n in [0, 9]
    // (You can easily generalize this later.)
    std::string lemmaKey = std::to_string(lemmaId);

    for (int b = 0; b <= 9; ++b) {
        std::string filename = "inverted_barrel_" + std::to_string(b) + ".json";
        fs::path barrelPath = barrelsRoot / filename;

        if (!fs::exists(barrelPath)) {
            // Skip missing barrels (maybe fewer than 10 exist)
            continue;
        }

        std::ifstream in(barrelPath);
        if (!in.is_open()) {
            std::cerr << "Warning: cannot open " << barrelPath << ", skipping.\n";
            continue;
        }

        json barrel;
        try {
            in >> barrel;
        } catch (const json::parse_error &e) {
            std::cerr << "Warning: JSON parse error in " << barrelPath << ": "
                      << e.what() << "\n";
            continue;
        }

        if (!barrel.contains("postings")) {
            std::cerr << "Warning: barrel " << barrelPath << " has no 'postings' object.\n";
            continue;
        }

        json &postings = barrel["postings"];
        auto it = postings.find(lemmaKey);
        if (it != postings.end()) {
            postingOut = *it;
            barrelFound = b;
            return true;
        }
    }

    return false; // lemma not found in any barrel
}

// ---------------------- MainSearch: Single-word query ----------------------
int main(int argc, char *argv[]) {
    try {
        // ----- 1. Get query word -----
        std::string queryWord;
        if (argc >= 2) {
            queryWord = argv[1];
        } else {
            std::cout << "Enter a single-word query: ";
            if (!std::getline(std::cin, queryWord)) {
                std::cerr << "No query provided.\n";
                return 1;
            }
        }

        if (queryWord.empty()) {
            std::cerr << "Empty query.\n";
            return 1;
        }

        // You might want to lowercase or normalize queryWord here
        // depending on how your lexicon is built.
        // For now, we assume exact match in lexicon.

        // ----- 2. Locate backend and load config -----
        fs::path backendDir = findBackendDir();   // finds directory containing config.json
        json config = loadConfig(backendDir);     // from config.hpp

        // ----- 3. Load lexicon -----
        json lexicon = loadLexicon(backendDir, config);

        // ----- 4. Find lemma ID -----
        int lemmaId;
        if (!getLemmaIdForWord(lexicon, queryWord, lemmaId)) {
            std::cout << "No results: word '" << queryWord << "' not found in lexicon.\n";
            return 0;
        }

        std::cout << "Query word: " << queryWord << "\n";
        std::cout << "Lemma ID: " << lemmaId << "\n";

        // ----- 5. Find postings for this lemma in barrels -----
        json postingJson;
        int barrelId = -1;
        if (!findPostingInBarrels(backendDir, config, lemmaId, postingJson, barrelId)) {
            std::cout << "No postings found for lemma ID " << lemmaId
                      << " in any barrel.\n";
            return 0;
        }

        std::cout << "Found in barrel: " << barrelId << "\n";

        // postingJson structure (as you described):
        // {
        //   "df": 47671,
        //   "docs": [
        //     { "doc_id": "PMC7134257", "tf": 3 },
        //     { "doc_id": "PMC5583365", "tf": 7 },
        //     ...
        //   ]
        // }

        int df = postingJson.value("df", 0);
        std::cout << "Document frequency (df): " << df << "\n";

        if (!postingJson.contains("docs") || !postingJson["docs"].is_array()) {
            std::cerr << "Error: posting for lemma " << lemmaId
                      << " has no valid 'docs' array.\n";
            return 1;
        }

        const json &docs = postingJson["docs"];
        std::vector<DocPosting> results;
        results.reserve(docs.size());

        for (const auto &d : docs) {
            DocPosting dp;
            dp.docId = d.at("doc_id").get<std::string>();
            dp.tf    = d.at("tf").get<int>();
            results.push_back(dp);
        }

        // ----- 6. Rank results (simple: by tf descending) -----
        std::sort(results.begin(), results.end(),
                  [](const DocPosting &a, const DocPosting &b) {
                      if (a.tf != b.tf) return a.tf > b.tf;
                      return a.docId < b.docId; // tie-breaker
                  });

        // ----- 7. Print top-k results -----
        const std::size_t TOP_K = 20;
        std::cout << "\nTop " << std::min(TOP_K, results.size())
                  << " results for '" << queryWord << "':\n";

        std::size_t count = 0;
        for (const auto &r : results) {
            if (count >= TOP_K) break;
            std::cout << (count + 1) << ". DocID: " << r.docId
                      << " | tf: " << r.tf << "\n";
            ++count;
        }

        if (results.empty()) {
            std::cout << "No documents contain this term.\n";
        }

    } catch (const std::exception &e) {
        std::cerr << "Fatal error: " << e.what() << "\n";
        return 1;
    }

    return 0;
}
