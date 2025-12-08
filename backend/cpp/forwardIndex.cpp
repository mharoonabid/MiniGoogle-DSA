#include "config.hpp"

#include <iostream>
#include <fstream>
#include <string>
#include <vector>
#include <unordered_map>
#include <sstream>
#include <algorithm>
#include <cctype>
#include <climits>

using namespace std;


struct Document {
    string doc_id;
    string title;
    string abstract;
    vector<int> title_lemmas;
    vector<int> abstract_lemmas;
    vector<int> body_lemmas;
    int total_terms;

    Document() : total_terms(0) {}
};

class Lexicon {
private:
    unordered_map<string, int> wordToID;
    unordered_map<int, int> wordIDToLemmaID;

public:
    bool loadFromFile(const string& filename) {
        try {
            cout << "Opening file: " << filename << endl;

            ifstream file(filename);
            if (!file.is_open()) {
                cerr << "Error: Could not open " << filename << endl;
                return false;
            }

            // Check if file is empty
            file.seekg(0, ios::end);
            size_t fileSize = file.tellg();
            file.seekg(0, ios::beg);

            cout << "File size: " << fileSize << " bytes" << endl;

            if (fileSize == 0) {
                cerr << "Error: File is empty!" << endl;
                return false;
            }

            cout << "Parsing JSON (this may take a moment for large files)..." << endl;
            json j = json::parse(file);

            cout << "JSON parsed successfully!" << endl;

            // Load wordID
            if (j.contains("wordID")) {
                cout << "Loading word IDs..." << endl;
                for (auto& [word, id] : j["wordID"].items()) {
                    wordToID[word] = id.get<int>();
                }
                cout << "Loaded " << wordToID.size() << " word IDs" << endl;
            }

            // Load wordToLemmaID
            if (j.contains("wordToLemmaID")) {
                cout << "Loading lemma mappings..." << endl;
                for (auto& [wordIdStr, lemmaId] : j["wordToLemmaID"].items()) {
                    wordIDToLemmaID[stoi(wordIdStr)] = lemmaId.get<int>();
                }
                cout << "Loaded " << wordIDToLemmaID.size() << " lemma mappings" << endl;
            }

            cout << "Lexicon loaded successfully!" << endl;
            return true;
        } catch (json::parse_error& e) {
            cerr << "JSON Parse Error: " << e.what() << endl;
            cerr << "Error at byte position: " << e.byte << endl;
            return false;
        } catch (exception& e) {
            cerr << "Error loading lexicon: " << e.what() << endl;
            return false;
        }
    }

    int getLemmaID(const string& word) const {
        auto it = wordToID.find(word);
        if (it == wordToID.end()) return -1;

        int wordID = it->second;
        auto lemmaIt = wordIDToLemmaID.find(wordID);
        return (lemmaIt != wordIDToLemmaID.end()) ? lemmaIt->second : wordID;
    }

    vector<int> textToLemmaIDs(const string& text) const {
        vector<int> lemmaIDs;
        stringstream ss(text);
        string word;

        while (ss >> word) {
            // Lowercase
            transform(word.begin(), word.end(), word.begin(), ::tolower);

            // Remove punctuation
            word.erase(remove_if(word.begin(), word.end(), ::ispunct), word.end());

            if (!word.empty()) {
                int lemmaID = getLemmaID(word);
                if (lemmaID != -1) {
                    lemmaIDs.push_back(lemmaID);
                }
            }
        }

        return lemmaIDs;
    }
};

class ForwardIndexBuilder {
private:
    unordered_map<string, Document> forwardIndex;
    Lexicon lexicon;

public:
    bool initialize(const string& lexiconPath) {
        return lexicon.loadFromFile(lexiconPath);
    }

    bool processDocument(const string& filepath) {
        try {
            ifstream file(filepath);
            if (!file.is_open()) return false;

            json j = json::parse(file);
            file.close();

            // Extract PMC ID from filename
            string filename = fs::path(filepath).filename().string();
            string pmcId = filename.substr(0, filename.find('.'));

            Document doc;
            doc.doc_id = pmcId;

            // Extract title
            if (j.contains("metadata") && j["metadata"].contains("title")) {
                doc.title = j["metadata"]["title"].get<string>();
                doc.title_lemmas = lexicon.textToLemmaIDs(doc.title);
            }

            // Extract abstract (from abstract array)
            if (j.contains("abstract") && j["abstract"].is_array()) {
                stringstream abstractText;
                for (auto& section : j["abstract"]) {
                    if (section.contains("text")) {
                        abstractText << section["text"].get<string>() << " ";
                    }
                }
                doc.abstract = abstractText.str();
                doc.abstract_lemmas = lexicon.textToLemmaIDs(doc.abstract);
            }

            // Extract body text (from body_text array)
            if (j.contains("body_text") && j["body_text"].is_array()) {
                stringstream bodyText;
                for (auto& section : j["body_text"]) {
                    if (section.contains("text")) {
                        bodyText << section["text"].get<string>() << " ";
                    }
                }
                doc.body_lemmas = lexicon.textToLemmaIDs(bodyText.str());
            }

            // Calculate total terms
            doc.total_terms = doc.title_lemmas.size() +
                              doc.abstract_lemmas.size() +
                              doc.body_lemmas.size();

            // Only add if we got some content
            if (doc.total_terms > 0) {
                forwardIndex[pmcId] = doc;
                return true;
            }

            return false;

        } catch (exception& e) {
            cerr << "Error processing " << filepath << ": " << e.what() << endl;
            return false;
        }
    }

    void processDirectory(const string& dirPath, int maxFiles = -1) {
        cout << "Processing PMC files from: " << dirPath << endl;

        int processedCount = 0;
        int successCount = 0;

        for (const auto& entry : fs::directory_iterator(dirPath)) {
            if (entry.is_regular_file() && entry.path().extension() == ".json") {

                if (processDocument(entry.path().string())) {
                    successCount++;
                }

                processedCount++;

                if (processedCount % 1000 == 0) {
                    cout << "Processed " << processedCount << " files (indexed: "
                         << successCount << ")..." << endl;
                }

                if (maxFiles > 0 && processedCount >= maxFiles) {
                    cout << "Reached max files limit (" << maxFiles << ")" << endl;
                    break;
                }
            }
        }

        cout << "\nProcessing complete!" << endl;
        cout << "Total processed: " << processedCount << endl;
        cout << "Successfully indexed: " << successCount << endl;
    }

    void saveToFile(const string& outputPath) {
        ofstream out(outputPath);
        if (!out.is_open()) {
            cerr << "Error: Could not open output file" << endl;
            return;
        }

        cout << "Saving forward index to: " << outputPath << endl;

        for (const auto& [docId, doc] : forwardIndex) {
            out << docId << "|" << doc.total_terms << "|";

            // Save title lemmas
            for (size_t i = 0; i < doc.title_lemmas.size(); i++) {
                out << doc.title_lemmas[i];
                if (i < doc.title_lemmas.size() - 1) out << ",";
            }
            out << "|";

            // Save abstract lemmas
            for (size_t i = 0; i < doc.abstract_lemmas.size(); i++) {
                out << doc.abstract_lemmas[i];
                if (i < doc.abstract_lemmas.size() - 1) out << ",";
            }
            out << "|";

            // Save body lemmas (limit to 5000)
            size_t bodyLimit = min(doc.body_lemmas.size(), size_t(5000));
            for (size_t i = 0; i < bodyLimit; i++) {
                out << doc.body_lemmas[i];
                if (i < bodyLimit - 1) out << ",";
            }

            out << "\n";
        }

        out.close();
        cout << "Forward index saved! (" << forwardIndex.size() << " documents)" << endl;
    }

    void printStatistics() {
        cout << "\n=== Forward Index Statistics ===" << endl;
        cout << "Total documents: " << forwardIndex.size() << endl;

        long long totalTerms = 0;
        int minTerms = INT_MAX;
        int maxTerms = 0;

        for (const auto& [id, doc] : forwardIndex) {
            totalTerms += doc.total_terms;
            minTerms = min(minTerms, doc.total_terms);
            maxTerms = max(maxTerms, doc.total_terms);
        }

        cout << "Total terms indexed: " << totalTerms << endl;
        if (!forwardIndex.empty()) {
            cout << "Average terms per document: " << (totalTerms / forwardIndex.size()) << endl;
            cout << "Min terms in a document: " << minTerms << endl;
            cout << "Max terms in a document: " << maxTerms << endl;
        }

        // Show sample document
        if (!forwardIndex.empty()) {
            auto& [id, doc] = *forwardIndex.begin();
            cout << "\n=== Sample Document ===" << endl;
            cout << "Document ID: " << id << endl;
            cout << "Title terms: " << doc.title_lemmas.size() << endl;
            cout << "Abstract terms: " << doc.abstract_lemmas.size() << endl;
            cout << "Body terms: " << doc.body_lemmas.size() << endl;
            cout << "Total: " << doc.total_terms << endl;
        }
    }
};

int main() {
    try {
        // this file is in backend/cpp
        fs::path backendDir = fs::current_path().parent_path(); // backend/

        // Load centralized config
        json config = loadConfig(backendDir);

        fs::path dataDir = backendDir / config["data_dir"].get<std::string>();
        fs::path indexesDir = backendDir / config["indexes_dir"].get<std::string>();
        indexesDir /= ""; // just to normalize

        fs::create_directories(indexesDir); // ensure it exists

        fs::path lexiconPath = indexesDir / config["lexicon_file"].get<std::string>();
        fs::path forwardIndexPath = indexesDir / config["forward_index_file"].get<std::string>();

        // Find pmc-json folder
        fs::path pmcFolder = findPMCJSONFolder(dataDir, config["json_data"]);

        // Initialize builder
        ForwardIndexBuilder builder;
        if (!builder.initialize(lexiconPath.string())) {
            std::cerr << "Failed to load lexicon!" << std::endl;
            return 1;
        }

        // Process all JSON files
        builder.processDirectory(pmcFolder.string());

        builder.printStatistics();
        builder.saveToFile(forwardIndexPath.string());

        std::cout << "Done!" << std::endl;
    } catch (std::exception& e) {
        std::cerr << "Error: " << e.what() << std::endl;
        return 1;
    }

    return 0;
}
