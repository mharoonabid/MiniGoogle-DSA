# MiniGoogle-DSA: Critical TODOs to Complete

## 📋 Requirements Status Summary

### ✅ Completed (18.5/25 points)
- [x] Lexicon
- [x] Forward Index
- [x] Inverted Index
- [x] Single word search (3 pts)
- [x] Multi-word search (3 pts)
- [x] Semantic search (1.5 pts)
- [x] Autocomplete with multi-word (1.5 pts)
- [x] BM25 Ranking (2 pts)
- [x] Barrels (2 pts)
- [x] Query performance <500ms (1 pt)
- [x] Memory usage <2GB (1 pt)
- [x] Professional UI (1.5 pts)
- [x] Git usage (1.5 pts)

### ❌ Critical Missing (5 points)
- [ ] **Document titles in UI** (0.5 pt from UI requirements)
- [ ] **Application deployment** (1 pt)
- [ ] **Dynamic content addition** (2 pts)
- [ ] **New document indexing <1 min** (1 pt)
- [ ] **Code quality polish** (0.5 pt)

---

## 🎯 TODO 1: Display Document Titles (CRITICAL)

### Current Issue
```jsx
// Shows: "PMC7326321"
// Should show: "Efficacy and Safety of COVID-19 Vaccines: A Systematic Review"
```

### Solution

#### Step 1: Create Document Metadata Store

**File: `backend/py/document_metadata_builder.py`**
```python
"""
Extract document titles and metadata from CORD-19 dataset.
Creates a fast lookup JSON: doc_id → {title, authors, abstract}
"""

import json
from pathlib import Path
from tqdm import tqdm

def extract_metadata(json_dir, output_file):
    """Extract titles and metadata from all JSON files."""
    metadata = {}

    for json_file in tqdm(Path(json_dir).glob("*.json")):
        try:
            with open(json_file, 'r', encoding='utf-8') as f:
                data = json.load(f)

            doc_id = data.get('paper_id', json_file.stem)

            # Extract title
            title = data.get('metadata', {}).get('title', 'Untitled')

            # Extract authors
            authors = []
            for author in data.get('metadata', {}).get('authors', [])[:3]:
                if 'first' in author and 'last' in author:
                    authors.append(f"{author['first']} {author['last']}")

            # Extract abstract (first 200 chars)
            abstract = ""
            if 'abstract' in data and len(data['abstract']) > 0:
                abstract = data['abstract'][0].get('text', '')[:200]

            metadata[doc_id] = {
                'title': title,
                'authors': authors,
                'abstract': abstract
            }

        except Exception as e:
            continue

    # Save to JSON
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(metadata, f, indent=2)

    print(f"Extracted metadata for {len(metadata)} documents")
    return metadata

if __name__ == "__main__":
    # Paths
    backend_dir = Path(__file__).parent.parent
    config_path = backend_dir / "config.json"

    with open(config_path) as f:
        config = json.load(f)

    data_dir = backend_dir / config["data_dir"] / "document_parses" / "pdf_json"
    indexes_dir = backend_dir / config["indexes_dir"]
    output_file = indexes_dir / "document_metadata.json"

    extract_metadata(data_dir, output_file)
```

**Run once:**
```bash
python backend/py/document_metadata_builder.py
# Creates: backend/indexes/document_metadata.json
```

---

#### Step 2: Update API to Return Metadata

**File: `backend/py/api.py`**

Add after line 110:
```python
NGRAM_INDEX = None
DOC_METADATA = None  # ADD THIS

def load_doc_metadata():
    """Load document metadata (titles, authors)."""
    script_dir = Path(__file__).parent.resolve()
    backend_dir = script_dir.parent
    indexes_dir = backend_dir / "indexes"
    metadata_file = indexes_dir / "document_metadata.json"

    if metadata_file.exists():
        with open(metadata_file, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {}
```

Update startup (line 135):
```python
@app.on_event("startup")
async def startup_event():
    global SEARCH_EXECUTABLE, SEMANTIC_SEARCH_EXECUTABLE, NGRAM_INDEX, DOC_METADATA

    # ... existing code ...

    # Load document metadata
    DOC_METADATA = load_doc_metadata()
    if DOC_METADATA:
        print(f"Loaded metadata for {len(DOC_METADATA)} documents")
```

Update parse functions to add metadata (around line 190):
```python
def parse_semantic_search_output(output: str) -> dict:
    # ... existing parsing ...

    # After building results list, add metadata
    for result in results:
        doc_id = result["doc_id"]
        if doc_id in DOC_METADATA:
            result["title"] = DOC_METADATA[doc_id].get("title", "")
            result["authors"] = DOC_METADATA[doc_id].get("authors", [])
            result["abstract"] = DOC_METADATA[doc_id].get("abstract", "")

    return {
        "query_type": "semantic",
        # ... rest of return
    }
```

Do same for `parse_basic_search_output()`.

---

#### Step 3: Update Frontend to Display Titles

**File: `frontend/src/App.jsx`**

Update Pydantic model (line 44):
```python
class SearchResult(BaseModel):
    rank: int
    doc_id: str
    title: Optional[str] = None  # ADD
    authors: Optional[List[str]] = None  # ADD
    abstract: Optional[str] = None  # ADD
    score: float
    # ... rest
```

Update frontend display (line 226):
```jsx
<li key={result.doc_id} className="result-item">
  <div className="result-rank">{result.rank || i + 1}</div>
  <div className="result-content">
    {/* Title as main heading */}
    <h3 className="result-title">
      <a
        href={`https://www.ncbi.nlm.nih.gov/pmc/articles/${result.doc_id}/`}
        target="_blank"
        rel="noopener noreferrer"
      >
        {result.title || result.doc_id}
      </a>
    </h3>

    {/* Authors */}
    {result.authors && result.authors.length > 0 && (
      <div className="result-authors">
        {result.authors.join(', ')}
      </div>
    )}

    {/* Abstract snippet */}
    {result.abstract && (
      <p className="result-abstract">{result.abstract}...</p>
    )}

    {/* Doc ID (smaller) */}
    <div className="result-doc-id">
      Document: {result.doc_id}
    </div>

    {/* Scores */}
    <div className="result-scores">
      <span className="score">Score: {result.score?.toFixed(4)}</span>
      {result.tfidf_score !== undefined && (
        <span className="score">BM25: {result.tfidf_score?.toFixed(4)}</span>
      )}
      {/* ... rest of scores */}
    </div>
  </div>
</li>
```

**Add CSS** (`frontend/src/App.css`):
```css
.result-title {
  font-size: 1.1rem;
  font-weight: 500;
  margin-bottom: 4px;
  color: #1a0dab;
}

.result-title a {
  color: #1a0dab;
  text-decoration: none;
}

.result-title a:hover {
  text-decoration: underline;
}

.result-authors {
  font-size: 0.85rem;
  color: #006621;
  margin-bottom: 4px;
}

.result-abstract {
  font-size: 0.9rem;
  color: #545454;
  margin: 8px 0;
  line-height: 1.4;
}

.result-doc-id {
  font-size: 0.75rem;
  color: #70757a;
  margin-bottom: 4px;
}
```

**Estimated time:** 2 hours

---

## 🚀 TODO 2: Deploy Application (1 point)

### Option A: Vercel (Frontend) + Railway (Backend)

#### Frontend Deployment (Vercel)

1. **Push to GitHub:**
```bash
cd d:/MiniGoogle-DSA
git add .
git commit -m "Prepare for deployment"
git push origin main
```

2. **Deploy on Vercel:**
   - Go to https://vercel.com
   - Sign up with GitHub
   - Click "New Project"
   - Import your repository
   - Set root directory: `frontend`
   - Build command: `npm run build`
   - Output directory: `dist`
   - Deploy!

3. **Update API URL:**
```jsx
// frontend/src/App.jsx
const API_BASE = import.meta.env.PROD
  ? 'https://your-backend.railway.app'
  : 'http://localhost:5000'
```

#### Backend Deployment (Railway)

1. **Create `requirements.txt`:**
```bash
cd backend/py
pip freeze > requirements.txt
```

2. **Create `railway.toml`:**
```toml
[build]
builder = "nixpacks"

[deploy]
startCommand = "uvicorn api:app --host 0.0.0.0 --port $PORT"
```

3. **Deploy on Railway:**
   - Go to https://railway.app
   - Sign up with GitHub
   - New Project → Deploy from GitHub
   - Select repo
   - Set root directory: `backend/py`
   - Add environment variables if needed
   - Deploy!

4. **Upload Index Files:**
   - Railway provides persistent storage
   - Upload `backend/indexes/` to Railway via CLI or web UI

**Estimated time:** 2-3 hours

---

### Option B: All-in-One (Render.com)

**Simpler but potentially slower:**

1. Create `render.yaml`:
```yaml
services:
  - type: web
    name: minigoogle-backend
    env: python
    buildCommand: "pip install -r backend/py/requirements.txt && cd backend/cpp && cmake . && make"
    startCommand: "uvicorn backend.py.api:app --host 0.0.0.0 --port $PORT"

  - type: web
    name: minigoogle-frontend
    env: static
    buildCommand: "cd frontend && npm install && npm run build"
    staticPublishPath: frontend/dist
```

2. Push to GitHub
3. Connect Render to GitHub
4. Auto-deploys!

**Estimated time:** 1-2 hours

---

## 📝 TODO 3: Dynamic Content Addition (2 points)

### Requirements
- User uploads new JSON document
- System indexes it automatically
- Appears in search results
- Completes within 1 minute

### Implementation Strategy

#### Approach 1: Incremental Indexing (RECOMMENDED)

**File: `backend/py/incremental_indexer.py`**

```python
"""
Incremental Document Indexer
Adds new documents to existing indices without full rebuild.
"""

import json
from pathlib import Path
from collections import defaultdict

class IncrementalIndexer:
    def __init__(self, backend_dir):
        self.backend_dir = Path(backend_dir)
        self.indexes_dir = self.backend_dir / "indexes"

        # Load existing indices
        self.lexicon = self._load_lexicon()
        self.inverted_index = self._load_inverted_index()
        self.doc_metadata = self._load_metadata()

    def add_document(self, doc_data, doc_id=None):
        """
        Add a single document to indices.

        Args:
            doc_data: JSON document data
            doc_id: Optional document ID (auto-generated if not provided)

        Returns:
            doc_id: The document ID
            time_taken: Indexing time in seconds
        """
        import time
        start = time.time()

        # Generate doc ID if not provided
        if not doc_id:
            doc_id = f"DOC_{int(time.time() * 1000)}"

        # Extract text
        text = self._extract_text(doc_data)

        # Tokenize and lemmatize
        tokens = self._process_text(text)

        # Update lexicon (add new words)
        for word, lemma in tokens:
            if word not in self.lexicon['wordID']:
                word_id = len(self.lexicon['wordID'])
                self.lexicon['wordID'][word] = word_id

                lemma_id = self.lexicon['lemmaID'].get(lemma)
                if lemma_id is None:
                    lemma_id = len(self.lexicon['lemmaID'])
                    self.lexicon['lemmaID'][lemma] = lemma_id

                self.lexicon['wordToLemmaID'][str(word_id)] = lemma_id

        # Count term frequencies
        term_freqs = defaultdict(int)
        for word, lemma in tokens:
            lemma_id = self.lexicon['lemmaID'][lemma]
            term_freqs[lemma_id] += 1

        # Update inverted index
        for lemma_id, tf in term_freqs.items():
            if lemma_id not in self.inverted_index:
                self.inverted_index[lemma_id] = {
                    'df': 0,
                    'docs': []
                }

            self.inverted_index[lemma_id]['df'] += 1
            self.inverted_index[lemma_id]['docs'].append({
                'doc_id': doc_id,
                'tf': tf
            })

        # Add metadata
        self.doc_metadata[doc_id] = {
            'title': doc_data.get('metadata', {}).get('title', 'Untitled'),
            'authors': self._extract_authors(doc_data),
            'abstract': self._extract_abstract(doc_data)
        }

        # Persist changes
        self._save_indices()

        # Update binary barrels (quick append)
        self._update_barrels(doc_id, term_freqs)

        elapsed = time.time() - start
        return doc_id, elapsed

    def _update_barrels(self, doc_id, term_freqs):
        """Update binary barrels with new document."""
        # Determine which barrel each term goes to
        barrel_lookup = self._load_barrel_lookup()

        for lemma_id, tf in term_freqs.items():
            barrel_id = barrel_lookup.get(str(lemma_id), 9)  # Default to barrel 9

            # Append to binary barrel
            barrel_path = self.indexes_dir / "barrels_binary" / f"barrel_{barrel_id}.bin"

            with open(barrel_path, 'ab') as f:  # Append mode
                # Write posting: [doc_id:20][tf:4]
                doc_id_padded = doc_id.ljust(20)[:20].encode()
                f.write(doc_id_padded)
                f.write(tf.to_bytes(4, 'little'))

            # Update index file
            self._update_barrel_index(barrel_id, lemma_id, barrel_path)

    def _save_indices(self):
        """Persist updated indices to disk."""
        # Save lexicon
        lexicon_path = self.indexes_dir / "lexicon.json"
        with open(lexicon_path, 'w') as f:
            json.dump(self.lexicon, f, indent=2)

        # Save metadata
        metadata_path = self.indexes_dir / "document_metadata.json"
        with open(metadata_path, 'w') as f:
            json.dump(self.doc_metadata, f, indent=2)

        # Inverted index update handled by barrel updates
```

**File: `backend/py/api.py` - Add upload endpoint:**

```python
from fastapi import UploadFile, File
import tempfile

@app.post("/upload", tags=["Admin"])
async def upload_document(file: UploadFile = File(...)):
    """
    Upload a new JSON document to be indexed.

    Returns indexing time and document ID.
    """
    try:
        # Read uploaded file
        contents = await file.read()
        doc_data = json.loads(contents)

        # Index document
        indexer = IncrementalIndexer(backend_dir)
        doc_id, time_taken = indexer.add_document(doc_data)

        # Check if within 1 minute requirement
        if time_taken > 60:
            return {
                "success": False,
                "error": f"Indexing took {time_taken:.2f}s (>60s limit)",
                "doc_id": doc_id
            }

        return {
            "success": True,
            "doc_id": doc_id,
            "indexing_time_ms": int(time_taken * 1000),
            "message": f"Document indexed successfully in {time_taken:.2f}s"
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
```

**Frontend upload component:**

```jsx
// Add to App.jsx
const [uploadFile, setUploadFile] = useState(null)
const [uploadStatus, setUploadStatus] = useState(null)

const handleUpload = async () => {
  const formData = new FormData()
  formData.append('file', uploadFile)

  try {
    const res = await fetch(`${API_BASE}/upload`, {
      method: 'POST',
      body: formData
    })
    const data = await res.json()
    setUploadStatus(data)
  } catch (err) {
    setUploadStatus({ success: false, error: err.message })
  }
}

// In JSX:
<div className="upload-section">
  <h3>Add New Document</h3>
  <input
    type="file"
    accept=".json"
    onChange={(e) => setUploadFile(e.target.files[0])}
  />
  <button onClick={handleUpload}>Upload & Index</button>
  {uploadStatus && (
    <div className={uploadStatus.success ? 'success' : 'error'}>
      {uploadStatus.message || uploadStatus.error}
      {uploadStatus.indexing_time_ms && (
        <span> ({uploadStatus.indexing_time_ms}ms)</span>
      )}
    </div>
  )}
</div>
```

**Estimated time:** 6-8 hours

---

#### Approach 2: Batch Re-indexing (SIMPLER but slower)

For small additions (<100 docs), just rebuild affected barrels:

```python
def add_document_simple(doc_data):
    """Simple approach: Add to JSON barrels and rebuild binary."""
    # 1. Add to inverted_index.txt (append)
    # 2. Rebuild affected barrels only
    # 3. Update binary barrels

    # Should complete in <30s for single document
```

---

## 🎨 TODO 4: Code Quality Polish (0.5 point)

### Quick Wins

1. **Add docstrings to all functions:**
```python
def run_autocomplete(prefix: str) -> dict:
    """
    Get autocomplete suggestions with multi-word support.

    Args:
        prefix: User's partial query (e.g., "covid vac")

    Returns:
        dict: {
            "success": bool,
            "prefix": str,
            "suggestions": List[{word: str, df: int}],
            "time_ms": int
        }
    """
```

2. **Consistent error handling:**
```python
try:
    result = process_query(query)
except FileNotFoundError as e:
    logger.error(f"Index file not found: {e}")
    return {"success": False, "error": "Search index not initialized"}
except Exception as e:
    logger.error(f"Unexpected error: {e}")
    return {"success": False, "error": "Internal server error"}
```

3. **Add logging:**
```python
import logging

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

logger.info(f"Search query: {query}, mode: {mode}, time: {time_ms}ms")
```

**Estimated time:** 2-3 hours

---

## 📊 Priority Order

| Priority | Task | Points | Time | Deadline |
|----------|------|--------|------|----------|
| **1** | Document titles | 0.5 | 2h | Day 1 |
| **2** | Deployment | 1.0 | 3h | Day 2 |
| **3** | Dynamic indexing | 2.0 | 8h | Day 3-4 |
| **4** | Code quality | 0.5 | 3h | Day 5 |

**Total time estimate:** 16 hours over 5 days

---

## 🎯 Bonus Optimizations (Optional)

### 1. Search History
```python
# Track user queries
search_history = []

@app.get("/history")
async def get_search_history():
    return search_history[-10:]  # Last 10 searches
```

### 2. Query Spell Correction
```python
from difflib import get_close_matches

def suggest_corrections(query, lexicon):
    words = query.split()
    corrections = []

    for word in words:
        if word not in lexicon:
            suggestions = get_close_matches(word, lexicon, n=1, cutoff=0.8)
            if suggestions:
                corrections.append((word, suggestions[0]))

    return corrections
```

### 3. Related Searches
```python
# Based on query logs
related_searches = {
    "covid vaccine": ["covid booster", "vaccine efficacy", "mrna vaccine"],
    "machine learning": ["deep learning", "neural networks", "ai"]
}
```

---

## ✅ Final Checklist

Before submission:

- [ ] Document titles display correctly
- [ ] Application deployed and accessible via URL
- [ ] Can upload new JSON document via UI
- [ ] New document appears in search results within 1 minute
- [ ] All code has docstrings
- [ ] Error handling is consistent
- [ ] Git has 20+ meaningful commits
- [ ] README updated with deployment URL
- [ ] All team members have commits
- [ ] Performance requirements met (test with timer)

---

## 📝 Submission Checklist

**Required files/items:**

1. ✅ Source code on GitHub (private repo OK)
2. ✅ README with:
   - Project description
   - Setup instructions
   - **Deployment URL** ⚠️
   - Team member contributions
3. ✅ Documentation:
   - Architecture diagram
   - API documentation
   - Performance benchmarks
4. ✅ Demo video (optional but recommended):
   - Show all features
   - Upload new document
   - Search performance

Good luck! 🚀
