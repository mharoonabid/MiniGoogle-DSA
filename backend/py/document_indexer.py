"""
Fast Document Indexer for Real-time Document Addition

Allows adding new documents to the search index in under a minute.
Uses the existing lexicon and updates indexes incrementally.

Features:
- Supports txt, json, pdf, and other text formats
- Fast tokenization and lemmatization
- Incremental index updates (no full rebuild)
- Updates barrels, forward index, and metadata
"""

import os
import json
import re
import time
from pathlib import Path
from collections import Counter, defaultdict
from typing import Optional, List, Dict, Tuple, Any
import uuid

# Try faster JSON
try:
    import orjson
    def json_loads(data):
        return orjson.loads(data)
    def json_dumps(data, indent=None):
        if indent:
            return orjson.dumps(data, option=orjson.OPT_INDENT_2).decode('utf-8')
        return orjson.dumps(data).decode('utf-8')
except ImportError:
    def json_loads(data):
        return json.loads(data)
    def json_dumps(data, indent=None):
        return json.dumps(data, indent=indent)

# NLTK for lemmatization (reuse from lexicon.py)
try:
    from nltk.corpus import stopwords
    from nltk.tokenize import word_tokenize
    from nltk.stem import WordNetLemmatizer
    import nltk
    
    # Ensure required data is downloaded
    try:
        stopwords.words('english')
    except LookupError:
        print("Downloading NLTK data...")
        nltk.download('stopwords', quiet=True)
        nltk.download('punkt', quiet=True)
        nltk.download('wordnet', quiet=True)
    
    HAS_NLTK = True
except ImportError:
    HAS_NLTK = False
    print("Warning: NLTK not available. Using fallback tokenization.")

# Stopwords fallback
STOPWORDS = frozenset({
    'a', 'an', 'the', 'and', 'or', 'but', 'in', 'on', 'at', 'to', 'for',
    'of', 'with', 'by', 'from', 'as', 'is', 'was', 'are', 'were', 'been',
    'be', 'have', 'has', 'had', 'do', 'does', 'did', 'will', 'would', 'could',
    'should', 'may', 'might', 'must', 'shall', 'can', 'need', 'dare', 'ought',
    'used', 'this', 'that', 'these', 'those', 'i', 'you', 'he', 'she', 'it',
    'we', 'they', 'what', 'which', 'who', 'whom', 'where', 'when', 'why', 'how',
    'all', 'each', 'every', 'both', 'few', 'more', 'most', 'other', 'some',
    'such', 'no', 'nor', 'not', 'only', 'own', 'same', 'so', 'than', 'too',
    'very', 'just', 'also', 'now', 'here', 'there', 'then', 'once', 'if'
})


class DocumentIndexer:
    """Fast document indexer for real-time document addition."""

    def __init__(self, backend_dir: Path = None):
        """Initialize the indexer with paths to existing indexes."""
        if backend_dir is None:
            backend_dir = Path(__file__).resolve().parent.parent

        self.backend_dir = Path(backend_dir)

        # Load config
        config_path = self.backend_dir / "config.json"
        if not config_path.exists():
            raise FileNotFoundError(f"Config file not found: {config_path}")
        
        with open(config_path, 'r') as f:
            self.config = json.load(f)

        self.indexes_dir = self.backend_dir / self.config["indexes_dir"]
        self.barrels_dir = self.indexes_dir / self.config["barrels_dir"]
        
        # Ensure directories exist
        self.indexes_dir.mkdir(parents=True, exist_ok=True)
        self.barrels_dir.mkdir(parents=True, exist_ok=True)

        # Initialize NLTK if available
        if HAS_NLTK:
            self.stop_words = set(stopwords.words('english'))
            self.lemmatizer = WordNetLemmatizer()
        else:
            self.stop_words = STOPWORDS
            self.lemmatizer = None

        # Load lexicon into memory (for fast lookups)
        self.lexicon = self._load_lexicon()

        # Load barrel lookup
        self.barrel_lookup = self._load_barrel_lookup()

        # Load document metadata
        self.doc_metadata = self._load_metadata()

        # Track new terms that need to be added to lexicon
        self.new_terms = {}
        self.next_word_id = max(self.lexicon.get("wordID", {}).values() or [0]) + 1
        self.next_lemma_id = max(self.lexicon.get("lemmaID", {}).values() or [0]) + 1

    def _load_lexicon(self) -> dict:
        """Load lexicon from disk."""
        lexicon_path = self.indexes_dir / self.config["lexicon_file"]
        if lexicon_path.exists():
            with open(lexicon_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        return {"wordID": {}, "lemmaID": {}, "wordToLemmaID": {}}

    def _load_barrel_lookup(self) -> dict:
        """Load barrel lookup table."""
        lookup_path = self.indexes_dir / self.config["barrel_lookup"]
        if lookup_path.exists():
            with open(lookup_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        return {}

    def _load_metadata(self) -> dict:
        """Load document metadata."""
        metadata_path = self.indexes_dir / "document_metadata.json"
        if metadata_path.exists():
            with open(metadata_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        return {}

    def _save_metadata(self):
        """Save document metadata."""
        metadata_path = self.indexes_dir / "document_metadata.json"
        with open(metadata_path, 'w', encoding='utf-8') as f:
            json.dump(self.doc_metadata, f, indent=2)

    def _save_lexicon(self):
        """Save updated lexicon and rebuild binary cache for fast C++ loading."""
        lexicon_path = self.indexes_dir / self.config["lexicon_file"]
        with open(lexicon_path, 'w', encoding='utf-8') as f:
            json.dump(self.lexicon, f, indent=2)
        
        # Rebuild binary lexicon cache so C++ can load quickly
        self._rebuild_binary_lexicon()

    def _rebuild_binary_lexicon(self):
        """Rebuild binary lexicon for fast C++ loading."""
        try:
            import struct
            
            embeddings_dir = self.indexes_dir / "embeddings"
            embeddings_dir.mkdir(parents=True, exist_ok=True)
            
            word_id = self.lexicon.get("wordID", {})
            word_to_lemma = self.lexicon.get("wordToLemmaID", {})
            
            # Create word -> lemma_id mapping
            words = []
            for word, wid in word_id.items():
                wid_str = str(wid)
                if wid_str in word_to_lemma:
                    lemma_id = word_to_lemma[wid_str]
                else:
                    lemma_id = wid
                words.append((word.lower(), lemma_id))
            
            # Sort by word for binary search
            words.sort(key=lambda x: x[0])
            
            # Write binary file
            bin_path = embeddings_dir / "lexicon.bin"
            with open(bin_path, 'wb') as f:
                # Header: number of words
                f.write(struct.pack('I', len(words)))
                
                # Word data (length-prefixed strings)
                word_data = b''
                for word, _ in words:
                    word_bytes = word.encode('utf-8')
                    word_data += struct.pack('H', len(word_bytes)) + word_bytes
                
                # Lemma IDs
                lemma_data = b''
                for _, lemma_id in words:
                    lemma_data += struct.pack('i', lemma_id)
                
                f.write(word_data)
                f.write(lemma_data)
            
            print(f"  Rebuilt binary lexicon: {len(words)} words, {bin_path.stat().st_size / 1024 / 1024:.1f} MB")
            
        except Exception as e:
            print(f"  Warning: Failed to rebuild binary lexicon: {e}")
            # Don't fail the upload if binary rebuild fails

    def _clean_and_tokenize(self, text: str) -> List[Tuple[str, str]]:
        """Clean and tokenize text, returning (word, lemma) pairs."""
        # Clean text
        text = re.sub(r'http[s]?://\S+|[^a-zA-Z0-9\s]+|\s+', ' ', text).strip()

        if HAS_NLTK:
            tokens = word_tokenize(text.lower())
            return [
                (word, self.lemmatizer.lemmatize(word))
                for word in tokens
                if word not in self.stop_words and word.isalpha() and len(word) >= 2
            ]
        else:
            # Fallback tokenization
            words = text.lower().split()
            return [
                (word, word)  # No lemmatization without NLTK
                for word in words
                if word not in self.stop_words and word.isalpha() and len(word) >= 2
            ]

    def _get_or_create_lemma_id(self, word: str, lemma: str) -> int:
        """Get lemma ID for a word, creating new entries if needed."""
        word = word.lower()
        lemma = lemma.lower()

        # Check if word exists
        if word in self.lexicon["wordID"]:
            word_id = self.lexicon["wordID"][word]
            lemma_id = self.lexicon["wordToLemmaID"].get(str(word_id), word_id)
            return lemma_id

        # Create new word ID
        word_id = self.next_word_id
        self.next_word_id += 1
        self.lexicon["wordID"][word] = word_id

        # Get or create lemma ID
        if lemma in self.lexicon["lemmaID"]:
            lemma_id = self.lexicon["lemmaID"][lemma]
        else:
            lemma_id = self.next_lemma_id
            self.next_lemma_id += 1
            self.lexicon["lemmaID"][lemma] = lemma_id

        self.lexicon["wordToLemmaID"][str(word_id)] = lemma_id
        self.new_terms[word] = lemma_id

        return lemma_id

    def _text_to_lemma_ids(self, text: str) -> List[int]:
        """Convert text to list of lemma IDs."""
        tokens = self._clean_and_tokenize(text)
        return [self._get_or_create_lemma_id(word, lemma) for word, lemma in tokens]

    def _determine_barrel(self, lemma_id: int, df: int = 1) -> int:
        """Determine which barrel a term should go to."""
        # Check existing lookup
        str_lemma = str(lemma_id)
        if str_lemma in self.barrel_lookup:
            return self.barrel_lookup[str_lemma]

        # New terms go to COLD barrels (7-9) since df is low
        barrel = 7 + (lemma_id % 3)
        self.barrel_lookup[str_lemma] = barrel
        return barrel

    def _update_barrel(self, barrel_id: int, lemma_id: int, doc_id: str, tf: int):
        """
        Update barrel with new posting.
        Uses barrel 10 (new_docs) to avoid corrupting large existing barrels.
        """
        # Always use barrel 10 path for new document indexing
        barrel_path = self.barrels_dir / "inverted_barrel_new_docs.json"
        barrel_name = "new_docs"

        # Load barrel (much smaller for new_docs and safe to load)
        if barrel_path.exists():
            try:
                with open(barrel_path, 'r', encoding='utf-8') as f:
                    barrel = json.load(f)
            except json.JSONDecodeError:
                # If corrupted, recreate
                barrel = {
                    "barrel_id": barrel_name,
                    "type": "NEW_DOCS",
                    "num_terms": 0,
                    "postings": {}
                }
        else:
            barrel = {
                "barrel_id": barrel_name,
                "type": "NEW_DOCS",
                "num_terms": 0,
                "postings": {}
            }

        str_lemma = str(lemma_id)

        # Add or update posting
        if str_lemma not in barrel["postings"]:
            barrel["postings"][str_lemma] = {
                "df": 0,
                "docs": [],
                "barrel_id": 10
            }
            barrel["num_terms"] += 1
            # Only update barrel_lookup if this is a NEW term (not already in any barrel)
            if str_lemma not in self.barrel_lookup:
                self.barrel_lookup[str_lemma] = 10

        # Check if doc already exists
        existing_docs = {d["doc_id"] for d in barrel["postings"][str_lemma]["docs"]}
        if doc_id not in existing_docs:
            barrel["postings"][str_lemma]["docs"].append({
                "doc_id": doc_id,
                "tf": tf
            })
            barrel["postings"][str_lemma]["df"] += 1

        # Save barrel
        with open(barrel_path, 'w', encoding='utf-8') as f:
            json.dump(barrel, f, indent=2)

    def _update_forward_index(self, doc_id: str, lemma_ids: List[int],
                               title_lemmas: List[int] = None,
                               abstract_lemmas: List[int] = None):
        """Append document to forward index."""
        forward_path = self.indexes_dir / self.config["forward_index_file"]

        total_terms = len(lemma_ids)
        title_str = ",".join(map(str, title_lemmas or []))
        abstract_str = ",".join(map(str, abstract_lemmas or []))
        body_str = ",".join(map(str, lemma_ids[:5000]))  # Limit body

        line = f"{doc_id}|{total_terms}|{title_str}|{abstract_str}|{body_str}\n"

        with open(forward_path, 'a', encoding='utf-8') as f:
            f.write(line)

    def _save_barrel_lookup(self):
        """Save updated barrel lookup."""
        lookup_path = self.indexes_dir / self.config["barrel_lookup"]
        with open(lookup_path, 'w', encoding='utf-8') as f:
            json.dump(self.barrel_lookup, f, indent=2)
    
    def _rebuild_binary_barrel(self, barrel_id):
        """Rebuild binary barrel from JSON barrel (called after updates)."""
        try:
            # Import here to avoid circular dependency
            import struct
            
            # Handle barrel 10 (new_docs) and regular barrels
            if barrel_id == 10:
                barrel_json_path = self.barrels_dir / "inverted_barrel_new_docs.json"
                barrel_name = "new_docs"
            else:
                barrel_json_path = self.barrels_dir / f"inverted_barrel_{barrel_id}.json"
                barrel_name = str(barrel_id)
                
            if not barrel_json_path.exists():
                return
            
            # Load JSON barrel
            try:
                with open(barrel_json_path, 'r', encoding='utf-8') as f:
                    barrel_data = json.load(f)
            except json.JSONDecodeError:
                print(f"Warning: Corrupted barrel {barrel_id}, skipping binary rebuild")
                return
            
            # Binary files directory
            binary_dir = self.indexes_dir / self.config.get("barrels_binary_dir", "barrels_binary")
            binary_dir.mkdir(parents=True, exist_ok=True)
            
            barrel_bin_path = binary_dir / f"barrel_{barrel_name}.bin"
            barrel_idx_path = binary_dir / f"barrel_{barrel_name}.idx"
            
            # Build binary barrel and index
            index_entries = []  # List of (lemma_id, offset, length) tuples
            
            with open(barrel_bin_path, 'wb') as bin_file:
                for lemma_str, posting in barrel_data.get("postings", {}).items():
                    lemma_id = int(lemma_str)
                    offset = bin_file.tell()
                    
                    df = posting.get("df", 0)
                    docs = posting.get("docs", [])
                    num_docs = len(docs)
                    
                    # Write header: [lemma_id:4][df:4][num_docs:4]
                    bin_file.write(struct.pack('<III', lemma_id, df, num_docs))
                    
                    # Write each posting: [doc_id:20][tf:4]
                    for doc in docs:
                        doc_id = doc["doc_id"]
                        tf = doc["tf"]
                        
                        # Pad/truncate doc_id to 20 bytes
                        doc_id_bytes = doc_id.encode('utf-8')[:20].ljust(20, b'\x00')
                        bin_file.write(doc_id_bytes)
                        bin_file.write(struct.pack('<I', tf))
                    
                    length = bin_file.tell() - offset
                    index_entries.append((lemma_id, offset, length))
            
            # Write binary index file: [numEntries:4][(lemmaId:4, offset:8, length:8)...]
            with open(barrel_idx_path, 'wb') as idx_file:
                num_entries = len(index_entries)
                idx_file.write(struct.pack('<I', num_entries))
                
                for lemma_id, offset, length in index_entries:
                    idx_file.write(struct.pack('<Iqq', lemma_id, offset, length))
            
            print(f"Rebuilt binary barrel {barrel_id} with {len(index_entries)} terms")
            
        except Exception as e:
            print(f"Warning: Failed to rebuild binary barrel {barrel_id}: {e}")
            # Don't fail the entire indexing operation if binary rebuild fails

    def extract_text_from_file(self, file_path: str, content: bytes = None,
                                file_type: str = None) -> Dict[str, str]:
        """
        Extract text content from various file formats.

        Returns dict with keys: title, abstract, body
        """
        if file_type is None and file_path:
            file_type = Path(file_path).suffix.lower().lstrip('.')

        if content is None and file_path:
            with open(file_path, 'rb') as f:
                content = f.read()

        result = {"title": "", "abstract": "", "body": ""}

        try:
            if file_type == 'json':
                data = json_loads(content.decode('utf-8', errors='ignore'))

                # Handle CORD-19 format
                if "metadata" in data and "title" in data["metadata"]:
                    result["title"] = data["metadata"]["title"]
                elif "title" in data:
                    result["title"] = data["title"]

                if "abstract" in data:
                    if isinstance(data["abstract"], list):
                        result["abstract"] = " ".join(
                            entry.get("text", "") for entry in data["abstract"]
                        )
                    else:
                        result["abstract"] = str(data["abstract"])

                if "body_text" in data:
                    if isinstance(data["body_text"], list):
                        result["body"] = " ".join(
                            entry.get("text", "") for entry in data["body_text"]
                        )
                    else:
                        result["body"] = str(data["body_text"])
                elif "content" in data:
                    result["body"] = str(data["content"])
                elif "text" in data:
                    result["body"] = str(data["text"])

            elif file_type == 'txt':
                text = content.decode('utf-8', errors='ignore')
                lines = text.strip().split('\n')

                # First line as title, rest as body
                if lines:
                    result["title"] = lines[0][:200]  # Limit title length
                    result["body"] = "\n".join(lines[1:]) if len(lines) > 1 else lines[0]

            elif file_type == 'md':
                text = content.decode('utf-8', errors='ignore')
                lines = text.strip().split('\n')

                # Find first heading as title
                for i, line in enumerate(lines):
                    if line.startswith('#'):
                        result["title"] = line.lstrip('#').strip()
                        result["body"] = "\n".join(lines[i+1:])
                        break
                else:
                    result["body"] = text

            else:
                # Generic text extraction
                text = content.decode('utf-8', errors='ignore')
                result["body"] = text

        except Exception as e:
            print(f"Error extracting text: {e}")
            # Fallback: treat as plain text
            try:
                result["body"] = content.decode('utf-8', errors='ignore')
            except:
                result["body"] = str(content)

        return result

    def index_document(self, doc_id: str = None,
                       title: str = "",
                       abstract: str = "",
                       body: str = "",
                       authors: List[str] = None,
                       file_path: str = None,
                       file_content: bytes = None,
                       file_type: str = None) -> Dict[str, Any]:
        """
        Index a single document.

        Can accept either:
        - Direct text (title, abstract, body)
        - File path or content

        Returns indexing result with doc_id and statistics.
        """
        start_time = time.time()

        # Generate doc ID if not provided
        if doc_id is None:
            doc_id = f"DOC_{uuid.uuid4().hex[:12].upper()}"

        # Extract text from file if provided
        if file_path or file_content:
            extracted = self.extract_text_from_file(file_path, file_content, file_type)
            if not title:
                title = extracted["title"]
            if not abstract:
                abstract = extracted["abstract"]
            if not body:
                body = extracted["body"]

        # Combine all text
        full_text = f"{title} {abstract} {body}"

        if not full_text.strip():
            return {
                "success": False,
                "error": "No text content found",
                "doc_id": doc_id
            }

        # Convert to lemma IDs
        title_lemmas = self._text_to_lemma_ids(title) if title else []
        abstract_lemmas = self._text_to_lemma_ids(abstract) if abstract else []
        body_lemmas = self._text_to_lemma_ids(body) if body else []

        all_lemmas = title_lemmas + abstract_lemmas + body_lemmas

        if not all_lemmas:
            return {
                "success": False,
                "error": "No valid terms found after tokenization",
                "doc_id": doc_id
            }

        # Count term frequencies
        term_freqs = Counter(all_lemmas)

        # Update barrels with new postings
        # ALWAYS use barrel 10 (new_docs) for ALL terms from newly uploaded documents
        # This is MUCH faster than loading/updating large existing barrels
        # The C++ search already handles reading from barrel 10
        barrels_updated = set()
        for lemma_id, tf in term_freqs.items():
            # Always use barrel 10 for new document terms (fast)
            barrel_id = 10
            self._update_barrel(barrel_id, lemma_id, doc_id, tf)
            barrels_updated.add(barrel_id)

        # Rebuild binary barrels for updated barrels
        for barrel_id in barrels_updated:
            self._rebuild_binary_barrel(barrel_id)

        # Update forward index
        self._update_forward_index(doc_id, all_lemmas, title_lemmas, abstract_lemmas)

        # Update metadata
        self.doc_metadata[doc_id] = {
            "title": title[:500] if title else f"Document {doc_id}",
            "authors": authors or [],
            "abstract": abstract[:1000] if abstract else ""
        }
        self._save_metadata()

        # Save updated lexicon if new terms were added
        if self.new_terms:
            self._save_lexicon()
            self._save_barrel_lookup()

        elapsed = time.time() - start_time

        return {
            "success": True,
            "doc_id": doc_id,
            "title": title[:100] if title else doc_id,
            "total_terms": len(all_lemmas),
            "unique_terms": len(term_freqs),
            "new_terms_added": len(self.new_terms),
            "barrels_updated": list(barrels_updated),
            "indexing_time_ms": int(elapsed * 1000)
        }


# Singleton instance for API use
_indexer_instance = None

def get_indexer() -> DocumentIndexer:
    """Get or create the singleton indexer instance."""
    global _indexer_instance
    if _indexer_instance is None:
        _indexer_instance = DocumentIndexer()
    return _indexer_instance


def index_document_fast(doc_id: str = None,
                        title: str = "",
                        abstract: str = "",
                        body: str = "",
                        authors: List[str] = None,
                        file_content: bytes = None,
                        file_type: str = None) -> Dict[str, Any]:
    """
    Convenience function to index a document.
    Uses the singleton indexer for efficiency.
    """
    indexer = get_indexer()
    return indexer.index_document(
        doc_id=doc_id,
        title=title,
        abstract=abstract,
        body=body,
        authors=authors,
        file_content=file_content,
        file_type=file_type
    )


if __name__ == "__main__":
    # Test the indexer
    indexer = DocumentIndexer()

    # Test with sample text
    result = indexer.index_document(
        title="Test Document About COVID-19 Vaccines",
        abstract="This is a test abstract about coronavirus vaccines and their effectiveness.",
        body="The body text contains more detailed information about vaccine development and clinical trials.",
        authors=["Test Author"]
    )

    print(f"Indexing result: {json.dumps(result, indent=2)}")
