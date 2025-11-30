# MiniGoogle-DSA

A lightweight yet powerful search engine inspired by "The Anatomy of a Large Scale Hypertextual Web Search Engine". This project features **file-based indices**, **semantic search**, **auto-complete**, **ranking**, and **barrel-based scaling**. Developed as the Final Semester Project for Data Structures and Algorithms (DSA).

---

## Getting Started

Follow these steps to set up the project environment, download the necessary data, and build the core search engine indices.

### 1. Prerequisites

To ensure the project runs correctly, you must have the following installed:

* **Python:** Version **3.0 or higher**.
* **C++ Compiler:** Supports **C++17 standard** (e.g., GCC 7+, Clang 5+, or MSVC 2017+ for Windows).

> **Note:** On Linux/macOS, commands generally use `python3` and `g++`. On Windows, `python` and `cl` or `g++` via MinGW can be used.

---

### 2. Dataset Download and Placement

The search engine is designed to run on the CORD-19 research challenge dataset.

1. **Download the Dataset:** [CORD-19 Dataset on Kaggle](https://www.kaggle.com/datasets/allen-institute-for-ai/CORD-19-research-challenge/versions/35)
2. **Extract:** Unzip the downloaded file.
3. **Placement:** Place the **extracted folder** containing JSON files in:

```
MiniGoogle-DSA/backend/data/
```

---

### 3. Folder Structure

The project should be organized as follows:

```
MiniGoogle-DSA
└── backend/
    ├── cpp/
    │   ├── forwardIndex.cpp
    │   ├── invertedIndex.cpp
    │   ├── config.cpp
    │   ├── config.hpp
    │   └── json.hpp
    ├── py/
    │   └── lexicon.py
    ├── data/
    ├── indexes/
    └── requirements.txt
```
---

## Testing
You can use this data of 100 JSON files for testing by downloading the zip file form here. [Click here](https://drive.google.com/file/d/1-Upu0c0mJXNpzklmcNAaF_EwoCn98HWK/view?usp=sharing).

## Indexing and Build Process

The search engine relies on three sequential steps to process raw data and generate indices. **Run all commands from the root directory (`MiniGoogle-DSA/`).**

---

### Step 1: Generate the Lexicon (Python)

The `lexicon.py` script performs preprocessing, tokenization, and generates a list of unique terms.

**Install Python dependencies:**

**Mac/Linux:**

```bash
pip3 install -r backend/requirements.txt
```

**Windows (PowerShell or CMD):**

```cmd
pip install -r backend\requirements.txt
```

**Run the Lexicon Script:**

**Mac/Linux:**

```bash
python3 -u backend/py/lexicon.py
```

**Windows:**

```cmd
python -u backend\py\lexicon.py
```

---

### Step 2: Build the Forward Index (C++)

The Forward Index maps document IDs to lists of terms.

**Mac/Linux:**

```bash
g++ -o forwardIndex backend/cpp/forwardIndex.cpp backend/cpp/config.cpp -std=c++17 && ./forwardIndex
```

**Windows (using MinGW g++):**

```cmd
g++ -o forwardIndex.exe backend\cpp\forwardIndex.cpp backend\cpp\config.cpp -std=c++17
forwardIndex.exe
```

**Windows (using MSVC `cl`):**

```cmd
cl /EHsc /std:c++17 backend\cpp\forwardIndex.cpp backend\cpp\config.cpp
forwardIndex.exe
```

---

### Step 3: Build the Inverted Index (C++)

The Inverted Index maps terms to lists of documents.

**Mac/Linux:**

```bash
g++ -o invertedIndex backend/cpp/invertedIndex.cpp backend/cpp/config.cpp -std=c++17 && ./invertedIndex
```

**Windows (MinGW g++):**

```cmd
g++ -o invertedIndex.exe backend\cpp\invertedIndex.cpp backend\cpp\config.cpp -std=c++17
invertedIndex.exe
```

**Windows (MSVC `cl`):**

```cmd
cl /EHsc /std:c++17 backend\cpp\invertedIndex.cpp backend\cpp\config.cpp
invertedIndex.exe
```

---

## Output

Upon successful completion, the generated index files will be saved in:

```
MiniGoogle-DSA/backend/indexes/
```

These are now ready to be consumed by the search engine for querying.
