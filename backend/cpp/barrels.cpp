#include "config.hpp"

#include <iostream>
#include <sstream>
#include <string>
#include <vector>
#include <chrono>


using namespace std;
using namespace chrono;

struct Posting {
    string doc_id;
    int tf;
};

class JSONBarrelCreator {
private:
    int numBarrels;
    fs::path outputDir;
    vector<json> barrels;
    
public:
    JSONBarrelCreator(int numBarrels, fs::path outDir) 
        : numBarrels(numBarrels), outputDir(outDir) {
        
        fs::create_directories(outputDir);
        
        // Initialize barrel JSON objects
        for (int i = 0; i < numBarrels; i++) {
            json barrel;
            barrel["barrel_id"] = i;
            barrel["num_terms"] = 0;
            barrel["postings"] = json::object();
            barrels.push_back(barrel);
        }
        
        cout << "Initialized " << numBarrels << " JSON barrels" << endl;
    }
    
    void createFromInvertedIndex(const string& invertedIndexPath) {
        auto startTime = high_resolution_clock::now();
        
        ifstream input(invertedIndexPath);
        if (!input.is_open()) {
            cerr << "Error: Could not open " << invertedIndexPath << endl;
            return;
        }
        
        cout << "\nReading inverted index: " << invertedIndexPath << endl;
        cout << "Using FREQUENCY-BASED partitioning for optimal time complexity\n" << endl;
        
        // First pass: categorize terms by frequency
        vector<tuple<int, int, string>> termData; // (lemmaId, df, postings)
        
        string line;
        while (getline(input, line)) {
            stringstream ss(line);
            string lemmaIdStr, dfStr, postingsStr;
            
            getline(ss, lemmaIdStr, '|');
            getline(ss, dfStr, '|');
            getline(ss, postingsStr, '|');
            
            int lemmaId = stoi(lemmaIdStr);
            int df = stoi(dfStr);
            
            termData.push_back({lemmaId, df, line});
        }
        
        input.close();
        
        cout << "Total terms: " << termData.size() << endl;
        
        // Second pass: partition by frequency
        int hotThreshold = 10000;   // HOT: df > 10k
        int warmThreshold = 1000;   // WARM: df 1k-10k
        
        int hotCount = 0, warmCount = 0, coldCount = 0;
        
        for (const auto& [lemmaId, df, lineData] : termData) {
            int barrelNum;
            
            if (df > hotThreshold) {
                barrelNum = 0;  // HOT barrel
                hotCount++;
            } else if (df > warmThreshold) {
                barrelNum = 1 + (lemmaId % 6);   // 1..6
                warmCount++;
            } else {
                barrelNum = 7 + ((lemmaId % 3));  // COLD barrels (7-9)
                coldCount++;
            }
            
            // Parse line and add to barrel
            stringstream ss(lineData);
            string lemmaIdStr, dfStr, postingsStr;
            
            getline(ss, lemmaIdStr, '|');
            getline(ss, dfStr, '|');
            getline(ss, postingsStr, '|');
            
            // Create posting list
            json postingList = json::array();
            stringstream postingStream(postingsStr);
            string posting;
            
            while (getline(postingStream, posting, ',')) {
                size_t colonPos = posting.find(':');
                if (colonPos != string::npos) {
                    string docId = posting.substr(0, colonPos);
                    int tf = stoi(posting.substr(colonPos + 1));
                    
                    json postingObj;
                    postingObj["doc_id"] = docId;
                    postingObj["tf"] = tf;
                    
                    postingList.push_back(postingObj);
                }
            }
            
            // Add to barrel
            json termDataJson;
            termDataJson["df"] = df;
            termDataJson["docs"] = postingList;
            
            barrels[barrelNum]["postings"][lemmaIdStr] = termDataJson;
            barrels[barrelNum]["num_terms"] = barrels[barrelNum]["num_terms"].get<int>() + 1;
        }
        
        // Update barrel metadata
        barrels[0]["type"] = "HOT";
        barrels[0]["description"] = "Common terms (df > 10k)";
        for (int i = 1; i <= 6; i++) {
            barrels[i]["type"] = "WARM";
            barrels[i]["description"] = "Medium frequency (df 1k-10k)";
        }
        for (int i = 7; i < numBarrels; i++) {
            barrels[i]["type"] = "COLD";
            barrels[i]["description"] = "Rare terms (df < 1k)";
        }
        
        auto endTime = high_resolution_clock::now();
        auto duration = duration_cast<seconds>(endTime - startTime).count();
        
        cout << "\n=== Frequency Distribution ===" << endl;
        cout << "HOT (df>10k): " << hotCount << " terms → Barrel 0" << endl;
        cout << "WARM (df 1k-10k): " << warmCount << " terms → Barrels 1-6" << endl;
        cout << "COLD (df<1k): " << coldCount << " terms → Barrels 7-9" << endl;
        cout << "\nProcessing time: " << duration << " seconds" << endl;
        cout << "\nTime Complexity: O(H) for hot queries where H << total_terms" << endl;
    }
    
    void saveBarrels() {
        auto startTime = high_resolution_clock::now();
        
        cout << "\nSaving JSON barrels..." << endl;
        
        for (int i = 0; i < numBarrels; i++) {
            string filename = "inverted_barrel_" + to_string(i) + ".json";
            fs::path filepath = outputDir / filename;
            
            ofstream outFile(filepath);
            if (!outFile.is_open()) {
                cerr << "Error: Could not create " << filepath << endl;
                continue;
            }
            
            // Write JSON with indentation
            outFile << barrels[i].dump(2);
            outFile.close();
            
            // Get file size
            auto fileSize = fs::file_size(filepath);
            cout << "Saved " << filename 
                 << " (" << barrels[i]["num_terms"].get<int>() << " terms, "
                 << (fileSize / 1024.0 / 1024.0) << " MB)" << endl;
        }
        
        auto endTime = high_resolution_clock::now();
        auto duration = duration_cast<seconds>(endTime - startTime).count();
        
        cout << "\nAll barrels saved!" << endl;
        cout << "Save time: " << duration << " seconds" << endl;
    }
    
    void printStatistics() {
        cout << "\n======================================" << endl;
        cout << "  BARREL STATISTICS" << endl;
        cout << "======================================" << endl;
        
        int totalTerms = 0;
        size_t totalSize = 0;
        
        for (int i = 0; i < numBarrels; i++) {
            int numTerms = barrels[i]["num_terms"].get<int>();
            totalTerms += numTerms;
            
            string filename = "inverted_barrel_" + to_string(i) + ".json";
            fs::path filepath = outputDir / filename;
            
            if (fs::exists(filepath)) {
                totalSize += fs::file_size(filepath);
            }
        }
        
        cout << "Total barrels: " << numBarrels << endl;
        cout << "Total terms: " << totalTerms << endl;
        cout << "Average terms per barrel: " << (totalTerms / numBarrels) << endl;
        cout << "Total size: " << (totalSize / 1024.0 / 1024.0) << " MB" << endl;
        cout << "Average size per barrel: " << (totalSize / numBarrels / 1024.0 / 1024.0) << " MB" << endl;
        cout << "======================================" << endl;
    }
};

int main() {
    try {
        cout << "======================================" << endl;
        cout << "  JSON INVERTED BARREL CREATOR" << endl;
        cout << "======================================\n" << endl;
        
        // Load config
        fs::path backendDir = fs::current_path().parent_path();
        json config = loadConfig(backendDir);
        
        // Get paths
        fs::path indexesDir = backendDir / config["indexes_dir"].get<string>();
        fs::path invertedIndexPath = indexesDir / config["inverted_index_file"].get<string>();
        fs::path barrelsDir = indexesDir / config["barrels_dir"];
        
        // Configuration
        const int numBarrels = 10;
        
        cout << "Configuration:" << endl;
        cout << "  Number of barrels: " << numBarrels << endl;
        cout << "  Input: " << invertedIndexPath.string() << endl;
        cout << "  Output directory: " << barrelsDir.string() << "\n" << endl;
        
        // Check if input exists
        if (!fs::exists(invertedIndexPath)) {
            cerr << "Error: Inverted index file not found!" << endl;
            cerr << "Looking for: " << invertedIndexPath.string() << endl;
            return 1;
        }
        
        // Create barrels
        JSONBarrelCreator creator(numBarrels, barrelsDir);
        creator.createFromInvertedIndex(invertedIndexPath.string());
        creator.saveBarrels();
        creator.printStatistics();
        
        cout << "\n======================================" << endl;
        cout << "JSON barrels created successfully!" << endl;
        cout << "Location: " << barrelsDir.string() << endl;
        cout << "======================================" << endl;
        
    } catch (exception& e) {
        cerr << "Error: " << e.what() << endl;
        return 1;
    }
    
    return 0;
}
