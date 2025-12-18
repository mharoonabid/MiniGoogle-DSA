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

from fastapi import FastAPI, Query, HTTPException, UploadFile, File, Form
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
    title: Optional[str] = None
    authors: Optional[List[str]] = None
    abstract: Optional[str] = None
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

class DocumentUploadResponse(BaseModel):
    success: bool
    doc_id: Optional[str] = None
    title: Optional[str] = None
    total_terms: Optional[int] = None
    unique_terms: Optional[int] = None
    new_terms_added: Optional[int] = None
    indexing_time_ms: Optional[int] = None
    error: Optional[str] = None

class DocumentTextRequest(BaseModel):
    title: str = ""
    abstract: str = ""
    body: str = ""
    authors: Optional[List[str]] = None
    doc_id: Optional[str] = None

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
DOC_METADATA = None
AUTOCOMPLETE_INDEX = None  # Single-word autocomplete index loaded in memory

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

def load_autocomplete_index():
    """Load single-word autocomplete index for fast in-memory lookups."""
    script_dir = Path(__file__).parent.resolve()
    backend_dir = script_dir.parent
    indexes_dir = backend_dir / "indexes" / "embeddings"
    autocomplete_file = indexes_dir / "autocomplete.json"

    if autocomplete_file.exists():
        with open(autocomplete_file, 'r', encoding='utf-8') as f:
            return json.load(f)
    return None

def load_doc_metadata():
    """Load document metadata (titles, authors, abstracts)."""
    from mock_metadata import generate_metadata

    script_dir = Path(__file__).parent.resolve()
    backend_dir = script_dir.parent
    indexes_dir = backend_dir / "indexes"
    metadata_file = indexes_dir / "document_metadata.json"

    if metadata_file.exists():
        with open(metadata_file, 'r', encoding='utf-8') as f:
            return json.load(f)

    # Return function to generate on-the-fly if file doesn't exist
    return generate_metadata

@app.on_event("startup")
async def startup_event():
    """Initialize on startup."""
    global SEARCH_EXECUTABLE, SEMANTIC_SEARCH_EXECUTABLE, NGRAM_INDEX, DOC_METADATA, AUTOCOMPLETE_INDEX

    exes = get_executables()

    if exes["search"].exists():
        SEARCH_EXECUTABLE = str(exes["search"])
        print(f"Basic search: {SEARCH_EXECUTABLE}")

    if exes["semantic"].exists():
        SEMANTIC_SEARCH_EXECUTABLE = str(exes["semantic"])
        print(f"Semantic search: {SEMANTIC_SEARCH_EXECUTABLE}")

    if not SEARCH_EXECUTABLE and not SEMANTIC_SEARCH_EXECUTABLE:
        print("Warning: No search executables found!")

    # Load single-word autocomplete index (fast in-memory lookups)
    AUTOCOMPLETE_INDEX = load_autocomplete_index()
    if AUTOCOMPLETE_INDEX:
        print(f"Loaded autocomplete index with {len(AUTOCOMPLETE_INDEX)} prefixes")
    else:
        print("Warning: Autocomplete index not found. Will fallback to C++ subprocess.")

    # Load n-gram index for multi-word autocomplete
    NGRAM_INDEX = load_ngram_index()
    if NGRAM_INDEX:
        print(f"Loaded n-gram index with {len(NGRAM_INDEX)} prefixes")
    else:
        print("Warning: N-gram index not found. Run ngram_builder.py first for multi-word autocomplete.")

    # Load document metadata
    DOC_METADATA = load_doc_metadata()
    if callable(DOC_METADATA):
        print("Document metadata: Using on-the-fly generation (mock mode)")
    elif DOC_METADATA:
        print(f"Loaded metadata for {len(DOC_METADATA)} documents")
    else:
        print("Warning: Document metadata not available")

# ==================== Output Parsers ====================

def enrich_result_with_metadata(result: dict) -> dict:
    """Add title, authors, and abstract to a search result."""
    doc_id = result.get("doc_id", "")

    if not doc_id:
        return result

    # Get metadata
    if callable(DOC_METADATA):
        # Generate on-the-fly (mock mode)
        metadata = DOC_METADATA(doc_id)
    elif DOC_METADATA and doc_id in DOC_METADATA:
        # Load from database
        metadata = DOC_METADATA[doc_id]
    else:
        # No metadata available
        return result

    # Add metadata fields
    result["title"] = metadata.get("title", "")
    result["authors"] = metadata.get("authors", [])
    result["abstract"] = metadata.get("abstract", "")

    return result

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

    # Enrich results with metadata
    enriched_results = [enrich_result_with_metadata(r) for r in results]

    return {
        "query_type": "semantic",
        "mode": mode,
        "expanded_terms": expanded_terms,
        "search_time_ms": search_time,
        "result_count": len(enriched_results),
        "results": enriched_results
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

    # Enrich results with metadata
    enriched_results = [enrich_result_with_metadata(r) for r in results]

    return {
        "query_type": "multi" if is_multi else "single",
        "mode": mode,
        "lemma_id": lemma_id,
        "barrel": barrel,
        "document_frequency": df,
        "search_time_ms": search_time,
        "result_count": len(enriched_results),
        "results": enriched_results
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
    original_prefix = prefix.lower()
    prefix_stripped = original_prefix.strip()
    has_trailing_space = original_prefix.endswith(' ')

    # Check if this is a multi-word query
    words = prefix_stripped.split()
    is_multi_word = len(words) > 1 or (len(words) == 1 and has_trailing_space)

    if is_multi_word:
        # For multi-word queries, we have two approaches:
        # 1. Try n-gram index for phrase completions
        # 2. Fall back to single-word completion for the last word

        suggestions = []
        seen = set()

        # First try n-gram index for phrase completions
        if NGRAM_INDEX:
            # Case 1: Direct lookup (e.g., "covid v" -> look up "covid v")
            if prefix_stripped in NGRAM_INDEX:
                for item in NGRAM_INDEX[prefix_stripped]:
                    phrase = item["phrase"]
                    if phrase not in seen:
                        suggestions.append({"word": phrase, "df": item["count"]})
                        seen.add(phrase)

            # Case 2: User typed trailing space (e.g., "covid " -> look up "covid")
            if not suggestions and has_trailing_space:
                first_word = prefix_stripped
                if first_word in NGRAM_INDEX:
                    for item in NGRAM_INDEX[first_word]:
                        phrase = item["phrase"]
                        if phrase != first_word and phrase not in seen:
                            suggestions.append({"word": phrase, "df": item["count"]})
                            seen.add(phrase)

            # Case 3: Try partial match on first word
            if not suggestions and len(words) >= 1:
                first_word = words[0]
                if first_word in NGRAM_INDEX:
                    for item in NGRAM_INDEX[first_word]:
                        phrase = item["phrase"]
                        if phrase.startswith(prefix_stripped) and phrase not in seen:
                            suggestions.append({"word": phrase, "df": item["count"]})
                            seen.add(phrase)

        # If n-gram didn't find anything, fall back to single-word completion for last word
        if not suggestions and AUTOCOMPLETE_INDEX:
            # Extract prefix of previous words and the current word being typed
            if has_trailing_space:
                # User just typed space, waiting for next word
                prev_words = prefix_stripped
                current_word_prefix = ""
            else:
                # User is typing a word
                prev_words = " ".join(words[:-1])
                current_word_prefix = words[-1]

            # Get suggestions for the current word
            if current_word_prefix and len(current_word_prefix) >= 1:
                word_suggestions = []

                # Try 2-character prefix lookup
                if len(current_word_prefix) >= 2:
                    prefix_key = current_word_prefix[:2]
                    if prefix_key in AUTOCOMPLETE_INDEX:
                        for item in AUTOCOMPLETE_INDEX[prefix_key]:
                            word = item.get("w", "")
                            if word.startswith(current_word_prefix):
                                word_suggestions.append({
                                    "word": word,
                                    "df": item.get("d", 0)
                                })
                                if len(word_suggestions) >= 5:
                                    break

                # Also try single character if we have few results
                if len(word_suggestions) < 5 and len(current_word_prefix) >= 1:
                    prefix_key = current_word_prefix[:2] if len(current_word_prefix) >= 2 else current_word_prefix[0]
                    # Try 3-char prefix
                    if len(current_word_prefix) >= 3:
                        prefix_key = current_word_prefix[:3]
                        if prefix_key in AUTOCOMPLETE_INDEX:
                            existing = {s["word"] for s in word_suggestions}
                            for item in AUTOCOMPLETE_INDEX[prefix_key]:
                                word = item.get("w", "")
                                if word.startswith(current_word_prefix) and word not in existing:
                                    word_suggestions.append({
                                        "word": word,
                                        "df": item.get("d", 0)
                                    })
                                    if len(word_suggestions) >= 5:
                                        break

                # Prepend previous words to each suggestion
                for ws in word_suggestions:
                    full_phrase = f"{prev_words} {ws['word']}" if prev_words else ws['word']
                    if full_phrase not in seen:
                        suggestions.append({
                            "word": full_phrase,
                            "df": ws["df"]
                        })
                        seen.add(full_phrase)

        if suggestions:
            return {
                "success": True,
                "prefix": original_prefix,
                "suggestions": suggestions[:5],
                "time_ms": 1
            }

    # Single-word autocomplete - use in-memory index (fast)
    if AUTOCOMPLETE_INDEX:
        suggestions = []

        # Try 2-character prefix lookup (matches the index structure)
        if len(prefix_stripped) >= 2:
            prefix_key = prefix_stripped[:2]
            if prefix_key in AUTOCOMPLETE_INDEX:
                # Filter by full prefix match
                for item in AUTOCOMPLETE_INDEX[prefix_key]:
                    word = item.get("w", "")
                    if word.startswith(prefix_stripped):
                        suggestions.append({
                            "word": word,
                            "df": item.get("d", 0)
                        })
                        if len(suggestions) >= 5:
                            break

        # Also try 3-character prefix if available and we need more results
        if len(suggestions) < 5 and len(prefix_stripped) >= 3:
            prefix_key = prefix_stripped[:3]
            if prefix_key in AUTOCOMPLETE_INDEX:
                existing_words = {s["word"] for s in suggestions}
                for item in AUTOCOMPLETE_INDEX[prefix_key]:
                    word = item.get("w", "")
                    if word.startswith(prefix_stripped) and word not in existing_words:
                        suggestions.append({
                            "word": word,
                            "df": item.get("d", 0)
                        })
                        if len(suggestions) >= 5:
                            break

        return {
            "success": True,
            "prefix": original_prefix,
            "suggestions": suggestions[:5],
            "time_ms": 1  # Fast in-memory lookup
        }

    # Fallback to C++ subprocess (slower, only if index not loaded)
    if not SEMANTIC_SEARCH_EXECUTABLE:
        return {"success": False, "error": "Autocomplete not available", "prefix": original_prefix}

    cmd = [SEMANTIC_SEARCH_EXECUTABLE, "--autocomplete", prefix_stripped]

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)

        if result.returncode != 0:
            return {"success": False, "error": result.stderr or "Failed", "prefix": original_prefix}

        parsed = parse_autocomplete_output(result.stdout)
        parsed["success"] = True
        parsed["prefix"] = original_prefix

        return parsed

    except Exception as e:
        return {"success": False, "error": str(e), "prefix": original_prefix}

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
            "/health": "Health check",
            "/upload": "Upload and index a new document (POST)",
            "/upload/text": "Index a document from text (POST)"
        }
    }

# ==================== Document Upload Endpoints ====================

# Lazy load document indexer to avoid startup delay
_document_indexer = None

def get_document_indexer():
    """Get or create document indexer instance."""
    global _document_indexer
    if _document_indexer is None:
        try:
            from document_indexer import DocumentIndexer
            _document_indexer = DocumentIndexer()
            print("Document indexer initialized")
        except Exception as e:
            print(f"Failed to initialize document indexer: {e}")
            return None
    return _document_indexer

@app.post("/upload", response_model=DocumentUploadResponse, tags=["Upload"])
async def upload_document(
    file: UploadFile = File(..., description="Document file (txt, json, md)"),
    title: Optional[str] = Form(None, description="Document title (optional, extracted from file if not provided)"),
    authors: Optional[str] = Form(None, description="Comma-separated list of authors")
):
    """
    Upload and index a new document.

    Supports file formats:
    - .txt - Plain text (first line used as title)
    - .json - JSON with title, abstract, body_text fields
    - .md - Markdown (first heading used as title)

    The document will be indexed and immediately searchable.
    Indexing typically takes less than 1 second.
    """
    indexer = get_document_indexer()
    if indexer is None:
        return DocumentUploadResponse(
            success=False,
            error="Document indexer not initialized. Please ensure all dependencies are installed."
        )

    # Validate file
    if not file or not file.filename:
        return DocumentUploadResponse(
            success=False,
            error="No file provided"
        )

    # Read file content
    try:
        content = await file.read()
        if not content:
            return DocumentUploadResponse(
                success=False,
                error="File is empty"
            )
    except Exception as e:
        return DocumentUploadResponse(
            success=False,
            error=f"Failed to read file: {str(e)}"
        )

    # Determine file type
    file_type = file.filename.split('.')[-1].lower() if '.' in file.filename else 'txt'
    
    # Validate file type
    allowed_types = ['txt', 'json', 'md', 'text']
    if file_type not in allowed_types:
        return DocumentUploadResponse(
            success=False,
            error=f"Unsupported file type: .{file_type}. Allowed types: {', '.join(allowed_types)}"
        )

    # Parse authors
    author_list = []
    if authors:
        author_list = [a.strip() for a in authors.split(',') if a.strip()]

    # Index the document
    try:
        result = indexer.index_document(
            title=title or "",
            authors=author_list,
            file_content=content,
            file_type=file_type
        )

        if result["success"]:
            # Reload metadata in memory
            global DOC_METADATA
            DOC_METADATA = load_doc_metadata()

            return DocumentUploadResponse(
                success=True,
                doc_id=result["doc_id"],
                title=result.get("title", ""),
                total_terms=result.get("total_terms", 0),
                unique_terms=result.get("unique_terms", 0),
                new_terms_added=result.get("new_terms_added", 0),
                indexing_time_ms=result.get("indexing_time_ms", 0)
            )
        else:
            return DocumentUploadResponse(
                success=False,
                error=result.get("error", "Indexing failed")
            )

    except Exception as e:
        import traceback
        error_detail = f"Indexing error: {str(e)}"
        print(f"Upload error: {error_detail}")
        print(traceback.format_exc())
        return DocumentUploadResponse(
            success=False,
            error=error_detail
        )

@app.post("/upload/text", response_model=DocumentUploadResponse, tags=["Upload"])
async def upload_document_text(doc: DocumentTextRequest):
    """
    Index a document from text content.

    Provide title, abstract, and/or body text directly.
    At least one text field must be non-empty.
    """
    indexer = get_document_indexer()
    if indexer is None:
        return DocumentUploadResponse(
            success=False,
            error="Document indexer not initialized. Please ensure all dependencies are installed."
        )

    if not doc.title and not doc.abstract and not doc.body:
        return DocumentUploadResponse(
            success=False,
            error="At least one of title, abstract, or body must be provided"
        )

    try:
        result = indexer.index_document(
            doc_id=doc.doc_id,
            title=doc.title,
            abstract=doc.abstract,
            body=doc.body,
            authors=doc.authors
        )

        if result["success"]:
            # Reload metadata
            global DOC_METADATA
            DOC_METADATA = load_doc_metadata()

            return DocumentUploadResponse(
                success=True,
                doc_id=result["doc_id"],
                title=result.get("title", ""),
                total_terms=result.get("total_terms", 0),
                unique_terms=result.get("unique_terms", 0),
                new_terms_added=result.get("new_terms_added", 0),
                indexing_time_ms=result.get("indexing_time_ms", 0)
            )
        else:
            return DocumentUploadResponse(
                success=False,
                error=result.get("error", "Indexing failed")
            )

    except Exception as e:
        import traceback
        error_detail = f"Indexing error: {str(e)}"
        print(f"Upload text error: {error_detail}")
        print(traceback.format_exc())
        return DocumentUploadResponse(
            success=False,
            error=error_detail
        )

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
