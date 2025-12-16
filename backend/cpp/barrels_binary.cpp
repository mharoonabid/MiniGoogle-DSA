/*
 * Binary Barrel Converter
 *
 * Converts JSON barrels to binary format for O(1) seeks
 * This dramatically improves search performance from ~60s to <500ms
 *
 * Binary Format:
 * - barrel_X.bin: Binary postings data
 * - barrel_X.idx: Offset index (lemmaId -> offset, length)
 *
 * Posting entry format in .bin file:
 * [lemmaId:4bytes][df:4bytes][numDocs:4bytes][doc1_id_len:2bytes][doc1_id:var][doc1_tf:4bytes]...
 */

#include "config.hpp"
#include <iostream>
#include <fstream>
#include <sstream>
#include <string>
#include <vector>
#include <unordered_map>
#include <chrono>
#include <cstring>

using namespace std;
using namespace chrono;

// Fixed-size doc ID (padded to 20 chars for PMC IDs)
const int DOC_ID_SIZE = 20;

struct BinaryPosting {
    char doc_id[DOC_ID_SIZE];
    int32_t tf;
};

class BinaryBarrelConverter {
private:
    int numBarrels;
    fs::path inputDir;
    fs::path outputDir;

public:
    BinaryBarrelConverter(int numBarrels, fs::path inDir, fs::path outDir)
        : numBarrels(numBarrels), inputDir(inDir), outputDir(outDir) {
        fs::create_directories(outputDir);
    }

    void convertAllBarrels() {
        auto startTime = high_resolution_clock::now();

        cout << "Converting " << numBarrels << " JSON barrels to binary format...\n" << endl;

        for (int i = 0; i < numBarrels; i++) {
            convertBarrel(i);
        }

        auto endTime = high_resolution_clock::now();
        auto duration = duration_cast<seconds>(endTime - startTime).count();

        cout << "\n=== Conversion Complete ===" << endl;
        cout << "Total time: " << duration << " seconds" << endl;
    }

    void convertBarrel(int barrelId) {
        string jsonFilename = "inverted_barrel_" + to_string(barrelId) + ".json";
        fs::path jsonPath = inputDir / jsonFilename;

        if (!fs::exists(jsonPath)) {
            cerr << "Warning: " << jsonPath << " not found, skipping." << endl;
            return;
        }

        cout << "Converting barrel " << barrelId << "..." << flush;
        auto startTime = high_resolution_clock::now();

        // Output files
        string binFilename = "barrel_" + to_string(barrelId) + ".bin";
        string idxFilename = "barrel_" + to_string(barrelId) + ".idx";

        fs::path binPath = outputDir / binFilename;
        fs::path idxPath = outputDir / idxFilename;

        // Load JSON barrel
        ifstream jsonFile(jsonPath);
        json barrel;
        jsonFile >> barrel;
        jsonFile.close();

        // Open binary output files
        ofstream binFile(binPath, ios::binary);
        ofstream idxFile(idxPath, ios::binary);

        if (!binFile.is_open() || !idxFile.is_open()) {
            cerr << "Error opening output files for barrel " << barrelId << endl;
            return;
        }

        // Write header to idx file: [numEntries:4bytes]
        const json& postings = barrel["postings"];
        int32_t numEntries = postings.size();
        idxFile.write(reinterpret_cast<char*>(&numEntries), sizeof(numEntries));

        int termCount = 0;

        for (auto& [lemmaKey, postingData] : postings.items()) {
            int32_t lemmaId = stoi(lemmaKey);
            int32_t df = postingData["df"].get<int>();
            const json& docs = postingData["docs"];
            int32_t numDocs = docs.size();

            // Record offset before writing
            int64_t offset = binFile.tellp();

            // Write to bin file: [lemmaId][df][numDocs][postings...]
            binFile.write(reinterpret_cast<char*>(&lemmaId), sizeof(lemmaId));
            binFile.write(reinterpret_cast<char*>(&df), sizeof(df));
            binFile.write(reinterpret_cast<char*>(&numDocs), sizeof(numDocs));

            // Write each posting
            for (const auto& doc : docs) {
                BinaryPosting bp;
                memset(bp.doc_id, 0, DOC_ID_SIZE);
                string docId = doc["doc_id"].get<string>();
                strncpy(bp.doc_id, docId.c_str(), DOC_ID_SIZE - 1);
                bp.tf = doc["tf"].get<int>();

                binFile.write(bp.doc_id, DOC_ID_SIZE);
                binFile.write(reinterpret_cast<char*>(&bp.tf), sizeof(bp.tf));
            }

            // Calculate length
            int64_t length = static_cast<int64_t>(binFile.tellp()) - offset;

            // Write to idx file: [lemmaId][offset][length]
            idxFile.write(reinterpret_cast<char*>(&lemmaId), sizeof(lemmaId));
            idxFile.write(reinterpret_cast<char*>(&offset), sizeof(offset));
            idxFile.write(reinterpret_cast<char*>(&length), sizeof(length));

            termCount++;
        }

        binFile.close();
        idxFile.close();

        auto endTime = high_resolution_clock::now();
        auto duration = duration_cast<milliseconds>(endTime - startTime).count();

        // Get file sizes
        auto binSize = fs::file_size(binPath) / 1024.0 / 1024.0;
        auto idxSize = fs::file_size(idxPath) / 1024.0 / 1024.0;

        cout << " done! (" << duration << "ms, "
             << termCount << " terms, bin: " << binSize << "MB, idx: " << idxSize << "MB)" << endl;
    }
};

// Helper to find backend directory from executable path
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

    // Navigate from build/ to backend/
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

    throw runtime_error("Cannot find config.json");
}

int main(int argc, char* argv[]) {
    try {
        cout << "======================================" << endl;
        cout << "  BINARY BARREL CONVERTER" << endl;
        cout << "======================================\n" << endl;

        // Find backend directory (works from any location)
        fs::path backendDir = findBackendDir(argv[0]);
        json config = loadConfig(backendDir);

        // Get paths
        fs::path indexesDir = backendDir / config["indexes_dir"].get<string>();
        fs::path jsonBarrelsDir = indexesDir / config["barrels_dir"].get<string>();
        fs::path binaryBarrelsDir = indexesDir / "barrels_binary";

        const int numBarrels = 10;

        cout << "Configuration:" << endl;
        cout << "  Input (JSON barrels): " << jsonBarrelsDir.string() << endl;
        cout << "  Output (Binary barrels): " << binaryBarrelsDir.string() << endl;
        cout << "  Number of barrels: " << numBarrels << "\n" << endl;

        // Convert barrels
        BinaryBarrelConverter converter(numBarrels, jsonBarrelsDir, binaryBarrelsDir);
        converter.convertAllBarrels();

        cout << "\n======================================" << endl;
        cout << "Binary barrels created successfully!" << endl;
        cout << "Location: " << binaryBarrelsDir.string() << endl;
        cout << "======================================" << endl;

    } catch (exception& e) {
        cerr << "Error: " << e.what() << endl;
        return 1;
    }

    return 0;
}
