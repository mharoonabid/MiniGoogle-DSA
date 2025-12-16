/*
 * Optimized Search Engine
 *
 * Features:
 * - Binary barrel format support (O(1) seeks) - sub-500ms response time
 * - Single-word and multi-word query support
 * - AND/OR query modes for multi-word queries
 * - TF-IDF ranking
 * - Cached lexicon and barrel lookup for repeated queries
 *
 * Usage:
 *   ./search "single word"
 *   ./search "word1 word2 word3"          # Default: AND mode
 *   ./search "word1 word2 word3" --or     # OR mode
 *   ./search "word1 word2 word3" --and    # AND mode (explicit)
 */

#include <iostream>
#include <fstream>
#include <sstream>
#include <string>
#include <vector>
#include <algorithm>
#include <filesystem>
#include <unordered_map>
#include <unordered_set>
#include <cstring>
#include <cmath>
#include <chrono>
#include <cctype>

#include "config.hpp"

namespace fs = std::filesystem;
using json = nlohmann::json;
using namespace std::chrono;

// Constants
const int DOC_ID_SIZE = 20;
const int TOTAL_DOCS = 59000;  // Approximate total documents for IDF calculation

// ---------------------- Data Structures ----------------------

struct DocPosting {
    std::string docId;
    int tf;           // Term frequency
    double score;     // TF-IDF score
};

struct IndexEntry {
    int64_t offset;
    int64_t length;
};

// ---------------------- Global Cache (loaded once) ----------------------

struct SearchCache {
    std::unordered_map<std::string, int> wordToLemmaId;  // word -> lemmaId (from binary lexicon)
    json lexicon;  // fallback for JSON lexicon
    bool useBinaryLexicon = false;
    std::unordered_map<int, int> barrelLookup;  // lemmaId -> barrelId
    std::unordered_map<int, std::unordered_map<int, IndexEntry>> barrelIndices;  // barrelId -> (lemmaId -> IndexEntry)
    bool initialized = false;
    fs::path backendDir;
};

static SearchCache g_cache;

// ---------------------- Utility Functions ----------------------

std::string toLower(const std::string& str) {
    std::string result = str;
    std::transform(result.begin(), result.end(), result.begin(),
                   [](unsigned char c) { return std::tolower(c); });
    return result;
}

std::vector<std::string> tokenize(const std::string& query) {
    std::vector<std::string> tokens;
    std::istringstream iss(query);
    std::string token;
    while (iss >> token) {
        // Remove punctuation and convert to lowercase
        std::string clean;
        for (char c : token) {
            if (std::isalnum(c)) {
                clean += std::tolower(c);
            }
        }
        if (!clean.empty()) {
            tokens.push_back(clean);
        }
    }
    return tokens;
}

// ---------------------- Binary Lexicon Loading ----------------------

bool loadBinaryLexicon(const fs::path& binPath) {
    if (!fs::exists(binPath)) {
        return false;
    }

    std::ifstream binFile(binPath, std::ios::binary);
    if (!binFile.is_open()) {
        return false;
    }

    uint32_t numWords;
    binFile.read(reinterpret_cast<char*>(&numWords), sizeof(numWords));

    std::vector<std::pair<std::string, int>> words;
    words.reserve(numWords);

    for (uint32_t i = 0; i < numWords; i++) {
        uint16_t wordLen;
        binFile.read(reinterpret_cast<char*>(&wordLen), sizeof(wordLen));

        std::string word(wordLen, '\0');
        binFile.read(&word[0], wordLen);

        words.push_back({word, 0});
    }

    for (uint32_t i = 0; i < numWords; i++) {
        int32_t lemmaId;
        binFile.read(reinterpret_cast<char*>(&lemmaId), sizeof(lemmaId));
        words[i].second = lemmaId;
        g_cache.wordToLemmaId[words[i].first] = lemmaId;
    }

    binFile.close();
    return true;
}

// ---------------------- Cache Initialization ----------------------

void initializeCache(const fs::path& backendDir, const json& config) {
    if (g_cache.initialized) return;

    auto startTime = high_resolution_clock::now();
    g_cache.backendDir = backendDir;

    fs::path indexesDir = backendDir / config["indexes_dir"].get<std::string>();
    fs::path lexiconPath = indexesDir / config["lexicon_file"].get<std::string>();
    fs::path lookupPath = indexesDir / config["barrel_lookup"].get<std::string>();
    fs::path binaryBarrelsDir = indexesDir / "barrels_binary";
    fs::path embeddingsDir = indexesDir / "embeddings";

    // Try binary lexicon first (much faster)
    fs::path binLexPath = embeddingsDir / "lexicon.bin";
    if (loadBinaryLexicon(binLexPath)) {
        g_cache.useBinaryLexicon = true;
    } else {
        // Fallback to JSON lexicon
        std::ifstream lexFile(lexiconPath);
        if (!lexFile.is_open()) {
            throw std::runtime_error("Cannot open lexicon at " + lexiconPath.string());
        }
        lexFile >> g_cache.lexicon;
        lexFile.close();
    }

    // Load barrel lookup
    std::ifstream lookupFile(lookupPath);
    if (!lookupFile.is_open()) {
        throw std::runtime_error("Cannot open barrel_lookup.json at " + lookupPath.string());
    }
    json lookupJson;
    lookupFile >> lookupJson;
    lookupFile.close();

    for (auto& [key, val] : lookupJson.items()) {
        g_cache.barrelLookup[std::stoi(key)] = val.get<int>();
    }

    // Load binary barrel indices
    for (int barrelId = 0; barrelId < 10; barrelId++) {
        fs::path idxPath = binaryBarrelsDir / ("barrel_" + std::to_string(barrelId) + ".idx");

        if (!fs::exists(idxPath)) {
            continue;
        }

        std::ifstream idxFile(idxPath, std::ios::binary);
        if (!idxFile.is_open()) continue;

        int32_t numEntries;
        idxFile.read(reinterpret_cast<char*>(&numEntries), sizeof(numEntries));

        for (int i = 0; i < numEntries; i++) {
            int32_t lemmaId;
            int64_t offset, length;

            idxFile.read(reinterpret_cast<char*>(&lemmaId), sizeof(lemmaId));
            idxFile.read(reinterpret_cast<char*>(&offset), sizeof(offset));
            idxFile.read(reinterpret_cast<char*>(&length), sizeof(length));

            g_cache.barrelIndices[barrelId][lemmaId] = {offset, length};
        }

        idxFile.close();
    }

    g_cache.initialized = true;

    auto endTime = high_resolution_clock::now();
    auto duration = duration_cast<milliseconds>(endTime - startTime).count();
    std::cout << "[Cache initialized in " << duration << "ms]\n" << std::endl;
}

// ---------------------- Lexicon Lookup ----------------------

bool getLemmaIdForWord(const std::string& word, int& lemmaIdOut) {
    // Use binary lexicon if available
    if (g_cache.useBinaryLexicon) {
        auto it = g_cache.wordToLemmaId.find(word);
        if (it != g_cache.wordToLemmaId.end()) {
            lemmaIdOut = it->second;
            return true;
        }
        return false;
    }

    // Fallback to JSON lexicon
    if (!g_cache.lexicon.contains("wordID")) {
        return false;
    }

    const json& wordID = g_cache.lexicon["wordID"];
    auto it = wordID.find(word);
    if (it == wordID.end()) {
        return false;
    }

    lemmaIdOut = it.value().get<int>();
    return true;
}

// ---------------------- Binary Barrel Search (FAST) ----------------------

bool findPostingsBinary(
    const fs::path& backendDir,
    const json& config,
    int lemmaId,
    std::vector<DocPosting>& postingsOut,
    int& dfOut,
    int& barrelIdOut
) {
    // Find barrel
    auto it = g_cache.barrelLookup.find(lemmaId);
    if (it == g_cache.barrelLookup.end()) {
        return false;
    }

    barrelIdOut = it->second;

    // Find offset in barrel index
    auto& barrelIdx = g_cache.barrelIndices[barrelIdOut];
    auto offsetIt = barrelIdx.find(lemmaId);
    if (offsetIt == barrelIdx.end()) {
        return false;
    }

    IndexEntry entry = offsetIt->second;

    // Open binary barrel file and seek to offset
    fs::path indexesDir = backendDir / config["indexes_dir"].get<std::string>();
    fs::path binPath = indexesDir / "barrels_binary" / ("barrel_" + std::to_string(barrelIdOut) + ".bin");

    std::ifstream binFile(binPath, std::ios::binary);
    if (!binFile.is_open()) {
        return false;
    }

    binFile.seekg(entry.offset);

    // Read posting header
    int32_t readLemmaId, df, numDocs;
    binFile.read(reinterpret_cast<char*>(&readLemmaId), sizeof(readLemmaId));
    binFile.read(reinterpret_cast<char*>(&df), sizeof(df));
    binFile.read(reinterpret_cast<char*>(&numDocs), sizeof(numDocs));

    dfOut = df;

    // Read postings
    postingsOut.clear();
    postingsOut.reserve(numDocs);

    for (int i = 0; i < numDocs; i++) {
        char docIdBuf[DOC_ID_SIZE];
        int32_t tf;

        binFile.read(docIdBuf, DOC_ID_SIZE);
        binFile.read(reinterpret_cast<char*>(&tf), sizeof(tf));

        DocPosting dp;
        dp.docId = std::string(docIdBuf);
        dp.tf = tf;
        dp.score = 0.0;

        postingsOut.push_back(dp);
    }

    binFile.close();
    return true;
}

// ---------------------- JSON Barrel Search (FALLBACK) ----------------------

bool findPostingsJSON(
    const fs::path& backendDir,
    const json& config,
    int lemmaId,
    std::vector<DocPosting>& postingsOut,
    int& dfOut,
    int& barrelIdOut
) {
    auto it = g_cache.barrelLookup.find(lemmaId);
    if (it == g_cache.barrelLookup.end()) {
        return false;
    }

    barrelIdOut = it->second;

    fs::path indexesDir = backendDir / config["indexes_dir"].get<std::string>();
    fs::path barrelPath = indexesDir / config["barrels_dir"].get<std::string>() /
                          ("inverted_barrel_" + std::to_string(barrelIdOut) + ".json");

    std::cout << "[WARNING: Using slow JSON barrel. Run barrels_binary first!]" << std::endl;

    std::ifstream barrelFile(barrelPath);
    if (!barrelFile.is_open()) {
        return false;
    }

    json barrel;
    barrelFile >> barrel;
    barrelFile.close();

    std::string lemmaKey = std::to_string(lemmaId);
    if (!barrel["postings"].contains(lemmaKey)) {
        return false;
    }

    const json& postingJson = barrel["postings"][lemmaKey];
    dfOut = postingJson.value("df", 0);

    postingsOut.clear();
    for (const auto& d : postingJson["docs"]) {
        DocPosting dp;
        dp.docId = d.at("doc_id").get<std::string>();
        dp.tf = d.at("tf").get<int>();
        dp.score = 0.0;
        postingsOut.push_back(dp);
    }

    return true;
}

// ---------------------- Universal Posting Finder ----------------------

bool findPostings(
    const fs::path& backendDir,
    const json& config,
    int lemmaId,
    std::vector<DocPosting>& postingsOut,
    int& dfOut,
    int& barrelIdOut
) {
    // Try binary first (fast)
    if (findPostingsBinary(backendDir, config, lemmaId, postingsOut, dfOut, barrelIdOut)) {
        return true;
    }

    // Fallback to JSON (slow)
    return findPostingsJSON(backendDir, config, lemmaId, postingsOut, dfOut, barrelIdOut);
}

// ---------------------- TF-IDF Scoring ----------------------

double calculateTFIDF(int tf, int df, int totalDocs = TOTAL_DOCS) {
    if (tf == 0 || df == 0) return 0.0;

    // TF: 1 + log(tf)
    double tfScore = 1.0 + std::log10(static_cast<double>(tf));

    // IDF: log(N/df)
    double idf = std::log10(static_cast<double>(totalDocs) / static_cast<double>(df));

    return tfScore * idf;
}

// ---------------------- Multi-Word Query Processing ----------------------

enum QueryMode { AND_MODE, OR_MODE };

struct QueryResult {
    std::string docId;
    double totalScore;
    int matchedTerms;
    std::vector<int> termFreqs;  // TF for each query term
};

std::vector<QueryResult> processMultiWordQuery(
    const fs::path& backendDir,
    const json& config,
    const std::vector<std::string>& queryWords,
    QueryMode mode,
    std::vector<int>& lemmaIds,
    std::vector<int>& dfs
) {
    // Get postings for each word
    std::vector<std::vector<DocPosting>> allPostings;
    lemmaIds.clear();
    dfs.clear();

    for (const auto& word : queryWords) {
        int lemmaId;
        if (!getLemmaIdForWord(word, lemmaId)) {
            std::cout << "  Word '" << word << "': not found in lexicon" << std::endl;
            continue;
        }

        std::vector<DocPosting> postings;
        int df, barrelId;

        if (!findPostings(backendDir, config, lemmaId, postings, df, barrelId)) {
            std::cout << "  Word '" << word << "': no postings found" << std::endl;
            continue;
        }

        std::cout << "  Word '" << word << "': lemmaId=" << lemmaId
                  << ", df=" << df << ", barrel=" << barrelId << std::endl;

        lemmaIds.push_back(lemmaId);
        dfs.push_back(df);
        allPostings.push_back(postings);
    }

    if (allPostings.empty()) {
        return {};
    }

    // Build document -> scores map
    std::unordered_map<std::string, QueryResult> docScores;

    for (size_t i = 0; i < allPostings.size(); i++) {
        int df = dfs[i];

        for (const auto& posting : allPostings[i]) {
            double tfidf = calculateTFIDF(posting.tf, df);

            auto& result = docScores[posting.docId];
            if (result.docId.empty()) {
                result.docId = posting.docId;
                result.totalScore = 0.0;
                result.matchedTerms = 0;
                result.termFreqs.resize(allPostings.size(), 0);
            }

            result.totalScore += tfidf;
            result.matchedTerms++;
            result.termFreqs[i] = posting.tf;
        }
    }

    // Filter by query mode
    std::vector<QueryResult> results;
    int requiredTerms = (mode == AND_MODE) ? static_cast<int>(allPostings.size()) : 1;

    for (auto& [docId, result] : docScores) {
        if (result.matchedTerms >= requiredTerms) {
            results.push_back(result);
        }
    }

    // Sort by score descending
    std::sort(results.begin(), results.end(),
              [](const QueryResult& a, const QueryResult& b) {
                  if (std::abs(a.totalScore - b.totalScore) > 0.001) {
                      return a.totalScore > b.totalScore;
                  }
                  return a.matchedTerms > b.matchedTerms;
              });

    return results;
}

// ---------------------- Single-Word Query Processing ----------------------

std::vector<DocPosting> processSingleWordQuery(
    const fs::path& backendDir,
    const json& config,
    const std::string& word,
    int& lemmaIdOut,
    int& dfOut,
    int& barrelIdOut
) {
    if (!getLemmaIdForWord(word, lemmaIdOut)) {
        return {};
    }

    std::vector<DocPosting> postings;
    if (!findPostings(backendDir, config, lemmaIdOut, postings, dfOut, barrelIdOut)) {
        return {};
    }

    // Calculate TF-IDF scores
    for (auto& p : postings) {
        p.score = calculateTFIDF(p.tf, dfOut);
    }

    // Sort by TF-IDF score
    std::sort(postings.begin(), postings.end(),
              [](const DocPosting& a, const DocPosting& b) {
                  if (std::abs(a.score - b.score) > 0.001) return a.score > b.score;
                  if (a.tf != b.tf) return a.tf > b.tf;
                  return a.docId < b.docId;
              });

    return postings;
}

// ---------------------- Main ----------------------

// Helper to find backend directory from executable path
fs::path findBackendDir(const char* argv0) {
    // Try to get the executable's directory
    fs::path exePath;

    try {
        // Try using /proc/self/exe on Linux
        if (fs::exists("/proc/self/exe")) {
            exePath = fs::canonical("/proc/self/exe").parent_path();
        } else {
            // Fallback: use argv[0]
            exePath = fs::canonical(argv0).parent_path();
        }
    } catch (...) {
        // Last resort: current directory
        exePath = fs::current_path();
    }

    // Navigate from build/ to backend/
    // Expected: backend/cpp/build/search -> backend/
    fs::path backendDir = exePath.parent_path().parent_path();

    // Verify config.json exists
    if (fs::exists(backendDir / "config.json")) {
        return backendDir;
    }

    // Try current directory approach
    backendDir = fs::current_path().parent_path().parent_path();
    if (fs::exists(backendDir / "config.json")) {
        return backendDir;
    }

    // Try from current directory directly
    backendDir = fs::current_path();
    if (fs::exists(backendDir / "config.json")) {
        return backendDir;
    }

    throw std::runtime_error("Cannot find config.json. Run from backend/cpp/build/ or set correct path.");
}

int main(int argc, char* argv[]) {
    try {
        auto totalStart = high_resolution_clock::now();

        // Parse arguments
        std::string queryString;
        QueryMode mode = AND_MODE;

        if (argc >= 2) {
            queryString = argv[1];

            for (int i = 2; i < argc; i++) {
                std::string arg = argv[i];
                if (arg == "--or" || arg == "-o") {
                    mode = OR_MODE;
                } else if (arg == "--and" || arg == "-a") {
                    mode = AND_MODE;
                }
            }
        } else {
            std::cout << "Enter query (single or multi-word): ";
            if (!std::getline(std::cin, queryString)) {
                std::cerr << "No query provided.\n";
                return 1;
            }
        }

        if (queryString.empty()) {
            std::cerr << "Empty query.\n";
            return 1;
        }

        // Find backend directory (works from any location)
        fs::path backendDir = findBackendDir(argv[0]);
        json config = loadConfig(backendDir);

        initializeCache(backendDir, config);

        // Tokenize query
        std::vector<std::string> queryWords = tokenize(queryString);

        if (queryWords.empty()) {
            std::cerr << "No valid query words.\n";
            return 1;
        }

        auto searchStart = high_resolution_clock::now();

        // Process query
        const std::size_t TOP_K = 20;

        if (queryWords.size() == 1) {
            // Single-word query
            std::string word = queryWords[0];
            int lemmaId, df, barrelId;

            std::cout << "Query: '" << word << "' (single-word mode)\n" << std::endl;

            auto results = processSingleWordQuery(backendDir, config, word, lemmaId, df, barrelId);

            if (results.empty()) {
                std::cout << "No results found for '" << word << "'.\n";
                return 0;
            }

            std::cout << "Lemma ID: " << lemmaId << std::endl;
            std::cout << "Barrel: " << barrelId << std::endl;
            std::cout << "Document frequency (df): " << df << std::endl;

            auto searchEnd = high_resolution_clock::now();
            auto searchTime = duration_cast<milliseconds>(searchEnd - searchStart).count();

            std::cout << "\nTop " << std::min(TOP_K, results.size())
                      << " results for '" << word << "' (in " << searchTime << "ms):\n" << std::endl;

            for (size_t i = 0; i < std::min(TOP_K, results.size()); i++) {
                std::cout << (i + 1) << ". DocID: " << results[i].docId
                          << " | tf: " << results[i].tf
                          << " | TF-IDF: " << results[i].score << std::endl;
            }

        } else {
            // Multi-word query
            std::cout << "Query: '" << queryString << "' ("
                      << (mode == AND_MODE ? "AND" : "OR") << " mode)\n" << std::endl;

            std::cout << "Processing " << queryWords.size() << " words:" << std::endl;

            std::vector<int> lemmaIds, dfs;
            auto results = processMultiWordQuery(backendDir, config, queryWords, mode, lemmaIds, dfs);

            auto searchEnd = high_resolution_clock::now();
            auto searchTime = duration_cast<milliseconds>(searchEnd - searchStart).count();

            if (results.empty()) {
                std::cout << "\nNo documents found matching "
                          << (mode == AND_MODE ? "ALL" : "ANY") << " query terms.\n";
                return 0;
            }

            std::cout << "\nFound " << results.size() << " matching documents" << std::endl;
            std::cout << "\nTop " << std::min(TOP_K, results.size())
                      << " results (in " << searchTime << "ms):\n" << std::endl;

            for (size_t i = 0; i < std::min(TOP_K, results.size()); i++) {
                const auto& r = results[i];
                std::cout << (i + 1) << ". DocID: " << r.docId
                          << " | Score: " << r.totalScore
                          << " | Matched: " << r.matchedTerms << "/" << queryWords.size();

                // Show TF for each term
                std::cout << " | TFs: [";
                for (size_t j = 0; j < r.termFreqs.size(); j++) {
                    if (j > 0) std::cout << ",";
                    std::cout << r.termFreqs[j];
                }
                std::cout << "]" << std::endl;
            }
        }

        auto totalEnd = high_resolution_clock::now();
        auto totalTime = duration_cast<milliseconds>(totalEnd - totalStart).count();

        std::cout << "\n[Total time: " << totalTime << "ms]" << std::endl;

    } catch (const std::exception& e) {
        std::cerr << "Fatal error: " << e.what() << "\n";
        return 1;
    }

    return 0;
}
