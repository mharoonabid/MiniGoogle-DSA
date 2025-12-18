# MiniGoogle-DSA

A lightweight yet powerful search engine inspired by "The Anatomy of a Large Scale Hypertextual Web Search Engine". This project features **file-based indices**, **semantic search**, **auto-complete**, **ranking**, and **barrel-based scaling**. Developed as the Final Semester Project for Data Structures and Algorithms (DSA).

---

## Getting Started

Follow these steps to set up the project environment, download the necessary data, and build the core search engine indices.

### 1. Prerequisites

To ensure the project runs correctly, you must have the following installed:

* **Python:** Version **3.0 or higher**.
* **C++ Compiler:** Supports **C++17 standard** (e.g., GCC 7+).

---

### 2. Dataset Download and Placement

The search engine is designed to run on the CORD-19 research challenge dataset.

1. **Download the Dataset:** [CORD-19 Dataset on Kaggle](https://www.kaggle.com/datasets/allen-institute-for-ai/CORD-19-research-challenge/versions/35)
2. **Extract:** Unzip the downloaded file.
3. **Placement:** Place the **extracted folder** containing JSON files in:

```
MiniGoogle-DSA/backend/data/
```
OR you can download zip file of 100 JSON files for testing. [Click here](https://drive.google.com/file/d/1-Upu0c0mJXNpzklmcNAaF_EwoCn98HWK/view?usp=sharing)

---

### 3. Folder Structure

The project should be organized as follows:

```
MiniGoogle-DSA
└── backend/
    ├── cpp/
    │   ├── forwardIndex.cpp
    │   ├── invertedIndex.cpp
    │   └── barrels.cpp
    │   └── barrels_binary.cpp
    │   └── search.cpp
    │   └── search_semantic.cpp
    │   ├── config.hpp
    │   └── json.hpp
    │   ├── build/
    ├── py/
    │   └── lexicon.py
    ├── data/
    ├── indexes/
    └── requirements.txt
└── frontend/
    └── eslint.config.js
    └── index.html
    └── package-lock.json
    └── package.json
    └── vite.config.json
    ├── public/
    ├── src/
    │   └── assets/
    │   └── App.css
    │   └── App.jsx
    │   └── index.css
    │   └── main.jsx
```
---




### 4. Basic Setup
You can run this entire build process automatically using the provided scripts. **Ensure you are in root directory (`MiniGoogle-DSA/`).**

**Linux/MacOS**
```
./run.sh
```
If you encounter a "Permission Denied" error, grant the permission by using the following command

```
sudo chmod +x run.sh
```
**Windows**

To build and run the search engine,simply double click the batch file.

```
run.bat
```
---
## Output

Upon successful completion, the generated index files will be saved in:

```
MiniGoogle-DSA/backend/indexes/
```

These are now ready to be consumed by the search engine for querying.

