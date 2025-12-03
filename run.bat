@echo off
REM === MiniGoogle-DSA Build Script (Windows CMD) ===

echo === MiniGoogle-DSA Build Script (Windows) ===

REM --- Detect Python ---
where python >nul 2>nul
IF %ERRORLEVEL%==0 (
    set PYTHON=python
) ELSE (
    echo Error: Python not found.
    exit /b 1
)

REM --- Detect C++ Compiler ---
where g++ >nul 2>nul
IF %ERRORLEVEL%==0 (
    set COMPILER=g++
    set USE_CL=0
) ELSE (
    where cl >nul 2>nul
    IF %ERRORLEVEL%==0 (
        set COMPILER=cl
        set USE_CL=1
    ) ELSE (
        echo Error: No C++ compiler found (g++ or cl)
        exit /b 1
    )
)

echo Using Python: %PYTHON%
echo Using C++ Compiler: %COMPILER%

REM --- Setup Python virtual environment ---
if not exist ".venv" (
    echo Creating virtual environment...
    %PYTHON% -m venv .venv
    IF ERRORLEVEL 1 (
        echo Failed to create virtual environment.
        exit /b 1
    )
) ELSE (
    echo Virtual environment already exists.
)

call .venv\Scripts\activate.bat
IF ERRORLEVEL 1 (
    echo Failed to activate virtual environment.
    exit /b 1
)

REM --- Install Python dependencies ---
echo Installing Python dependencies...
pip install -r backend\requirements.txt
IF ERRORLEVEL 1 (
    echo Dependency installation failed.
    exit /b 1
)

REM --- Run Lexicon script ---
echo Running Lexicon Script...
%PYTHON% -u backend\py\lexicon.py
IF ERRORLEVEL 1 (
    echo Lexicon generation failed.
    exit /b 1
)

REM --- Build Forward Index ---
echo Building Forward Index...
IF %USE_CL%==0 (
    g++ -o forwardIndex.exe backend\cpp\forwardIndex.cpp backend\cpp\config.cpp -std=c++17
) ELSE (
    cl /EHsc /std:c++17 backend\cpp\forwardIndex.cpp backend\cpp\config.cpp
)
IF ERRORLEVEL 1 (
    echo Forward index compilation failed.
    exit /b 1
)
forwardIndex.exe
IF ERRORLEVEL 1 (
    echo Forward index run failed.
    exit /b 1
)

REM --- Build Inverted Index ---
echo Building Inverted Index...
IF %USE_CL%==0 (
    g++ -o invertedIndex.exe backend\cpp\invertedIndex.cpp backend\cpp\config.cpp -std=c++17
) ELSE (
    cl /EHsc /std:c++17 backend\cpp\invertedIndex.cpp backend\cpp\config.cpp
)
IF ERRORLEVEL 1 (
    echo Inverted index compilation failed.
    exit /b 1
)
invertedIndex.exe
IF ERRORLEVEL 1 (
    echo Inverted index run failed.
    exit /b 1
)

REM --- Deactivate Python virtual environment ---
call .venv\Scripts\deactivate.bat
IF ERRORLEVEL 1 (
    echo Failed to deactivate virtual environment.
    exit /b 1
)

echo All steps completed successfully!
