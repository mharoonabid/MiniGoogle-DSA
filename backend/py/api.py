"""
MiniGoogle Semantic Search API

FastAPI service with semantic search, autocomplete, and PageRank.

Endpoints:
    GET  /search?q=<query>&mode=<and|or>&semantic=<true|false>
    GET  /autocomplete?prefix=<prefix>
    GET  /similar?word=<word>
    GET  /health

Usage:
    uvicorn api:app --reload --port 5000
    python api.py --port 5000
"""

import subprocess
import re
import argparse
import json
from pathlib import Path
from typing import Optional, List
from enum import Enum

from fastapi import FastAPI, Query, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

# ==================== Pydantic Models ====================

class WordInfo(BaseModel):
    word: str
    lemma_id: int
    df: int
    barrel: int

class AutocompleteSuggestion(BaseModel):
    word: str
    df: int

class SimilarWord(BaseModel):
    word: str
    similarity: float

class SearchResult(BaseModel):
    rank: int
    doc_id: str
    score: float
    tfidf_score: Optional[float] = None
    pagerank_score: Optional[float] = None
    matched_terms: Optional[int] = None
    total_terms: Optional[int] = None
    tf: Optional[int] = None
    tfidf: Optional[float] = None
    term_frequencies: Optional[List[int]] = None

class ExpandedTerm(BaseModel):
    word: str
    lemma_id: int
    weight: float

class SearchResponse(BaseModel):
    success: bool
    query: str
    query_type: str
    mode: Optional[str] = None
    semantic: Optional[bool] = None
    error: Optional[str] = None
    expanded_terms: Optional[List[ExpandedTerm]] = None
    search_time_ms: Optional[int] = None
    result_count: Optional[int] = None
    results: Optional[List[SearchResult]] = None

class AutocompleteResponse(BaseModel):
    success: bool
    prefix: str
    suggestions: List[AutocompleteSuggestion]
    time_ms: int

class SimilarWordsResponse(BaseModel):
    success: bool
    word: str
    similar_words: List[SimilarWord]
    time_ms: int

class QueryMode(str, Enum):
    AND = "and"
    OR = "or"

# ==================== FastAPI App ====================

app = FastAPI(
    title="MiniGoogle Semantic Search API",
    description="Search API with semantic search, autocomplete, and PageRank",
    version="2.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ==================== Executable Paths ====================

SEARCH_EXECUTABLE = None
SEMANTIC_SEARCH_EXECUTABLE = None
NGRAM_INDEX = None

def get_executables():
    """Find search executables."""
    script_dir = Path(__file__).parent.resolve()
    backend_dir = script_dir.parent
    build_dir = backend_dir / "cpp" / "build"

    return {
        "search": build_dir / "search",
        "semantic": build_dir / "search_semantic"
    }

def load_ngram_index():
    """Load n-gram autocomplete index."""
    script_dir = Path(__file__).parent.resolve()
    backend_dir = script_dir.parent
    indexes_dir = backend_dir / "indexes"
    ngram_file = indexes_dir / "ngram_autocomplete.json"

    if ngram_file.exists():
        with open(ngram_file, 'r', encoding='utf-8') as f:
            return json.load(f)
    return None

@app.on_event("startup")
async def startup_event():
    """Initialize on startup."""
    global SEARCH_EXECUTABLE, SEMANTIC_SEARCH_EXECUTABLE, NGRAM_INDEX

    exes = get_executables()

    if exes["search"].exists():
        SEARCH_EXECUTABLE = str(exes["search"])
        print(f"Basic search: {SEARCH_EXECUTABLE}")

    if exes["semantic"].exists():
        SEMANTIC_SEARCH_EXECUTABLE = str(exes["semantic"])
        print(f"Semantic search: {SEMANTIC_SEARCH_EXECUTABLE}")

    if not SEARCH_EXECUTABLE and not SEMANTIC_SEARCH_EXECUTABLE:
        print("Warning: No search executables found!")

    # Load n-gram index for multi-word autocomplete
    NGRAM_INDEX = load_ngram_index()
    if NGRAM_INDEX:
        print(f"Loaded n-gram index with {len(NGRAM_INDEX)} prefixes")
    else:
        print("Warning: N-gram index not found. Run ngram_builder.py first for multi-word autocomplete.")

# ==================== Output Parsers ====================

def parse_semantic_search_output(output: str) -> dict:
    """Parse semantic search output."""
    results = []
    expanded_terms = []
    search_time = None
    mode = "AND"

    lines = output.strip().split('\n')

    in_expansion = False

    for line in lines:
        # Mode detection
        if "AND mode" in line:
            mode = "AND"
        elif "OR mode" in line:
            mode = "OR"

        # Query expansion parsing
        if "Query expansion" in line:
            in_expansion = True
            continue

        if in_expansion and line.strip().startswith("  "):
            # Parse: "  word (lemma=123, weight=0.5)"
            match = re.match(r'\s+(\w+) \(lemma=(\d+), weight=([\d.]+)\)', line)
            if match:
                expanded_terms.append({
                    "word": match.group(1),
                    "lemma_id": int(match.group(2)),
                    "weight": float(match.group(3))
                })
            continue
        else:
            in_expansion = False

        # Search time
        if "results (in" in line:
            match = re.search(r'in (\d+)ms', line)
            if match:
                search_time = int(match.group(1))

        # Results parsing
        # "1. DocID: PMC7326321 | Score: 4.1198 | TF-IDF: 3.5 | PageRank: 0.6 | Matched: 2/2"
        if line and line[0].isdigit() and ". DocID:" in line:
            match = re.match(
                r'(\d+)\. DocID: (\S+) \| Score: ([\d.]+) \| TF-IDF: ([\d.]+) \| PageRank: ([\d.]+) \| Matched: (\d+)/(\d+)',
                line
            )
            if match:
                results.append({
                    "rank": int(match.group(1)),
                    "doc_id": match.group(2),
                    "score": float(match.group(3)),
                    "tfidf_score": float(match.group(4)),
                    "pagerank_score": float(match.group(5)),
                    "matched_terms": int(match.group(6)),
                    "total_terms": int(match.group(7))
                })

    return {
        "query_type": "semantic",
        "mode": mode,
        "expanded_terms": expanded_terms,
        "search_time_ms": search_time,
        "result_count": len(results),
        "results": results
    }

def parse_autocomplete_output(output: str) -> dict:
    """Parse autocomplete output."""
    suggestions = []
    time_ms = 0

    lines = output.strip().split('\n')

    for line in lines:
        # Parse: "1. word (df: 123)"
        match = re.match(r'(\d+)\. (\w+) \(df: (\d+)\)', line)
        if match:
            suggestions.append({
                "word": match.group(2),
                "df": int(match.group(3))
            })

        # Time
        if "Autocomplete time:" in line:
            match = re.search(r'(\d+)ms', line)
            if match:
                time_ms = int(match.group(1))

    return {
        "suggestions": suggestions,
        "time_ms": time_ms
    }

def parse_similar_output(output: str) -> dict:
    """Parse similar words output."""
    similar_words = []
    time_ms = 0

    lines = output.strip().split('\n')

    for line in lines:
        # Parse: "1. word (similarity: 0.85)"
        match = re.match(r'(\d+)\. (\w+) \(similarity: ([\d.]+)\)', line)
        if match:
            similar_words.append({
                "word": match.group(2),
                "similarity": float(match.group(3))
            })

        # Time
        if "Similar words time:" in line:
            match = re.search(r'(\d+)ms', line)
            if match:
                time_ms = int(match.group(1))

    return {
        "similar_words": similar_words,
        "time_ms": time_ms
    }

def parse_basic_search_output(output: str, is_multi: bool) -> dict:
    """Parse basic (non-semantic) search output."""
    results = []
    search_time = None
    mode = "AND"
    df = None
    lemma_id = None
    barrel = None

    lines = output.strip().split('\n')

    for line in lines:
        if "AND mode" in line:
            mode = "AND"
        elif "OR mode" in line:
            mode = "OR"

        if line.startswith("Lemma ID:"):
            lemma_id = int(line.split(":")[1].strip())
        elif line.startswith("Barrel:"):
            barrel = int(line.split(":")[1].strip())
        elif line.startswith("Document frequency"):
            match = re.search(r'\d+', line.split(":")[1])
            if match:
                df = int(match.group())

        if "results" in line and "in " in line:
            match = re.search(r'in (\d+)ms', line)
            if match:
                search_time = int(match.group(1))

        # Single word result
        if line and line[0].isdigit() and ". DocID:" in line and "TF-IDF:" in line:
            match = re.match(r'(\d+)\. DocID: (\S+) \| tf: (\d+) \| TF-IDF: ([\d.]+)', line)
            if match:
                results.append({
                    "rank": int(match.group(1)),
                    "doc_id": match.group(2),
                    "tf": int(match.group(3)),
                    "tfidf": float(match.group(4)),
                    "score": float(match.group(4))
                })

        # Multi-word result
        if line and line[0].isdigit() and "Score:" in line and "TFs:" in line:
            match = re.match(r'(\d+)\. DocID: (\S+) \| Score: ([\d.]+) \| Matched: (\d+)/(\d+) \| TFs: \[([\d,]+)\]', line)
            if match:
                tfs = [int(x) for x in match.group(6).split(',')]
                results.append({
                    "rank": int(match.group(1)),
                    "doc_id": match.group(2),
                    "score": float(match.group(3)),
                    "matched_terms": int(match.group(4)),
                    "total_terms": int(match.group(5)),
                    "term_frequencies": tfs
                })

    return {
        "query_type": "multi" if is_multi else "single",
        "mode": mode,
        "lemma_id": lemma_id,
        "barrel": barrel,
        "document_frequency": df,
        "search_time_ms": search_time,
        "result_count": len(results),
        "results": results
    }

# ==================== Search Functions ====================

def run_semantic_search(query: str, mode: str = "and") -> dict:
    """Run semantic search."""
    if not SEMANTIC_SEARCH_EXECUTABLE:
        return {
            "success": False,
            "error": "Semantic search not available. Run embeddings_setup.py first.",
            "query": query,
            "query_type": "semantic"
        }

    cmd = [SEMANTIC_SEARCH_EXECUTABLE, query]
    if mode.lower() == "or":
        cmd.append("--or")
    else:
        cmd.append("--and")

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)

        if result.returncode != 0:
            return {
                "success": False,
                "error": result.stderr or "Search failed",
                "query": query,
                "query_type": "semantic"
            }

        parsed = parse_semantic_search_output(result.stdout)
        parsed["success"] = True
        parsed["query"] = query
        parsed["semantic"] = True

        return parsed

    except subprocess.TimeoutExpired:
        return {"success": False, "error": "Search timed out", "query": query, "query_type": "semantic"}
    except Exception as e:
        return {"success": False, "error": str(e), "query": query, "query_type": "semantic"}

def run_basic_search(query: str, mode: str = "and") -> dict:
    """Run basic keyword search."""
    if not SEARCH_EXECUTABLE:
        return {
            "success": False,
            "error": "Search executable not found",
            "query": query,
            "query_type": "unknown"
        }

    cmd = [SEARCH_EXECUTABLE, query]
    if mode.lower() == "or":
        cmd.append("--or")
    else:
        cmd.append("--and")

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)

        if result.returncode != 0:
            return {
                "success": False,
                "error": result.stderr or "Search failed",
                "query": query,
                "query_type": "unknown"
            }

        is_multi = len(query.split()) > 1
        parsed = parse_basic_search_output(result.stdout, is_multi)
        parsed["success"] = True
        parsed["query"] = query
        parsed["semantic"] = False

        return parsed

    except subprocess.TimeoutExpired:
        return {"success": False, "error": "Search timed out", "query": query, "query_type": "unknown"}
    except Exception as e:
        return {"success": False, "error": str(e), "query": query, "query_type": "unknown"}

def run_autocomplete(prefix: str) -> dict:
    """Get autocomplete suggestions with multi-word support."""
    prefix = prefix.strip().lower()

    # Check if prefix contains spaces (multi-word)
    if ' ' in prefix and NGRAM_INDEX:
        # Multi-word autocomplete using n-gram index
        suggestions = []

        # Look up exact prefix match
        if prefix in NGRAM_INDEX:
            for item in NGRAM_INDEX[prefix]:
                suggestions.append({
                    "word": item["phrase"],
                    "df": item["count"]
                })

        # If no exact match, try partial match on last word
        if not suggestions:
            words = prefix.split()
            # Try progressively shorter prefixes
            for i in range(len(prefix), len(words[0]), -1):
                test_prefix = prefix[:i]
                if test_prefix in NGRAM_INDEX:
                    for item in NGRAM_INDEX[test_prefix]:
                        suggestions.append({
                            "word": item["phrase"],
                            "df": item["count"]
                        })
                    break

        return {
            "success": True,
            "prefix": prefix,
            "suggestions": suggestions[:5],
            "time_ms": 1  # Fast lookup from index
        }

    # Single-word autocomplete using C++ executable
    if not SEMANTIC_SEARCH_EXECUTABLE:
        return {"success": False, "error": "Autocomplete not available", "prefix": prefix}

    cmd = [SEMANTIC_SEARCH_EXECUTABLE, "--autocomplete", prefix]

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)

        if result.returncode != 0:
            return {"success": False, "error": result.stderr or "Failed", "prefix": prefix}

        parsed = parse_autocomplete_output(result.stdout)
        parsed["success"] = True
        parsed["prefix"] = prefix

        return parsed

    except Exception as e:
        return {"success": False, "error": str(e), "prefix": prefix}

def run_similar(word: str) -> dict:
    """Find similar words."""
    if not SEMANTIC_SEARCH_EXECUTABLE:
        return {"success": False, "error": "Similar words not available", "word": word}

    cmd = [SEMANTIC_SEARCH_EXECUTABLE, "--similar", word]

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)

        if result.returncode != 0:
            return {"success": False, "error": result.stderr or "Failed", "word": word}

        parsed = parse_similar_output(result.stdout)
        parsed["success"] = True
        parsed["word"] = word

        return parsed

    except Exception as e:
        return {"success": False, "error": str(e), "word": word}

# ==================== API Endpoints ====================

@app.get("/search", tags=["Search"])
async def search(
    q: str = Query(..., description="Search query", min_length=1),
    mode: QueryMode = Query(QueryMode.AND, description="AND/OR mode"),
    semantic: bool = Query(True, description="Enable semantic search")
):
    """
    Search for documents.

    - **q**: Search query (required)
    - **mode**: 'and' or 'or' for multi-word queries
    - **semantic**: Enable semantic search with query expansion (default: true)
    """
    query = q.strip()

    if semantic and SEMANTIC_SEARCH_EXECUTABLE:
        result = run_semantic_search(query, mode.value)
    else:
        result = run_basic_search(query, mode.value)

    if not result["success"]:
        raise HTTPException(status_code=500, detail=result.get("error", "Search failed"))

    return result

@app.get("/autocomplete", response_model=AutocompleteResponse, tags=["Autocomplete"])
async def autocomplete(
    prefix: str = Query(..., description="Prefix to autocomplete", min_length=1)
):
    """
    Get autocomplete suggestions for a prefix.

    Returns up to 5 suggestions ranked by document frequency.
    """
    result = run_autocomplete(prefix.strip().lower())

    if not result["success"]:
        raise HTTPException(status_code=500, detail=result.get("error", "Autocomplete failed"))

    return result

@app.get("/similar", response_model=SimilarWordsResponse, tags=["Semantic"])
async def similar_words(
    word: str = Query(..., description="Word to find similar words for", min_length=1)
):
    """
    Find semantically similar words using word embeddings.

    Returns up to 10 similar words with cosine similarity scores.
    """
    result = run_similar(word.strip().lower())

    if not result["success"]:
        raise HTTPException(status_code=500, detail=result.get("error", "Similar words failed"))

    return result

@app.get("/health", tags=["Health"])
async def health():
    """Health check endpoint."""
    exes = get_executables()
    return {
        "status": "healthy",
        "service": "MiniGoogle Semantic Search API",
        "features": {
            "basic_search": exes["search"].exists(),
            "semantic_search": exes["semantic"].exists(),
            "autocomplete": exes["semantic"].exists(),
            "similar_words": exes["semantic"].exists()
        }
    }

@app.get("/", tags=["Info"])
async def root():
    """API documentation."""
    return {
        "service": "MiniGoogle Semantic Search API",
        "version": "2.0.0",
        "docs": "/docs",
        "endpoints": {
            "/search": "Search with semantic expansion and PageRank",
            "/autocomplete": "Get autocomplete suggestions",
            "/similar": "Find semantically similar words",
            "/health": "Health check"
        }
    }

# ==================== Main ====================

if __name__ == '__main__':
    import uvicorn

    parser = argparse.ArgumentParser(description='MiniGoogle Semantic Search API')
    parser.add_argument('--port', type=int, default=5000)
    parser.add_argument('--host', type=str, default='0.0.0.0')
    parser.add_argument('--reload', action='store_true')
    args = parser.parse_args()

    print(f"\nMiniGoogle Semantic Search API")
    print(f"==============================")
    print(f"Running on http://{args.host}:{args.port}")
    print(f"API Docs: http://{args.host}:{args.port}/docs")
    print()

    uvicorn.run("api:app", host=args.host, port=args.port, reload=args.reload)
