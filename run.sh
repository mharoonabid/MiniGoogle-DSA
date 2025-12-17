#!/bin/bash

# ===== Colors =====
RED="\e[31m"
GREEN="\e[32m"
YELLOW="\e[33m"
BLUE="\e[34m"
CYAN="\e[36m"
BOLD="\e[1m"
RESET="\e[0m"

# ===== Paths =====
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_DIR="$SCRIPT_DIR/backend"
FRONTEND_DIR="$SCRIPT_DIR/frontend"
INDEXES_DIR="$BACKEND_DIR/indexes"
CPP_BUILD_DIR="$BACKEND_DIR/cpp/build"

# ===== Functions =====

print_header() {
    echo -e "\n${BLUE}${BOLD}======================================${RESET}"
    echo -e "${BLUE}${BOLD}  MiniGoogle-DSA${RESET}"
    echo -e "${BLUE}${BOLD}======================================${RESET}\n"
}

print_menu() {
    echo -e "${CYAN}${BOLD}Select an option:${RESET}\n"
    echo -e "  ${GREEN}1)${RESET} Full Build (Build everything from scratch)"
    echo -e "  ${GREEN}2)${RESET} Start Server Only (Use existing indexes)"
    echo -e "  ${GREEN}3)${RESET} Build Indexes Only (Lexicon, Forward, Inverted, Barrels)"
    echo -e "  ${GREEN}4)${RESET} Build C++ Executables Only"
    echo -e "  ${GREEN}5)${RESET} Build Embeddings & Semantic Search"
    echo -e "  ${GREEN}6)${RESET} Build N-gram Index (Multi-word autocomplete)"
    echo -e "  ${GREEN}7)${RESET} Start Frontend Only"
    echo -e "  ${GREEN}8)${RESET} Start Backend API Only"
    echo -e "  ${GREEN}9)${RESET} Check Index Files Status"
    echo -e "  ${GREEN}0)${RESET} Exit"
    echo ""
}

detect_python() {
    if command -v python3 &>/dev/null; then
        PYTHON="python3"
    elif command -v python &>/dev/null; then
        PYTHON="python"
    else
        echo -e "${RED}Error: Python not found.${RESET}"
        exit 1
    fi
    echo -e "${GREEN}Using Python:${RESET} $PYTHON"
}

detect_compiler() {
    if ! command -v g++ &>/dev/null; then
        echo -e "${RED}Error: g++ compiler not found.${RESET}"
        exit 1
    fi
    echo -e "${GREEN}Using C++ Compiler:${RESET} g++"
}

setup_venv() {
    echo -e "${BLUE}=== Setting up Python virtual environment ===${RESET}"
    if [ ! -d "$SCRIPT_DIR/.venv" ]; then
        echo -e "${YELLOW}Creating virtual environment...${RESET}"
        $PYTHON -m venv "$SCRIPT_DIR/.venv" || { echo -e "${RED}Failed to create virtual environment.${RESET}"; exit 1; }
    else
        echo -e "${GREEN}Virtual environment already exists.${RESET}"
    fi
    source "$SCRIPT_DIR/.venv/bin/activate" || { echo -e "${RED}Failed to activate virtual environment.${RESET}"; exit 1; }
}

install_deps() {
    echo -e "${BLUE}=== Installing Python dependencies ===${RESET}"
    pip install -q -r "$BACKEND_DIR/requirements.txt" || { echo -e "${RED}Dependency installation failed.${RESET}"; exit 1; }
    echo -e "${GREEN}Dependencies installed.${RESET}"
}

check_index_file() {
    local file="$1"
    local name="$2"
    if [ -f "$file" ]; then
        local size=$(du -h "$file" | cut -f1)
        echo -e "  ${GREEN}[OK]${RESET} $name ($size)"
        return 0
    else
        echo -e "  ${RED}[MISSING]${RESET} $name"
        return 1
    fi
}

check_indexes() {
    echo -e "\n${BLUE}=== Index Files Status ===${RESET}\n"

    local all_ok=true

    echo -e "${CYAN}Core Indexes:${RESET}"
    check_index_file "$INDEXES_DIR/lexicon.txt" "Lexicon" || all_ok=false
    check_index_file "$INDEXES_DIR/forward_index.txt" "Forward Index" || all_ok=false
    check_index_file "$INDEXES_DIR/inverted_index.txt" "Inverted Index" || all_ok=false

    echo -e "\n${CYAN}Barrel Indexes:${RESET}"
    if [ -d "$INDEXES_DIR/barrels" ] && [ "$(ls -A "$INDEXES_DIR/barrels" 2>/dev/null)" ]; then
        local barrel_count=$(ls "$INDEXES_DIR/barrels" | wc -l)
        echo -e "  ${GREEN}[OK]${RESET} Barrels directory ($barrel_count files)"
    else
        echo -e "  ${RED}[MISSING]${RESET} Barrels directory"
        all_ok=false
    fi

    echo -e "\n${CYAN}Semantic Search Indexes:${RESET}"
    check_index_file "$INDEXES_DIR/embeddings/autocomplete.json" "Autocomplete Index"
    check_index_file "$INDEXES_DIR/embeddings/embeddings.bin" "Word Embeddings"
    check_index_file "$INDEXES_DIR/embeddings/word_to_index.json" "Word-to-Index Map"

    echo -e "\n${CYAN}N-gram Indexes:${RESET}"
    check_index_file "$INDEXES_DIR/ngram_autocomplete.json" "N-gram Autocomplete"
    check_index_file "$INDEXES_DIR/bigrams.json" "Bigrams"
    check_index_file "$INDEXES_DIR/trigrams.json" "Trigrams"

    echo -e "\n${CYAN}C++ Executables:${RESET}"
    check_index_file "$CPP_BUILD_DIR/search" "Search Executable"
    check_index_file "$CPP_BUILD_DIR/search_semantic" "Semantic Search Executable"

    echo ""
    if $all_ok; then
        echo -e "${GREEN}All core indexes are present.${RESET}"
        return 0
    else
        echo -e "${YELLOW}Some indexes are missing. Run 'Full Build' or specific build options.${RESET}"
        return 1
    fi
}

build_lexicon() {
    echo -e "${BLUE}=== Building Lexicon ===${RESET}"
    $PYTHON -u "$BACKEND_DIR/py/lexicon.py" || { echo -e "${RED}Lexicon generation failed.${RESET}"; exit 1; }
    echo -e "${GREEN}Lexicon built successfully.${RESET}"
}

build_cpp_indexes() {
    echo -e "${BLUE}=== Building C++ Index Executables ===${RESET}"
    mkdir -p "$CPP_BUILD_DIR"

    echo -e "${YELLOW}Compiling Forward Index...${RESET}"
    g++ -O2 -o "$CPP_BUILD_DIR/forwardIndex" "$BACKEND_DIR/cpp/forwardIndex.cpp" -std=c++17 || { echo -e "${RED}Forward index compilation failed.${RESET}"; exit 1; }

    echo -e "${YELLOW}Compiling Inverted Index...${RESET}"
    g++ -O2 -o "$CPP_BUILD_DIR/invertedIndex" "$BACKEND_DIR/cpp/invertedIndex.cpp" -std=c++17 || { echo -e "${RED}Inverted index compilation failed.${RESET}"; exit 1; }

    echo -e "${YELLOW}Compiling Barrels...${RESET}"
    g++ -O2 -o "$CPP_BUILD_DIR/barrels" "$BACKEND_DIR/cpp/barrels.cpp" -std=c++17 || { echo -e "${RED}Barrels compilation failed.${RESET}"; exit 1; }

    echo -e "${GREEN}C++ executables compiled.${RESET}"
}

run_cpp_indexes() {
    echo -e "${BLUE}=== Running C++ Index Builders ===${RESET}"

    echo -e "${YELLOW}Building Forward Index...${RESET}"
    "$CPP_BUILD_DIR/forwardIndex" || { echo -e "${RED}Forward index run failed.${RESET}"; exit 1; }

    echo -e "${YELLOW}Building Inverted Index...${RESET}"
    "$CPP_BUILD_DIR/invertedIndex" || { echo -e "${RED}Inverted index run failed.${RESET}"; exit 1; }

    echo -e "${YELLOW}Building Barrels...${RESET}"
    "$CPP_BUILD_DIR/barrels" || { echo -e "${RED}Barrels run failed.${RESET}"; exit 1; }

    echo -e "${GREEN}All indexes built successfully.${RESET}"
}

build_search_executables() {
    echo -e "${BLUE}=== Building Search Executables ===${RESET}"
    mkdir -p "$CPP_BUILD_DIR"

    echo -e "${YELLOW}Compiling Search...${RESET}"
    g++ -O2 -o "$CPP_BUILD_DIR/search" "$BACKEND_DIR/cpp/search.cpp" -std=c++17 || { echo -e "${RED}Search compilation failed.${RESET}"; exit 1; }

    echo -e "${YELLOW}Compiling Semantic Search...${RESET}"
    g++ -O2 -o "$CPP_BUILD_DIR/search_semantic" "$BACKEND_DIR/cpp/search_semantic.cpp" -std=c++17 || { echo -e "${RED}Semantic search compilation failed.${RESET}"; exit 1; }

    echo -e "${GREEN}Search executables compiled.${RESET}"
}

build_embeddings() {
    echo -e "${BLUE}=== Building Embeddings & Semantic Search ===${RESET}"
    $PYTHON -u "$BACKEND_DIR/py/embeddings_setup.py" || { echo -e "${RED}Embeddings setup failed.${RESET}"; exit 1; }
    build_search_executables
    echo -e "${GREEN}Embeddings and semantic search ready.${RESET}"
}

build_ngrams() {
    echo -e "${BLUE}=== Building N-gram Index ===${RESET}"
    echo -e "${YELLOW}This may take a few minutes...${RESET}"
    $PYTHON -u "$BACKEND_DIR/py/ngram_builder.py" || { echo -e "${RED}N-gram build failed.${RESET}"; exit 1; }
    echo -e "${GREEN}N-gram index built successfully.${RESET}"
}

start_backend() {
    echo -e "${BLUE}=== Starting Backend API ===${RESET}"

    # Check minimum required indexes
    if [ ! -f "$INDEXES_DIR/lexicon.txt" ]; then
        echo -e "${RED}Error: Lexicon not found. Run 'Full Build' or 'Build Indexes Only' first.${RESET}"
        return 1
    fi

    if [ ! -f "$CPP_BUILD_DIR/search_semantic" ] && [ ! -f "$CPP_BUILD_DIR/search" ]; then
        echo -e "${RED}Error: No search executables found. Run 'Build C++ Executables Only' first.${RESET}"
        return 1
    fi

    echo -e "${GREEN}Starting API server on http://localhost:5000${RESET}"
    echo -e "${YELLOW}Press Ctrl+C to stop${RESET}\n"
    cd "$BACKEND_DIR/py"
    $PYTHON -m uvicorn api:app --host 0.0.0.0 --port 5000 --reload
}

start_frontend() {
    echo -e "${BLUE}=== Starting Frontend ===${RESET}"

    if [ ! -d "$FRONTEND_DIR/node_modules" ]; then
        echo -e "${YELLOW}Installing frontend dependencies...${RESET}"
        cd "$FRONTEND_DIR"
        npm install || { echo -e "${RED}npm install failed.${RESET}"; return 1; }
    fi

    echo -e "${GREEN}Starting frontend on http://localhost:5173${RESET}"
    echo -e "${YELLOW}Press Ctrl+C to stop${RESET}\n"
    cd "$FRONTEND_DIR"
    npm run dev
}

start_server() {
    echo -e "${BLUE}=== Starting MiniGoogle Server ===${RESET}"

    # Quick check for essential files
    echo -e "${YELLOW}Checking indexes...${RESET}"
    local missing=false

    if [ ! -f "$INDEXES_DIR/lexicon.txt" ]; then
        echo -e "${RED}  Missing: lexicon.txt${RESET}"
        missing=true
    fi

    if [ ! -d "$INDEXES_DIR/barrels" ] || [ -z "$(ls -A "$INDEXES_DIR/barrels" 2>/dev/null)" ]; then
        echo -e "${RED}  Missing: barrels${RESET}"
        missing=true
    fi

    if [ ! -f "$CPP_BUILD_DIR/search_semantic" ] && [ ! -f "$CPP_BUILD_DIR/search" ]; then
        echo -e "${RED}  Missing: search executables${RESET}"
        missing=true
    fi

    if $missing; then
        echo -e "\n${RED}Some required files are missing.${RESET}"
        echo -e "${YELLOW}Would you like to run 'Full Build' first? (y/n)${RESET}"
        read -r answer
        if [ "$answer" = "y" ] || [ "$answer" = "Y" ]; then
            full_build
        else
            echo -e "${YELLOW}Attempting to start anyway...${RESET}"
        fi
    else
        echo -e "${GREEN}All required indexes found.${RESET}"
    fi

    # Start backend in background
    echo -e "\n${BLUE}Starting backend...${RESET}"
    cd "$BACKEND_DIR/py"
    $PYTHON -m uvicorn api:app --host 0.0.0.0 --port 5000 &
    BACKEND_PID=$!
    sleep 2

    # Check if backend started
    if ! kill -0 $BACKEND_PID 2>/dev/null; then
        echo -e "${RED}Backend failed to start.${RESET}"
        return 1
    fi
    echo -e "${GREEN}Backend running on http://localhost:5000${RESET}"

    # Start frontend
    echo -e "\n${BLUE}Starting frontend...${RESET}"
    cd "$FRONTEND_DIR"
    if [ ! -d "node_modules" ]; then
        npm install
    fi
    npm run dev &
    FRONTEND_PID=$!

    echo -e "\n${GREEN}${BOLD}MiniGoogle is running!${RESET}"
    echo -e "  Frontend: ${CYAN}http://localhost:5173${RESET}"
    echo -e "  Backend:  ${CYAN}http://localhost:5000${RESET}"
    echo -e "  API Docs: ${CYAN}http://localhost:5000/docs${RESET}"
    echo -e "\n${YELLOW}Press Enter to stop servers...${RESET}"
    read -r

    # Cleanup
    kill $BACKEND_PID 2>/dev/null
    kill $FRONTEND_PID 2>/dev/null
    echo -e "${GREEN}Servers stopped.${RESET}"
}

full_build() {
    echo -e "${BLUE}${BOLD}=== FULL BUILD ===${RESET}"
    echo -e "${YELLOW}This will build everything from scratch.${RESET}\n"

    detect_python
    detect_compiler
    setup_venv
    install_deps

    # Build lexicon
    build_lexicon

    # Build and run C++ index builders
    build_cpp_indexes
    run_cpp_indexes

    # Build search executables
    build_search_executables

    # Build embeddings (optional, may take time)
    echo -e "\n${YELLOW}Build embeddings for semantic search? (y/n)${RESET}"
    read -r answer
    if [ "$answer" = "y" ] || [ "$answer" = "Y" ]; then
        build_embeddings
    fi

    # Build n-grams (optional)
    echo -e "\n${YELLOW}Build n-gram index for multi-word autocomplete? (y/n)${RESET}"
    read -r answer
    if [ "$answer" = "y" ] || [ "$answer" = "Y" ]; then
        build_ngrams
    fi

    echo -e "\n${GREEN}${BOLD}=== BUILD COMPLETE ===${RESET}"
    check_indexes

    echo -e "\n${YELLOW}Start the server now? (y/n)${RESET}"
    read -r answer
    if [ "$answer" = "y" ] || [ "$answer" = "Y" ]; then
        start_server
    fi
}

# ===== Main =====

print_header

# Check if running with argument
if [ $# -gt 0 ]; then
    case "$1" in
        --full)
            detect_python
            setup_venv
            full_build
            ;;
        --server)
            detect_python
            setup_venv
            start_server
            ;;
        --backend)
            detect_python
            setup_venv
            start_backend
            ;;
        --frontend)
            start_frontend
            ;;
        --check)
            check_indexes
            ;;
        --help)
            echo "Usage: ./run.sh [option]"
            echo ""
            echo "Options:"
            echo "  --full      Full build from scratch"
            echo "  --server    Start frontend and backend"
            echo "  --backend   Start backend API only"
            echo "  --frontend  Start frontend only"
            echo "  --check     Check index files status"
            echo "  --help      Show this help"
            echo ""
            echo "Without options, shows interactive menu."
            ;;
        *)
            echo -e "${RED}Unknown option: $1${RESET}"
            echo "Use --help for usage information."
            exit 1
            ;;
    esac
    exit 0
fi

# Interactive menu
while true; do
    print_menu
    echo -n "Enter choice [0-9]: "
    read -r choice

    case $choice in
        1)
            detect_python
            setup_venv
            full_build
            ;;
        2)
            detect_python
            setup_venv
            start_server
            ;;
        3)
            detect_python
            detect_compiler
            setup_venv
            install_deps
            build_lexicon
            build_cpp_indexes
            run_cpp_indexes
            echo -e "\n${GREEN}Indexes built successfully.${RESET}"
            ;;
        4)
            detect_compiler
            build_cpp_indexes
            build_search_executables
            echo -e "\n${GREEN}C++ executables built.${RESET}"
            ;;
        5)
            detect_python
            setup_venv
            install_deps
            build_embeddings
            ;;
        6)
            detect_python
            setup_venv
            install_deps
            build_ngrams
            ;;
        7)
            start_frontend
            ;;
        8)
            detect_python
            setup_venv
            start_backend
            ;;
        9)
            check_indexes
            ;;
        0)
            echo -e "${GREEN}Goodbye!${RESET}"
            exit 0
            ;;
        *)
            echo -e "${RED}Invalid option. Please try again.${RESET}"
            ;;
    esac

    echo -e "\n${YELLOW}Press Enter to continue...${RESET}"
    read -r
    clear
    print_header
done
