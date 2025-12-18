/*
 * MiniGoogle Semantic Search Engine
 *
 * Features:
 * - Semantic search using GloVe word embeddings (query expansion)
 * - Fast prefix-based autocomplete with document frequency ranking
 * - PageRank-style document authority scores
 * - TF-IDF + semantic similarity + PageRank combined ranking
 * - Binary barrel format for O(1) seeks
 * - Performance: single word < 500ms, 5-word < 1.5s
 *
 * Usage:
 *   ./search_semantic "query"                    # Semantic search (AND mode)
 *   ./search_semantic "query" --or               # OR mode
 *   ./search_semantic --autocomplete "prefix"    # Get suggestions (3-5)
 *   ./search_semantic --similar "word"           # Find similar words
 */

#include <iostream>
#include <fstream>
#include <sstream>
#include <string>
#include <vector>
#include <array>
#include <algorithm>
#include <filesystem>
#include <unordered_map>
#include <unordered_set>
#include <cstring>
#include <cmath>
#include <chrono>
#include <cctype>
#include <queue>
#include <functional>

#include "config.hpp"

namespace fs = std::filesystem;
using json = nlohmann::json;
using namespace std::chrono;

// ===================== Configuration =====================

const int EMBEDDING_DIM = 50;           // GloVe 50d
const int DOC_ID_SIZE = 20;
const int TOTAL_DOCS = 59000;
const int TOP_SIMILAR_WORDS = 3;        // Expand query with top-k similar words
const int AUTOCOMPLETE_SUGGESTIONS = 5;
const float SEMANTIC_WEIGHT = 0.3f;     // Weight for semantic similarity in ranking
const float TFIDF_WEIGHT = 0.5f;        // Weight for TF-IDF
const float PAGERANK_WEIGHT = 0.2f;     // Weight for PageRank

// ===================== Data Structures =====================

struct DocPosting {
    std::string docId;
    int tf;
    double score;
};

struct IndexEntry {
    int64_t offset;
    int64_t length;
};

struct SimilarWord {
    std::string word;
    float similarity;
    int lemmaId;
};

struct AutocompleteSuggestion {
    std::string word;
    int df;
};

// ===================== Global Cache =====================

struct SearchCache {
    // Lexicon
    std::unordered_map<std::string, int> wordToWordId;
    std::unordered_map<int, int> wordIdToLemmaId;

    // Barrel lookup
    std::unordered_map<int, int> barrelLookup;
    std::unordered_map<int, std::unordered_map<int, IndexEntry>> barrelIndices;

    // Word embeddings (only if available)
    std::vector<std::array<float, EMBEDDING_DIM>> embeddings;
    std::unordered_map<std::string, int> wordToEmbIdx;
    bool embeddingsLoaded = false;

    // Autocomplete index (prefix -> list of {word, df})
    std::unordered_map<std::string, std::vector<AutocompleteSuggestion>> autocompleteIndex;
    bool autocompleteLoaded = false;

    // Document PageRank scores
    std::unordered_map<std::string, float> docScores;

    bool initialized = false;
    fs::path backendDir;
};

static SearchCache g_cache;

// ===================== Utility Functions =====================

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

// ===================== Embeddings Functions =====================

void loadEmbeddings(const fs::path& embeddingsDir) {
    fs::path binPath = embeddingsDir / "embeddings.bin";
    fs::path vocabPath = embeddingsDir / "vocab.json";

    if (!fs::exists(binPath) || !fs::exists(vocabPath)) {
        std::cout << "[Embeddings not found - semantic expansion disabled]" << std::endl;
        return;
    }

    auto start = high_resolution_clock::now();

    // Load vocabulary
    std::ifstream vocabFile(vocabPath);
    json vocab;
    vocabFile >> vocab;
    vocabFile.close();

    for (auto& [word, idx] : vocab.items()) {
        g_cache.wordToEmbIdx[word] = idx.get<int>();
    }

    // Load binary embeddings
    std::ifstream binFile(binPath, std::ios::binary);
    if (!binFile.is_open()) {
        std::cerr << "Cannot open embeddings.bin" << std::endl;
        return;
    }

    uint32_t numWords, dim;
    binFile.read(reinterpret_cast<char*>(&numWords), sizeof(numWords));
    binFile.read(reinterpret_cast<char*>(&dim), sizeof(dim));

    if (static_cast<int>(dim) != EMBEDDING_DIM) {
        std::cerr << "Embedding dimension mismatch: expected " << EMBEDDING_DIM
                  << ", got " << dim << std::endl;
        return;
    }

    g_cache.embeddings.resize(numWords);

    for (uint32_t i = 0; i < numWords; i++) {
        binFile.read(reinterpret_cast<char*>(g_cache.embeddings[i].data()),
                     EMBEDDING_DIM * sizeof(float));
    }

    binFile.close();
    g_cache.embeddingsLoaded = true;

    auto end = high_resolution_clock::now();
    auto ms = duration_cast<milliseconds>(end - start).count();
    std::cout << "[Loaded " << numWords << " embeddings in " << ms << "ms]" << std::endl;
}

float cosineSimilarity(const std::array<float, EMBEDDING_DIM>& a,
                       const std::array<float, EMBEDDING_DIM>& b) {
    float dot = 0.0f;
    for (int i = 0; i < EMBEDDING_DIM; i++) {
        dot += a[i] * b[i];
    }
    return dot;
}

std::vector<SimilarWord> findSimilarWords(const std::string& word, int topK = TOP_SIMILAR_WORDS) {
    std::vector<SimilarWord> similar;

    if (!g_cache.embeddingsLoaded) {
        return similar;
    }

    auto it = g_cache.wordToEmbIdx.find(word);
    if (it == g_cache.wordToEmbIdx.end()) {
        return similar;
    }

    int wordIdx = it->second;
    const auto& wordVec = g_cache.embeddings[wordIdx];

    using WordSim = std::pair<float, std::string>;
    std::priority_queue<WordSim, std::vector<WordSim>, std::greater<WordSim>> pq;

    for (const auto& [w, idx] : g_cache.wordToEmbIdx) {
        if (w == word) continue;

        float sim = cosineSimilarity(wordVec, g_cache.embeddings[idx]);

        if (pq.size() < static_cast<size_t>(topK)) {
            pq.push({sim, w});
        } else if (sim > pq.top().first) {
            pq.pop();
            pq.push({sim, w});
        }
    }

    while (!pq.empty()) {
        auto [sim, w] = pq.top();
        pq.pop();

        SimilarWord sw;
        sw.word = w;
        sw.similarity = sim;

        auto wordIt = g_cache.wordToWordId.find(w);
        if (wordIt != g_cache.wordToWordId.end()) {
            int wordId = wordIt->second;
            auto lemmaIt = g_cache.wordIdToLemmaId.find(wordId);
            sw.lemmaId = (lemmaIt != g_cache.wordIdToLemmaId.end()) ? lemmaIt->second : -1;
        } else {
            sw.lemmaId = -1;
        }

        similar.push_back(sw);
    }

    std::reverse(similar.begin(), similar.end());
    return similar;
}

// ===================== Autocomplete Functions =====================

void loadAutocomplete(const fs::path& embeddingsDir) {
    fs::path autoPath = embeddingsDir / "autocomplete.json";

    if (!fs::exists(autoPath)) {
        // Try loading from trie.txt as fallback
        fs::path triePath = embeddingsDir / "trie.txt";
        if (fs::exists(triePath)) {
            auto start = high_resolution_clock::now();

            std::ifstream trieFile(triePath);
            std::string line;
            std::unordered_map<std::string, std::vector<AutocompleteSuggestion>> prefixIndex;

            while (std::getline(trieFile, line)) {
                size_t sep = line.find('|');
                if (sep != std::string::npos) {
                    std::string word = line.substr(0, sep);
                    int df = std::stoi(line.substr(sep + 1));

                    if (word.length() >= 2) {
                        std::string prefix = word.substr(0, 2);
                        prefixIndex[prefix].push_back({word, df});
                    }
                }
            }
            trieFile.close();

            // Sort each prefix group by df descending and limit
            for (auto& [prefix, suggestions] : prefixIndex) {
                std::sort(suggestions.begin(), suggestions.end(),
                    [](const AutocompleteSuggestion& a, const AutocompleteSuggestion& b) {
                        return a.df > b.df;
                    });
                if (suggestions.size() > 50) {
                    suggestions.resize(50);
                }
            }

            g_cache.autocompleteIndex = std::move(prefixIndex);
            g_cache.autocompleteLoaded = true;

            auto end = high_resolution_clock::now();
            auto ms = duration_cast<milliseconds>(end - start).count();
            std::cout << "[Loaded autocomplete from trie.txt in " << ms << "ms]" << std::endl;
        } else {
            std::cout << "[Autocomplete index not found]" << std::endl;
        }
        return;
    }

    auto start = high_resolution_clock::now();

    std::ifstream autoFile(autoPath);
    json autoJson;
    autoFile >> autoJson;
    autoFile.close();

    for (auto& [prefix, entries] : autoJson.items()) {
        std::vector<AutocompleteSuggestion> suggestions;
        for (const auto& entry : entries) {
            AutocompleteSuggestion s;
            s.word = entry["w"].get<std::string>();
            s.df = entry["d"].get<int>();
            suggestions.push_back(s);
        }
        g_cache.autocompleteIndex[prefix] = std::move(suggestions);
    }

    g_cache.autocompleteLoaded = true;

    auto end = high_resolution_clock::now();
    auto ms = duration_cast<milliseconds>(end - start).count();
    std::cout << "[Loaded autocomplete index in " << ms << "ms]" << std::endl;
}

std::vector<AutocompleteSuggestion> getAutocompleteSuggestions(
    const std::string& prefix,
    int maxSuggestions = AUTOCOMPLETE_SUGGESTIONS
) {
    std::vector<AutocompleteSuggestion> suggestions;

    if (!g_cache.autocompleteLoaded || prefix.empty()) {
        return suggestions;
    }

    std::string lowerPrefix = toLower(prefix);

    // Try the most specific prefix bucket first (3-char), then fall back to 2-char
    std::string bucket;
    if (lowerPrefix.length() >= 3) {
        bucket = lowerPrefix.substr(0, 3);
        auto it = g_cache.autocompleteIndex.find(bucket);
        if (it != g_cache.autocompleteIndex.end()) {
            for (const auto& s : it->second) {
                if (s.word.find(lowerPrefix) == 0) {
                    suggestions.push_back(s);
                    if (static_cast<int>(suggestions.size()) >= maxSuggestions) {
                        return suggestions;
                    }
                }
            }
        }
    }

    // Fall back to 2-char prefix bucket
    if (suggestions.size() < static_cast<size_t>(maxSuggestions) && lowerPrefix.length() >= 2) {
        bucket = lowerPrefix.substr(0, 2);
        auto it = g_cache.autocompleteIndex.find(bucket);
        if (it != g_cache.autocompleteIndex.end()) {
            for (const auto& s : it->second) {
                if (s.word.find(lowerPrefix) == 0) {
                    // Avoid duplicates
                    bool found = false;
                    for (const auto& existing : suggestions) {
                        if (existing.word == s.word) {
                            found = true;
                            break;
                        }
                    }
                    if (!found) {
                        suggestions.push_back(s);
                        if (static_cast<int>(suggestions.size()) >= maxSuggestions) {
                            break;
                        }
                    }
                }
            }
        }
    }

    return suggestions;
}

// ===================== PageRank Functions =====================

void loadDocScores(const fs::path& embeddingsDir) {
    fs::path scoresPath = embeddingsDir / "doc_scores.json";

    if (!fs::exists(scoresPath)) {
        std::cout << "[Document scores not found - using default]" << std::endl;
        return;
    }

    auto start = high_resolution_clock::now();

    std::ifstream scoresFile(scoresPath);
    json scores;
    scoresFile >> scores;
    scoresFile.close();

    for (auto& [docId, score] : scores.items()) {
        g_cache.docScores[docId] = score.get<float>();
    }

    auto end = high_resolution_clock::now();
    auto ms = duration_cast<milliseconds>(end - start).count();
    std::cout << "[Loaded " << g_cache.docScores.size() << " doc scores in " << ms << "ms]" << std::endl;
}

float getDocScore(const std::string& docId) {
    auto it = g_cache.docScores.find(docId);
    if (it != g_cache.docScores.end()) {
        return it->second;
    }
    return 0.5f;
}

// ===================== Path Resolution =====================

fs::path findBackendDir(const char* argv0) {
    fs::path exePath;

    try {
        if (fs::exists("/proc/self/exe")) {
            exePath = fs::canonical("/proc/self/exe").parent_path();
        } else {
            exePath = fs::canonical(argv0).parent_path();
        }
    } catch (...) {
        exePath = fs::current_path();
    }

    fs::path backendDir = exePath.parent_path().parent_path();
    if (fs::exists(backendDir / "config.json")) {
        return backendDir;
    }

    backendDir = fs::current_path().parent_path().parent_path();
    if (fs::exists(backendDir / "config.json")) {
        return backendDir;
    }

    backendDir = fs::current_path();
    if (fs::exists(backendDir / "config.json")) {
        return backendDir;
    }

    throw std::runtime_error("Cannot find config.json");
}

// ===================== Binary Lexicon Loading =====================

bool loadBinaryLexicon(const fs::path& binPath) {
    if (!fs::exists(binPath)) {
        return false;
    }

    std::ifstream binFile(binPath, std::ios::binary);
    if (!binFile.is_open()) {
        return false;
    }

    // Read header
    uint32_t numWords;
    binFile.read(reinterpret_cast<char*>(&numWords), sizeof(numWords));

    // Read words and build lookup
    std::vector<std::pair<std::string, int>> words;
    words.reserve(numWords);

    for (uint32_t i = 0; i < numWords; i++) {
        uint16_t wordLen;
        binFile.read(reinterpret_cast<char*>(&wordLen), sizeof(wordLen));

        std::string word(wordLen, '\0');
        binFile.read(&word[0], wordLen);

        words.push_back({word, 0});  // lemma_id to be filled
    }

    // Read lemma IDs
    for (uint32_t i = 0; i < numWords; i++) {
        int32_t lemmaId;
        binFile.read(reinterpret_cast<char*>(&lemmaId), sizeof(lemmaId));

        words[i].second = lemmaId;
        g_cache.wordToWordId[words[i].first] = static_cast<int>(i);
        g_cache.wordIdToLemmaId[static_cast<int>(i)] = lemmaId;
    }

    binFile.close();
    return true;
}

// ===================== Cache Initialization =====================

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
    if (!loadBinaryLexicon(binLexPath)) {
        // Fallback to JSON lexicon
        std::cout << "[Binary lexicon not found, loading JSON...]" << std::endl;
        std::ifstream lexFile(lexiconPath);
        if (!lexFile.is_open()) {
            throw std::runtime_error("Cannot open lexicon at " + lexiconPath.string());
        }
        json lexicon;
        lexFile >> lexicon;
        lexFile.close();

        if (lexicon.contains("wordID")) {
            for (auto& [word, id] : lexicon["wordID"].items()) {
                g_cache.wordToWordId[word] = id.get<int>();
            }
        }

        if (lexicon.contains("wordToLemmaID")) {
            for (auto& [wordIdStr, lemmaId] : lexicon["wordToLemmaID"].items()) {
                g_cache.wordIdToLemmaId[std::stoi(wordIdStr)] = lemmaId.get<int>();
            }
        }
    }

    // Load barrel lookup
    std::ifstream lookupFile(lookupPath);
    if (!lookupFile.is_open()) {
        throw std::runtime_error("Cannot open barrel_lookup.json");
    }
    json lookupJson;
    lookupFile >> lookupJson;
    lookupFile.close();

    for (auto& [key, val] : lookupJson.items()) {
        g_cache.barrelLookup[std::stoi(key)] = val.get<int>();
    }

    // Load binary barrel indices (0-9 and new_docs)
    std::vector<std::pair<int, std::string>> barrelInfos;
    for (int i = 0; i < 10; i++) {
        barrelInfos.push_back({i, std::to_string(i)});
    }
    barrelInfos.push_back({10, "new_docs"});  // Add new_docs barrel

    for (const auto& [barrelId, barrelName] : barrelInfos) {
        fs::path idxPath = binaryBarrelsDir / ("barrel_" + barrelName + ".idx");

        if (!fs::exists(idxPath)) continue;

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

    // Load embeddings for semantic search (optional)
    loadEmbeddings(embeddingsDir);

    // Load autocomplete index
    loadAutocomplete(embeddingsDir);

    // Load document scores for PageRank (optional)
    loadDocScores(embeddingsDir);

    g_cache.initialized = true;

    auto endTime = high_resolution_clock::now();
    auto duration = duration_cast<milliseconds>(endTime - startTime).count();
    std::cout << "[Cache initialized in " << duration << "ms]\n" << std::endl;
}

// ===================== Lexicon Lookup =====================

bool getLemmaIdForWord(const std::string& word, int& lemmaIdOut) {
    auto it = g_cache.wordToWordId.find(word);
    if (it == g_cache.wordToWordId.end()) {
        return false;
    }

    int wordId = it->second;
    auto lemmaIt = g_cache.wordIdToLemmaId.find(wordId);
    if (lemmaIt != g_cache.wordIdToLemmaId.end()) {
        lemmaIdOut = lemmaIt->second;
    } else {
        lemmaIdOut = wordId;  // Use word ID as lemma ID if no mapping
    }

    return true;
}

// ===================== Binary Barrel Search =====================

bool findPostingsBinary(
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

    auto barrelIt = g_cache.barrelIndices.find(barrelIdOut);
    if (barrelIt == g_cache.barrelIndices.end()) {
        return false;
    }

    auto& barrelIdx = barrelIt->second;
    auto offsetIt = barrelIdx.find(lemmaId);
    if (offsetIt == barrelIdx.end()) {
        return false;
    }

    IndexEntry entry = offsetIt->second;

    fs::path indexesDir = g_cache.backendDir / config["indexes_dir"].get<std::string>();
    // Handle barrel 10 (new_docs) naming
    std::string barrelFileName = (barrelIdOut == 10) ? "barrel_new_docs.bin" : ("barrel_" + std::to_string(barrelIdOut) + ".bin");
    fs::path binPath = indexesDir / "barrels_binary" / barrelFileName;

    std::ifstream binFile(binPath, std::ios::binary);
    if (!binFile.is_open()) {
        return false;
    }

    binFile.seekg(entry.offset);

    int32_t readLemmaId, df, numDocs;
    binFile.read(reinterpret_cast<char*>(&readLemmaId), sizeof(readLemmaId));
    binFile.read(reinterpret_cast<char*>(&df), sizeof(df));
    binFile.read(reinterpret_cast<char*>(&numDocs), sizeof(numDocs));

    dfOut = df;

    postingsOut.clear();
    postingsOut.reserve(numDocs);

    for (int i = 0; i < numDocs; i++) {
        char docIdBuf[DOC_ID_SIZE];
        int32_t tf;

        binFile.read(docIdBuf, DOC_ID_SIZE);
        binFile.read(reinterpret_cast<char*>(&tf), sizeof(tf));

        DocPosting dp;
        dp.docId = std::string(docIdBuf);
        // Trim null characters from doc ID
        size_t nullPos = dp.docId.find('\0');
        if (nullPos != std::string::npos) {
            dp.docId = dp.docId.substr(0, nullPos);
        }
        dp.tf = tf;
        dp.score = 0.0;

        postingsOut.push_back(dp);
    }

    binFile.close();

    // ALSO check barrel 10 (new_docs) for newly indexed documents
    // This ensures newly uploaded documents are immediately searchable
    if (barrelIdOut != 10) {
        auto& newDocsIdx = g_cache.barrelIndices[10];
        auto newDocsIt = newDocsIdx.find(lemmaId);
        if (newDocsIt != newDocsIdx.end()) {
            IndexEntry newEntry = newDocsIt->second;

            fs::path newDocsBinPath = indexesDir / "barrels_binary" / "barrel_new_docs.bin";
            std::ifstream newDocsFile(newDocsBinPath, std::ios::binary);
            if (newDocsFile.is_open()) {
                newDocsFile.seekg(newEntry.offset);

                int32_t newReadLemmaId, newDf, newNumDocs;
                newDocsFile.read(reinterpret_cast<char*>(&newReadLemmaId), sizeof(newReadLemmaId));
                newDocsFile.read(reinterpret_cast<char*>(&newDf), sizeof(newDf));
                newDocsFile.read(reinterpret_cast<char*>(&newNumDocs), sizeof(newNumDocs));

                // Collect existing doc IDs
                std::unordered_set<std::string> existingDocs;
                for (const auto& p : postingsOut) {
                    existingDocs.insert(p.docId);
                }

                // Read and merge new postings
                for (int i = 0; i < newNumDocs; i++) {
                    char docIdBuf[DOC_ID_SIZE];
                    int32_t tf;

                    newDocsFile.read(docIdBuf, DOC_ID_SIZE);
                    newDocsFile.read(reinterpret_cast<char*>(&tf), sizeof(tf));

                    std::string docId(docIdBuf);
                    size_t nullPos = docId.find('\0');
                    if (nullPos != std::string::npos) {
                        docId = docId.substr(0, nullPos);
                    }

                    if (existingDocs.find(docId) == existingDocs.end()) {
                        DocPosting dp;
                        dp.docId = docId;
                        dp.tf = tf;
                        dp.score = 0.0;
                        postingsOut.push_back(dp);
                        dfOut++;
                    }
                }

                newDocsFile.close();
            }
        }
    }

    return true;
}

// ===================== TF-IDF Scoring =====================

double calculateTFIDF(int tf, int df, int totalDocs = TOTAL_DOCS) {
    if (tf == 0 || df == 0) return 0.0;

    double tfScore = 1.0 + std::log10(static_cast<double>(tf));
    double idf = std::log10(static_cast<double>(totalDocs) / static_cast<double>(df));

    return tfScore * idf;
}

// ===================== Semantic Search =====================

struct ExpandedTerm {
    std::string word;
    int lemmaId;
    float weight;
};

std::vector<ExpandedTerm> expandQuery(const std::vector<std::string>& queryWords) {
    std::vector<ExpandedTerm> expandedTerms;
    std::unordered_set<int> seenLemmas;

    for (const auto& word : queryWords) {
        int lemmaId;
        if (getLemmaIdForWord(word, lemmaId)) {
            if (seenLemmas.find(lemmaId) == seenLemmas.end()) {
                expandedTerms.push_back({word, lemmaId, 1.0f});
                seenLemmas.insert(lemmaId);
            }
        }

        // Find similar words for semantic expansion (only if embeddings loaded)
        if (g_cache.embeddingsLoaded) {
            auto similar = findSimilarWords(word, TOP_SIMILAR_WORDS);

            for (const auto& sim : similar) {
                if (sim.lemmaId >= 0 && sim.similarity > 0.5f) {
                    if (seenLemmas.find(sim.lemmaId) == seenLemmas.end()) {
                        expandedTerms.push_back({sim.word, sim.lemmaId, sim.similarity * 0.5f});
                        seenLemmas.insert(sim.lemmaId);
                    }
                }
            }
        }
    }

    return expandedTerms;
}

enum QueryMode { AND_MODE, OR_MODE };

struct SearchResult {
    std::string docId;
    double totalScore;
    double tfidfScore;
    double semanticScore;
    double pagerankScore;
    int matchedTerms;
    int totalTerms;
};

std::vector<SearchResult> semanticSearch(
    const json& config,
    const std::vector<std::string>& queryWords,
    QueryMode mode,
    bool verbose = true
) {
    auto expandedTerms = expandQuery(queryWords);

    if (verbose) {
        std::cout << "Query expansion (" << expandedTerms.size() << " terms):" << std::endl;
        for (const auto& term : expandedTerms) {
            std::cout << "  " << term.word << " (lemma=" << term.lemmaId
                      << ", weight=" << term.weight << ")" << std::endl;
        }
    }

    std::unordered_map<std::string, SearchResult> docResults;
    int originalTermCount = static_cast<int>(queryWords.size());

    for (const auto& term : expandedTerms) {
        std::vector<DocPosting> postings;
        int df, barrelId;

        if (!findPostingsBinary(config, term.lemmaId, postings, df, barrelId)) {
            continue;
        }

        for (const auto& posting : postings) {
            double tfidf = calculateTFIDF(posting.tf, df);

            auto& result = docResults[posting.docId];
            if (result.docId.empty()) {
                result.docId = posting.docId;
                result.tfidfScore = 0.0;
                result.semanticScore = 0.0;
                result.pagerankScore = getDocScore(posting.docId);
                result.matchedTerms = 0;
                result.totalTerms = originalTermCount;
            }

            result.tfidfScore += tfidf * term.weight;

            if (term.weight < 1.0f) {
                result.semanticScore += tfidf * term.weight;
            }

            if (term.weight >= 1.0f) {
                result.matchedTerms++;
            }
        }
    }

    std::vector<SearchResult> results;
    int requiredTerms = (mode == AND_MODE) ? originalTermCount : 1;

    for (auto& [docId, result] : docResults) {
        if (result.matchedTerms >= requiredTerms) {
            result.totalScore = TFIDF_WEIGHT * result.tfidfScore +
                               SEMANTIC_WEIGHT * result.semanticScore +
                               PAGERANK_WEIGHT * result.pagerankScore;

            results.push_back(result);
        }
    }

    std::sort(results.begin(), results.end(),
              [](const SearchResult& a, const SearchResult& b) {
                  return a.totalScore > b.totalScore;
              });

    return results;
}

// ===================== Main =====================

void printUsage(const char* progName) {
    std::cout << "Usage:\n";
    std::cout << "  " << progName << " \"query\"                    # Semantic search\n";
    std::cout << "  " << progName << " \"query\" --or               # OR mode\n";
    std::cout << "  " << progName << " --autocomplete \"prefix\"    # Get suggestions\n";
    std::cout << "  " << progName << " --similar \"word\"           # Find similar words\n";
}

int main(int argc, char* argv[]) {
    try {
        auto totalStart = high_resolution_clock::now();

        if (argc < 2) {
            printUsage(argv[0]);
            return 1;
        }

        std::string queryString;
        QueryMode mode = AND_MODE;
        bool autocompleteMode = false;
        bool similarMode = false;

        for (int i = 1; i < argc; i++) {
            std::string arg = argv[i];

            if (arg == "--or" || arg == "-o") {
                mode = OR_MODE;
            } else if (arg == "--and" || arg == "-a") {
                mode = AND_MODE;
            } else if (arg == "--autocomplete" || arg == "-ac") {
                autocompleteMode = true;
                if (i + 1 < argc) {
                    queryString = argv[++i];
                }
            } else if (arg == "--similar" || arg == "-s") {
                similarMode = true;
                if (i + 1 < argc) {
                    queryString = argv[++i];
                }
            } else if (arg == "--help" || arg == "-h") {
                printUsage(argv[0]);
                return 0;
            } else if (queryString.empty()) {
                queryString = arg;
            }
        }

        if (queryString.empty()) {
            std::cerr << "No query provided.\n";
            return 1;
        }

        fs::path backendDir = findBackendDir(argv[0]);
        json config = loadConfig(backendDir);

        initializeCache(backendDir, config);

        auto searchStart = high_resolution_clock::now();

        // Handle autocomplete mode
        if (autocompleteMode) {
            std::cout << "Autocomplete suggestions for '" << queryString << "':\n" << std::endl;

            auto suggestions = getAutocompleteSuggestions(queryString);

            if (suggestions.empty()) {
                std::cout << "No suggestions found.\n";
            } else {
                for (size_t i = 0; i < suggestions.size(); i++) {
                    std::cout << (i + 1) << ". " << suggestions[i].word
                              << " (df: " << suggestions[i].df << ")\n";
                }
            }

            auto searchEnd = high_resolution_clock::now();
            auto searchTime = duration_cast<milliseconds>(searchEnd - searchStart).count();
            std::cout << "\n[Autocomplete time: " << searchTime << "ms]\n";

            return 0;
        }

        // Handle similar words mode
        if (similarMode) {
            std::cout << "Words similar to '" << queryString << "':\n" << std::endl;

            auto similar = findSimilarWords(queryString, 10);

            if (similar.empty()) {
                if (g_cache.embeddingsLoaded) {
                    std::cout << "No similar words found (word not in embeddings).\n";
                } else {
                    std::cout << "Similar words unavailable (embeddings not loaded).\n";
                    std::cout << "Run: python backend/py/embeddings_setup.py\n";
                }
            } else {
                for (size_t i = 0; i < similar.size(); i++) {
                    std::cout << (i + 1) << ". " << similar[i].word
                              << " (similarity: " << similar[i].similarity << ")\n";
                }
            }

            auto searchEnd = high_resolution_clock::now();
            auto searchTime = duration_cast<milliseconds>(searchEnd - searchStart).count();
            std::cout << "\n[Similar words time: " << searchTime << "ms]\n";

            return 0;
        }

        // Semantic search
        std::vector<std::string> queryWords = tokenize(queryString);

        if (queryWords.empty()) {
            std::cerr << "No valid query words.\n";
            return 1;
        }

        std::cout << "Semantic Search: '" << queryString << "' ("
                  << (mode == AND_MODE ? "AND" : "OR") << " mode)\n" << std::endl;

        auto results = semanticSearch(config, queryWords, mode);

        auto searchEnd = high_resolution_clock::now();
        auto searchTime = duration_cast<milliseconds>(searchEnd - searchStart).count();

        if (results.empty()) {
            std::cout << "\nNo documents found.\n";
            return 0;
        }

        std::cout << "\nFound " << results.size() << " documents\n";
        std::cout << "\nTop 20 results (in " << searchTime << "ms):\n" << std::endl;

        const size_t TOP_K = 20;
        for (size_t i = 0; i < std::min(TOP_K, results.size()); i++) {
            const auto& r = results[i];
            std::cout << (i + 1) << ". DocID: " << r.docId
                      << " | Score: " << r.totalScore
                      << " | TF-IDF: " << r.tfidfScore
                      << " | PageRank: " << r.pagerankScore
                      << " | Matched: " << r.matchedTerms << "/" << r.totalTerms
                      << std::endl;
        }

        auto totalEnd = high_resolution_clock::now();
        auto totalTime = duration_cast<milliseconds>(totalEnd - totalStart).count();

        std::cout << "\n[Total time: " << totalTime << "ms]" << std::endl;

    } catch (const std::exception& e) {
        std::cerr << "Error: " << e.what() << "\n";
        return 1;
    }

    return 0;
}
