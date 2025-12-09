#include "config.hpp"

#include <iostream>
#include <sstream>
#include <string>
#include <vector>
#include <unordered_map>
#include <unordered_set>
#include <algorithm>
#include <chrono>
#include <iomanip>
#include <cmath>
#include <climits>



using namespace std;
using namespace chrono;





// Posting: document ID + term frequency in that document
struct Posting {
    string doc_id;
    int term_frequency;
    
    Posting(string id, int tf) : doc_id(id), term_frequency(tf) {}
};

// Inverted Index: lemma_id -> list of postings
class InvertedIndex {
private:
    unordered_map<int, vector<Posting>> index;
    int totalDocuments;
    
public:
    InvertedIndex() : totalDocuments(0) {}
    
    // Build inverted index from forward index file
    void buildFromForwardIndex(const string& forwardIndexPath) {
        auto startTime = high_resolution_clock::now();
        
        ifstream file(forwardIndexPath);
        if (!file.is_open()) {
            cerr << "Error: Could not open " << forwardIndexPath << endl;
            return;
        }
        
        cout << "Building inverted index from: " << forwardIndexPath << endl;
        cout << "Start time: " << getCurrentTime() << endl;
        
        string line;
        int docCount = 0;
        
        auto lastUpdate = high_resolution_clock::now();
        
        while (getline(file, line)) {
            // Parse: doc_id|total_terms|title_lemmas|abstract_lemmas|body_lemmas
            stringstream ss(line);
            string doc_id, total_terms_str, title_lemmas, abstract_lemmas, body_lemmas;
            
            getline(ss, doc_id, '|');
            getline(ss, total_terms_str, '|');
            getline(ss, title_lemmas, '|');
            getline(ss, abstract_lemmas, '|');
            getline(ss, body_lemmas, '|');
            
            // Combine all lemmas
            vector<int> allLemmas;
            parseLemmas(title_lemmas, allLemmas);
            parseLemmas(abstract_lemmas, allLemmas);
            parseLemmas(body_lemmas, allLemmas);
            
            // Count term frequencies in this document
            unordered_map<int, int> termFreqs;
            for (int lemma : allLemmas) {
                termFreqs[lemma]++;
            }
            
            // Add to inverted index
            for (const auto& [lemma, freq] : termFreqs) {
                index[lemma].push_back(Posting(doc_id, freq));
            }
            
            docCount++;
            if (docCount % 5000 == 0) {
                auto now = high_resolution_clock::now();
                auto elapsed = duration_cast<seconds>(now - lastUpdate).count();
                auto totalElapsed = duration_cast<seconds>(now - startTime).count();
                
                cout << "Processed " << docCount << " documents... "
                     << "(Last 5000 in " << elapsed << "s, "
                     << "Total: " << formatTime(totalElapsed) << ")" << endl;
                
                lastUpdate = now;
            }
        }
        
        totalDocuments = docCount;
        file.close();
        
        auto endTime = high_resolution_clock::now();
        auto totalTime = duration_cast<milliseconds>(endTime - startTime).count();
        
        cout << "\nInverted index built successfully!" << endl;
        cout << "End time: " << getCurrentTime() << endl;
        cout << "Total time: " << formatTime(totalTime / 1000.0) << endl;
        cout << "Processing rate: " << (docCount / (totalTime / 1000.0)) << " docs/sec" << endl;
        cout << "Total documents: " << totalDocuments << endl;
        cout << "Unique terms (lemmas): " << index.size() << endl;
    }
    
    // Save inverted index to file
    void saveToFile(const string& outputPath) {
        auto startTime = high_resolution_clock::now();
        
        ofstream out(outputPath);
        if (!out.is_open()) {
            cerr << "Error: Could not open output file" << endl;
            return;
        }
        
        cout << "\nSaving inverted index to: " << outputPath << endl;
        cout << "Start time: " << getCurrentTime() << endl;
        
        int termsWritten = 0;
        
        // Format: lemma_id|document_frequency|doc1:tf1,doc2:tf2,...
        for (const auto& [lemma, postings] : index) {
            out << lemma << "|" << postings.size() << "|";
            
            for (size_t i = 0; i < postings.size(); i++) {
                out << postings[i].doc_id << ":" << postings[i].term_frequency;
                if (i < postings.size() - 1) out << ",";
            }
            out << "\n";
            
            termsWritten++;
            if (termsWritten % 10000 == 0) {
                cout << "Written " << termsWritten << " terms..." << endl;
            }
        }
        
        out.close();
        
        auto endTime = high_resolution_clock::now();
        auto totalTime = duration_cast<milliseconds>(endTime - startTime).count();
        
        cout << "Inverted index saved!" << endl;
        cout << "End time: " << getCurrentTime() << endl;
        cout << "Save time: " << formatTime(totalTime / 1000.0) << endl;
        cout << "Write rate: " << (termsWritten / (totalTime / 1000.0)) << " terms/sec" << endl;
    }
    
    // Get statistics
    void printStatistics() {
        cout << "\n=== Inverted Index Statistics ===" << endl;
        cout << "Total documents: " << totalDocuments << endl;
        cout << "Unique terms: " << index.size() << endl;
        
        // Calculate average postings per term
        long long totalPostings = 0;
        int minPostings = INT_MAX;
        int maxPostings = 0;
        int maxLemma = -1;
        
        for (const auto& [lemma, postings] : index) {
            int size = postings.size();
            totalPostings += size;
            minPostings = min(minPostings, size);
            if (size > maxPostings) {
                maxPostings = size;
                maxLemma = lemma;
            }
        }
        
        cout << "Total postings: " << totalPostings << endl;
        cout << "Average postings per term: " << (totalPostings / index.size()) << endl;
        cout << "Min postings (rarest term): " << minPostings << endl;
        cout << "Max postings (most common term): " << maxPostings << " (lemma ID: " << maxLemma << ")" << endl;
        
        // Sample some terms
        cout << "\n=== Sample Terms ===" << endl;
        int count = 0;
        for (const auto& [lemma, postings] : index) {
            cout << "Lemma " << lemma << " appears in " << postings.size() << " documents" << endl;
            if (++count >= 5) break;
        }
    }
    
    // Search functionality (for testing)
    vector<string> search(int lemmaId) {
        auto startTime = high_resolution_clock::now();
        
        vector<string> results;
        
        if (index.find(lemmaId) != index.end()) {
            for (const auto& posting : index[lemmaId]) {
                results.push_back(posting.doc_id);
            }
        }
        
        auto endTime = high_resolution_clock::now();
        auto searchTime = duration_cast<microseconds>(endTime - startTime).count();
        
        cout << "(Search time: " << searchTime << " microseconds)" << endl;
        
        return results;
    }
    
    // Get document frequency (how many docs contain this term)
    int getDocumentFrequency(int lemmaId) {
        if (index.find(lemmaId) != index.end()) {
            return index[lemmaId].size();
        }
        return 0;
    }
    
    // Calculate IDF (Inverse Document Frequency)
    double calculateIDF(int lemmaId) {
        int df = getDocumentFrequency(lemmaId);
        if (df == 0) return 0.0;
        
        // IDF = log(N / df)
        return log((double)totalDocuments / df);
    }
    
private:
    void parseLemmas(const string& lemmaStr, vector<int>& lemmas) {
        if (lemmaStr.empty()) return;
        
        stringstream ss(lemmaStr);
        string token;
        
        while (getline(ss, token, ',')) {
            if (!token.empty()) {
                try {
                    lemmas.push_back(stoi(token));
                } catch (...) {
                    // Skip malformed tokens
                }
            }
        }
    }
    
    // Helper function to get current time as string
    string getCurrentTime() {
        auto now = system_clock::now();
        auto time = system_clock::to_time_t(now);
        stringstream ss;
        ss << put_time(localtime(&time), "%Y-%m-%d %H:%M:%S");
        return ss.str();
    }
    
    // Helper function to format time duration
    string formatTime(double seconds) {
        stringstream ss;
        
        if (seconds < 60) {
            ss << fixed << setprecision(2) << seconds << " seconds";
        } else if (seconds < 3600) {
            int mins = (int)(seconds / 60);
            double secs = seconds - (mins * 60);
            ss << mins << " min " << fixed << setprecision(0) << secs << " sec";
        } else {
            int hours = (int)(seconds / 3600);
            int mins = (int)((seconds - hours * 3600) / 60);
            ss << hours << " hr " << mins << " min";
        }
        
        return ss.str();
    }
};

int main() {
    try {
        // Assume this file is in backend/cpp
        fs::path backendDir = fs::current_path().parent_path(); // backend/

        // Load centralized config
        json config = loadConfig(backendDir);

        fs::path indexesDir = backendDir / config["indexes_dir"].get<std::string>();
        fs::create_directories(indexesDir); // ensure folder exists

        fs::path forwardIndexPath = indexesDir / config["forward_index_file"].get<std::string>();
        fs::path invertedIndexPath = indexesDir / config["inverted_index_file"].get<std::string>();

        InvertedIndex invertedIndex;

        // Build inverted index from forward index
        invertedIndex.buildFromForwardIndex(forwardIndexPath.string());

        // Print statistics
        invertedIndex.printStatistics();

        // Save inverted index
        invertedIndex.saveToFile(invertedIndexPath.string());

        std::cout << "\nInverted index saved to " << invertedIndexPath << std::endl;
    }
    catch (const std::exception& e) {
        std::cerr << "Error: " << e.what() << std::endl;
        return 1;
    }

    return 0;
}
