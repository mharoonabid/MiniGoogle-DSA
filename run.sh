#!/bin/bash

# ===== Colors =====
RED="\e[31m" # errors
GREEN="\e[32m" # success status
YELLOW="\e[33m" # warnings
BLUE="\e[34m" # headings
RESET="\e[0m" # for reset

echo -e "${BLUE}=== MiniGoogle-DSA Build Script (Linux/macOS) ===${RESET}"

# Detect Python
if command -v python3 &>/dev/null; then
    PYTHON="python3"
elif command -v python &>/dev/null; then
    PYTHON="python"
else
    echo -e "${RED}Error: Python not found.${RESET}"
    exit 1
fi

# Detect g++
if ! command -v g++ &>/dev/null; then
    echo -e "${RED}Error: g++ compiler not found.${RESET}"
    exit 1
fi

echo -e "${GREEN}Using Python:${RESET} $PYTHON"
echo -e "${GREEN}Using C++ Compiler:${RESET} g++"

echo -e "${BLUE}=== Setting up Python virtual environment ===${RESET}"
if [ ! -d ".venv" ]; then
    echo -e "${YELLOW}Creating virtual environment...${RESET}"
    $PYTHON -m venv .venv || { echo -e "${RED}Failed to create virtual environment.${RESET}"; exit 1; }
else
    echo -e "${GREEN}Virtual environment already exists.${RESET}"
fi

source .venv/bin/activate || { echo -e "${RED}Failed to activate virtual environment.${RESET}"; exit 1; }


echo -e "${BLUE}=== Installing Python dependencies ===${RESET}"
pip install -r backend/requirements.txt || { echo -e "${RED}Dependency installation failed.${RESET}"; exit 1; }

echo -e "${BLUE}=== Running Lexicon Script ===${RESET}"
$PYTHON -u backend/py/lexicon.py || { echo -e "${RED}Lexicon generation failed.${RESET}"; exit 1; }

echo -e "${BLUE}=== Building Forward Index ===${RESET}"
g++ -o backend/cpp/build/forwardIndex backend/cpp/forwardIndex.cpp -std=c++17 || { echo -e "${RED}Forward index compilation failed.${RESET}"; exit 1; }
./backend/cpp/build/forwardIndex || { echo -e "${RED}Forward index run failed.${RESET}"; exit 1; }

echo -e "${BLUE}=== Building Inverted Index ===${RESET}"
g++ -o backend/cpp/build/invertedIndex backend/cpp/invertedIndex.cpp -std=c++17 || { echo -e "${RED}Inverted index compilation failed.${RESET}"; exit 1; }
.backend/cpp/build/invertedIndex || { echo -e "${RED}Inverted index run failed.${RESET}"; exit 1; }

echo -e "${BLUE}=== Building Inverted Barrels ===${RESET}"
g++ -o backend/cpp/build/barrels backend/cpp/barrels.cpp -std=c++17 || { echo -e "${RED}Barrels compilation failed.${RESET}"; exit 1; }
.backend/cpp/build/barrels || { echo -e "${RED}Barrels run failed.${RESET}"; exit 1; }


echo -e "${BLUE}=== Deactivating Python virtual environment ===${RESET}"
deactivate || { echo -e "${RED}Failed to deactivate virtual environment.${RESET}"; exit 1; }

echo -e "${GREEN}=== All steps completed successfully! ===${RESET}"
