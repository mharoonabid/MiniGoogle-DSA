@echo off
setlocal EnableDelayedExpansion

REM =====================================
REM MiniGoogle-DSA Windows Automation
REM =====================================

REM ===== Paths =====
set SCRIPT_DIR=%~dp0
set SCRIPT_DIR=%SCRIPT_DIR:~0,-1%

set BACKEND_DIR=%SCRIPT_DIR%\backend
set FRONTEND_DIR=%SCRIPT_DIR%\frontend
set INDEXES_DIR=%BACKEND_DIR%\indexes
set CPP_BUILD_DIR=%BACKEND_DIR%\cpp\build
set VENV_DIR=%SCRIPT_DIR%\.venv

REM ===== Utility =====

:print_header
echo.
echo ======================================
echo   MiniGoogle-DSA
echo ======================================
echo.
exit /b

:print_menu
echo Select an option:
echo.
echo   1) Full Build (Build everything from scratch)
echo   2) Start Server Only (Use existing indexes)
echo   3) Build Indexes Only
echo   4) Build C++ Executables Only
echo   5) Build Embeddings & Semantic Search
echo   6) Build N-gram Index
echo   7) Start Frontend Only
echo   8) Start Backend API Only
echo   9) Check Index Files Status
echo   0) Exit
echo.
exit /b

:detect_python
where python >nul 2>nul
if errorlevel 1 (
    echo ERROR: Python not found in PATH.
    exit /b 1
)
set PYTHON=python
echo Using Python: %PYTHON%
exit /b

:detect_compiler
where g++ >nul 2>nul
if errorlevel 1 (
    echo ERROR: g++ compiler not found.
    exit /b 1
)
echo Using C++ Compiler: g++
exit /b

:setup_venv
echo === Setting up Python virtual environment ===
if not exist "%VENV_DIR%" (
    echo Creating virtual environment...
    %PYTHON% -m venv "%VENV_DIR%" || exit /b 1
) else (
    echo Virtual environment already exists.
)
call "%VENV_DIR%\Scripts\activate.bat" || exit /b 1
exit /b

:install_deps
echo === Installing Python dependencies ===
pip install -r "%BACKEND_DIR%\requirements.txt" || exit /b 1
echo Dependencies installed.
exit /b

:check_file
if exist "%~1" (
    echo   [OK] %~2
) else (
    echo   [MISSING] %~2
    set MISSING=true
)
exit /b

:check_indexes
echo.
echo === Index Files Status ===
set MISSING=false

echo.
echo Core Indexes:
call :check_file "%INDEXES_DIR%\lexicon.txt" "Lexicon"
call :check_file "%INDEXES_DIR%\forward_index.txt" "Forward Index"
call :check_file "%INDEXES_DIR%\inverted_index.txt" "Inverted Index"

echo.
echo Barrel Indexes:
if exist "%INDEXES_DIR%\barrels" (
    dir "%INDEXES_DIR%\barrels" >nul 2>nul && echo   [OK] Barrels directory
) else (
    echo   [MISSING] Barrels directory
    set MISSING=true
)

echo.
echo Semantic Search Indexes:
call :check_file "%INDEXES_DIR%\embeddings\autocomplete.json" "Autocomplete"
call :check_file "%INDEXES_DIR%\embeddings\embeddings.bin" "Embeddings"
call :check_file "%INDEXES_DIR%\embeddings\word_to_index.json" "Word-to-Index"

echo.
echo N-gram Indexes:
call :check_file "%INDEXES_DIR%\ngram_autocomplete.json" "N-gram Autocomplete"
call :check_file "%INDEXES_DIR%\bigrams.json" "Bigrams"
call :check_file "%INDEXES_DIR%\trigrams.json" "Trigrams"

echo.
echo C++ Executables:
call :check_file "%CPP_BUILD_DIR%\search.exe" "Search Executable"
call :check_file "%CPP_BUILD_DIR%\search_semantic.exe" "Semantic Search"

echo.
if "%MISSING%"=="false" (
    echo All core indexes are present.
) else (
    echo Some indexes are missing.
)
exit /b

:build_lexicon
echo === Building Lexicon ===
%PYTHON% "%BACKEND_DIR%\py\lexicon.py" || exit /b 1
exit /b

:build_cpp_indexes
echo === Building C++ Index Executables ===
if not exist "%CPP_BUILD_DIR%" mkdir "%CPP_BUILD_DIR%"

g++ -O2 -std=c++17 -o "%CPP_BUILD_DIR%\forwardIndex.exe" "%BACKEND_DIR%\cpp\forwardIndex.cpp" || exit /b 1
g++ -O2 -std=c++17 -o "%CPP_BUILD_DIR%\invertedIndex.exe" "%BACKEND_DIR%\cpp\invertedIndex.cpp" || exit /b 1
g++ -O2 -std=c++17 -o "%CPP_BUILD_DIR%\barrels.exe" "%BACKEND_DIR%\cpp\barrels.cpp" || exit /b 1

exit /b

:run_cpp_indexes
echo === Running C++ Index Builders ===
"%CPP_BUILD_DIR%\forwardIndex.exe" || exit /b 1
"%CPP_BUILD_DIR%\invertedIndex.exe" || exit /b 1
"%CPP_BUILD_DIR%\barrels.exe" || exit /b 1
exit /b

:build_search_executables
echo === Building Search Executables ===
g++ -O2 -std=c++17 -o "%CPP_BUILD_DIR%\search.exe" "%BACKEND_DIR%\cpp\search.cpp" || exit /b 1
g++ -O2 -std=c++17 -o "%CPP_BUILD_DIR%\search_semantic.exe" "%BACKEND_DIR%\cpp\search_semantic.cpp" || exit /b 1
exit /b

:build_embeddings
echo === Building Embeddings ===
%PYTHON% "%BACKEND_DIR%\py\embeddings_setup.py" || exit /b 1
call :build_search_executables
exit /b

:build_ngrams
echo === Building N-gram Index ===
%PYTHON% "%BACKEND_DIR%\py\ngram_builder.py" || exit /b 1
exit /b

:start_backend
echo === Starting Backend API ===
cd /d "%BACKEND_DIR%\py"
%PYTHON% -m uvicorn api:app --host 0.0.0.0 --port 5000 --reload
exit /b

:start_frontend
echo === Starting Frontend ===
cd /d "%FRONTEND_DIR%"
if not exist node_modules (
    npm install || exit /b 1
)
npm run dev
exit /b

:start_server
echo === Starting MiniGoogle Server ===
start cmd /k "%VENV_DIR%\Scripts\activate.bat && cd /d %BACKEND_DIR%\py && python -m uvicorn api:app --host 0.0.0.0 --port 5000"
timeout /t 3 >nul
start cmd /k "cd /d %FRONTEND_DIR% && npm run dev"
exit /b

:full_build
call :detect_python
call :detect_compiler
call :setup_venv
call :install_deps
call :build_lexicon
call :build_cpp_indexes
call :run_cpp_indexes
call :build_search_executables
call :check_indexes
exit /b

REM ===== Main =====
call :print_header

:menu_loop
call :print_menu
set /p CHOICE=Enter choice [0-9]:

if "%CHOICE%"=="1" call :full_build
if "%CHOICE%"=="2" call :start_server
if "%CHOICE%"=="3" (
    call :detect_python
    call :detect_compiler
    call :setup_venv
    call :install_deps
    call :build_lexicon
    call :build_cpp_indexes
    call :run_cpp_indexes
)
if "%CHOICE%"=="4" (
    call :detect_compiler
    call :build_cpp_indexes
    call :build_search_executables
)
if "%CHOICE%"=="5" (
    call :detect_python
    call :setup_venv
    call :install_deps
    call :build_embeddings
)
if "%CHOICE%"=="6" (
    call :detect_python
    call :setup_venv
    call :install_deps
    call :build_ngrams
)
if "%CHOICE%"=="7" call :start_frontend
if "%CHOICE%"=="8" (
    call :detect_python
    call :setup_venv
    call :start_backend
)
if "%CHOICE%"=="9" call :check_indexes
if "%CHOICE%"=="0" exit

echo.
pause
cls
call :print_header
goto menu_loop
