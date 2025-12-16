"""
Word Embeddings Setup Script

Downloads GloVe embeddings and converts to binary format for fast C++ loading.
Also builds a Trie index for autocomplete functionality.

Usage:
    python embeddings_setup.py

This will:
1. Download GloVe embeddings (glove.6B.50d.txt - 50 dimensions, ~66MB)
2. Convert to binary format for fast loading
3. Build word->index mapping
4. Create Trie index from lexicon for autocomplete
"""

import os
import sys
import json
import struct
import urllib.request
import zipfile
from pathlib import Path
from collections import defaultdict
import numpy as np

# Configuration
GLOVE_URL = "https://nlp.stanford.edu/data/glove.6B.zip"
GLOVE_FILE = "glove.6B.50d.txt"  # Using 50-dimensional for speed
EMBEDDING_DIM = 50

def get_paths():
    """Get project paths."""
    script_dir = Path(__file__).parent.resolve()
    backend_dir = script_dir.parent
    indexes_dir = backend_dir / "indexes"
    embeddings_dir = indexes_dir / "embeddings"
    embeddings_dir.mkdir(parents=True, exist_ok=True)

    return {
        "backend": backend_dir,
        "indexes": indexes_dir,
        "embeddings": embeddings_dir,
        "lexicon": indexes_dir / "lexicon.json"
    }

def download_glove(paths):
    """Download GloVe embeddings if not present."""
    embeddings_dir = paths["embeddings"]
    glove_txt = embeddings_dir / GLOVE_FILE
    glove_zip = embeddings_dir / "glove.6B.zip"

    if glove_txt.exists():
        print(f"GloVe file already exists: {glove_txt}")
        return glove_txt

    print(f"Downloading GloVe embeddings from {GLOVE_URL}...")
    print("This may take a few minutes (~862MB download)...")

    try:
        urllib.request.urlretrieve(GLOVE_URL, glove_zip, reporthook=download_progress)
        print("\nExtracting...")

        with zipfile.ZipFile(glove_zip, 'r') as zip_ref:
            zip_ref.extract(GLOVE_FILE, embeddings_dir)

        # Clean up zip file to save space
        os.remove(glove_zip)
        print(f"Extracted to {glove_txt}")

        return glove_txt

    except Exception as e:
        print(f"\nError downloading GloVe: {e}")
        print("\nManual download instructions:")
        print(f"1. Download from: {GLOVE_URL}")
        print(f"2. Extract {GLOVE_FILE} to: {embeddings_dir}")
        sys.exit(1)

def download_progress(count, block_size, total_size):
    """Progress callback for download."""
    percent = int(count * block_size * 100 / total_size)
    sys.stdout.write(f"\rDownloading: {percent}%")
    sys.stdout.flush()

def load_lexicon(paths):
    """Load lexicon to filter embeddings."""
    lexicon_path = paths["lexicon"]

    if not lexicon_path.exists():
        print(f"Warning: Lexicon not found at {lexicon_path}")
        return set()

    with open(lexicon_path, 'r') as f:
        lexicon = json.load(f)

    # Get all words from lexicon
    words = set(lexicon.get("wordID", {}).keys())
    print(f"Loaded {len(words)} words from lexicon")

    return words, lexicon

def convert_to_binary(glove_path, paths, lexicon_words):
    """Convert GloVe text to binary format, filtering to lexicon words."""
    embeddings_dir = paths["embeddings"]

    # Output files
    vectors_bin = embeddings_dir / "embeddings.bin"
    vocab_json = embeddings_dir / "vocab.json"

    print(f"\nConverting GloVe to binary format...")
    print(f"Filtering to {len(lexicon_words)} lexicon words...")

    word_to_idx = {}
    vectors = []

    with open(glove_path, 'r', encoding='utf-8') as f:
        for line_num, line in enumerate(f):
            if line_num % 100000 == 0:
                print(f"  Processed {line_num} lines...")

            parts = line.strip().split()
            if len(parts) != EMBEDDING_DIM + 1:
                continue

            word = parts[0]

            # Only keep words in our lexicon (or common words)
            if lexicon_words and word not in lexicon_words:
                # Also keep top common words for semantic expansion
                if line_num > 50000:  # GloVe is sorted by frequency
                    continue

            try:
                vector = [float(x) for x in parts[1:]]
                word_to_idx[word] = len(vectors)
                vectors.append(vector)
            except ValueError:
                continue

    print(f"  Kept {len(vectors)} word vectors")

    # Normalize vectors for faster cosine similarity (just dot product after normalization)
    vectors = np.array(vectors, dtype=np.float32)
    norms = np.linalg.norm(vectors, axis=1, keepdims=True)
    norms[norms == 0] = 1  # Avoid division by zero
    vectors = vectors / norms

    # Write binary file
    # Format: [num_words:4][dim:4][vectors:num_words*dim*4]
    print(f"Writing binary file: {vectors_bin}")

    with open(vectors_bin, 'wb') as f:
        f.write(struct.pack('I', len(vectors)))  # num words
        f.write(struct.pack('I', EMBEDDING_DIM))  # dimension
        f.write(vectors.tobytes())  # all vectors

    # Write vocabulary mapping
    print(f"Writing vocabulary: {vocab_json}")

    with open(vocab_json, 'w') as f:
        json.dump(word_to_idx, f)

    print(f"Binary embeddings: {vectors_bin.stat().st_size / 1024 / 1024:.1f} MB")
    print(f"Vocabulary size: {len(word_to_idx)} words")

    return word_to_idx

def build_trie_index(paths, lexicon_data):
    """Build Trie index from lexicon for autocomplete."""
    embeddings_dir = paths["embeddings"]

    print("\nBuilding Trie index for autocomplete...")

    word_id = lexicon_data.get("wordID", {})
    word_to_lemma = lexicon_data.get("wordToLemmaID", {})

    # Load document frequencies from inverted index
    word_df = {}
    inverted_path = paths["indexes"] / "inverted_index.txt"
    if inverted_path.exists():
        print("  Loading document frequencies...")
        lemma_df = {}
        with open(inverted_path, 'r') as f:
            for line in f:
                parts = line.strip().split('|')
                if len(parts) >= 2:
                    try:
                        lemma_id = int(parts[0])
                        df = int(parts[1])
                        lemma_df[lemma_id] = df
                    except ValueError:
                        continue

        # Map words to their DF via word_id -> lemma_id -> df
        for word, wid in word_id.items():
            wid_str = str(wid)
            if wid_str in word_to_lemma:
                lemma_id = word_to_lemma[wid_str]
                word_df[word] = lemma_df.get(lemma_id, 1)
            elif wid in lemma_df:
                word_df[word] = lemma_df[wid]
            else:
                word_df[word] = 1

    # Filter and sort words
    words_with_df = []
    for word in word_id.keys():
        if len(word) >= 2 and word.isalpha():
            words_with_df.append((word.lower(), word_df.get(word, 1)))

    # Sort by word for efficient prefix search
    words_with_df.sort(key=lambda x: x[0])

    # Save as simple text format: word|df (sorted by word)
    trie_txt = embeddings_dir / "trie.txt"
    print(f"  Writing word list: {trie_txt}")

    with open(trie_txt, 'w') as f:
        for word, df in words_with_df:
            f.write(f"{word}|{df}\n")

    print(f"  Word list size: {trie_txt.stat().st_size / 1024 / 1024:.1f} MB")
    print(f"  Indexed {len(words_with_df)} words")

    # Create a multi-level prefix index for efficient autocomplete
    # Level 1: 2-char prefix -> top 100 words (for short queries)
    # Level 2: 3-char prefix -> top 50 words (for longer queries)
    prefix_index = {}

    # Build 2-char and 3-char prefix indexes
    for word, df in words_with_df:
        if len(word) >= 2:
            p2 = word[:2]
            if p2 not in prefix_index:
                prefix_index[p2] = []
            prefix_index[p2].append({"w": word, "d": df})

        if len(word) >= 3:
            p3 = word[:3]
            if p3 not in prefix_index:
                prefix_index[p3] = []
            prefix_index[p3].append({"w": word, "d": df})

    # Sort each prefix group by df descending
    for prefix in prefix_index:
        prefix_index[prefix].sort(key=lambda x: -x["d"])
        # Keep top 100 for 2-char, top 50 for 3-char+
        limit = 100 if len(prefix) == 2 else 50
        prefix_index[prefix] = prefix_index[prefix][:limit]

    trie_json = embeddings_dir / "autocomplete.json"
    print(f"  Writing prefix index: {trie_json}")
    with open(trie_json, 'w') as f:
        json.dump(prefix_index, f, separators=(',', ':'))

    print(f"  Prefix index size: {trie_json.stat().st_size / 1024 / 1024:.1f} MB")
    print(f"  Prefix groups: {len(prefix_index)}")

    return prefix_index

def compute_document_scores(paths):
    """Compute simple PageRank-like scores for documents."""
    embeddings_dir = paths["embeddings"]
    scores_path = embeddings_dir / "doc_scores.json"

    print("\nComputing document authority scores...")

    # Load forward index to get document statistics
    forward_index_path = paths["indexes"] / "forward_index.txt"

    if not forward_index_path.exists():
        print("  Forward index not found, skipping document scores")
        return {}

    doc_stats = {}

    with open(forward_index_path, 'r') as f:
        for line_num, line in enumerate(f):
            if line_num % 10000 == 0:
                print(f"  Processed {line_num} documents...")

            parts = line.strip().split('|')
            if len(parts) < 2:
                continue

            doc_id = parts[0]
            total_terms = int(parts[1]) if parts[1].isdigit() else 0

            # Count unique terms in each section
            title_terms = set(parts[2].split(',')) if len(parts) > 2 and parts[2] else set()
            abstract_terms = set(parts[3].split(',')) if len(parts) > 3 and parts[3] else set()
            body_terms = set(parts[4].split(',')) if len(parts) > 4 and parts[4] else set()

            # Remove empty strings
            title_terms.discard('')
            abstract_terms.discard('')
            body_terms.discard('')

            unique_terms = len(title_terms | abstract_terms | body_terms)

            doc_stats[doc_id] = {
                'total_terms': total_terms,
                'unique_terms': unique_terms,
                'has_title': len(title_terms) > 0,
                'has_abstract': len(abstract_terms) > 0
            }

    # Compute PageRank-like score
    # Factors:
    # 1. Term diversity (unique_terms / total_terms) - documents with diverse vocabulary
    # 2. Completeness (has title + abstract)
    # 3. Length normalization

    print("  Computing authority scores...")

    # Get statistics for normalization
    total_terms_list = [d['total_terms'] for d in doc_stats.values() if d['total_terms'] > 0]
    unique_terms_list = [d['unique_terms'] for d in doc_stats.values() if d['unique_terms'] > 0]

    if not total_terms_list:
        print("  No valid documents found")
        return {}

    avg_length = np.mean(total_terms_list)
    max_unique = max(unique_terms_list)

    doc_scores = {}

    for doc_id, stats in doc_stats.items():
        if stats['total_terms'] == 0:
            doc_scores[doc_id] = 0.1
            continue

        # Term diversity score (0-1)
        diversity = stats['unique_terms'] / max(stats['total_terms'], 1)
        diversity = min(diversity, 1.0)

        # Completeness score
        completeness = 0.5
        if stats['has_title']:
            completeness += 0.25
        if stats['has_abstract']:
            completeness += 0.25

        # Length normalization (BM25-style)
        length_norm = 1.0 / (1.0 + 0.5 * (stats['total_terms'] / avg_length - 1))
        length_norm = max(0.5, min(length_norm, 1.5))

        # Combined score (0-1 range, normalized)
        score = 0.4 * diversity + 0.3 * completeness + 0.3 * length_norm
        doc_scores[doc_id] = round(score, 4)

    # Save scores
    print(f"  Writing scores: {scores_path}")
    with open(scores_path, 'w') as f:
        json.dump(doc_scores, f)

    print(f"  Computed scores for {len(doc_scores)} documents")

    # Print statistics
    scores_list = list(doc_scores.values())
    print(f"  Score range: {min(scores_list):.3f} - {max(scores_list):.3f}")
    print(f"  Average score: {np.mean(scores_list):.3f}")

    return doc_scores

def build_binary_lexicon(paths, lexicon_data):
    """Build binary lexicon for fast C++ loading."""
    embeddings_dir = paths["embeddings"]

    print("\nBuilding binary lexicon...")

    word_id = lexicon_data.get("wordID", {})
    word_to_lemma = lexicon_data.get("wordToLemmaID", {})

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
    # Format: [num_words:4][word_lengths:num_words*2][words:variable][lemma_ids:num_words*4]
    bin_path = embeddings_dir / "lexicon.bin"

    with open(bin_path, 'wb') as f:
        import struct

        # Header
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

    print(f"  Written {len(words)} words to {bin_path}")
    print(f"  Binary lexicon size: {bin_path.stat().st_size / 1024 / 1024:.1f} MB")

    return words


def main():
    import argparse
    parser = argparse.ArgumentParser(description='MiniGoogle Embeddings & Index Setup')
    parser.add_argument('--skip-embeddings', action='store_true',
                       help='Skip downloading/processing embeddings')
    parser.add_argument('--trie-only', action='store_true',
                       help='Only build Trie index')
    parser.add_argument('--scores-only', action='store_true',
                       help='Only compute document scores')
    parser.add_argument('--all', action='store_true',
                       help='Build all indexes (default)')
    args = parser.parse_args()

    print("=" * 50)
    print("  MiniGoogle Embeddings & Index Setup")
    print("=" * 50)

    paths = get_paths()

    # Load lexicon
    lexicon_words, lexicon_data = load_lexicon(paths)

    # Build Trie for autocomplete (always - doesn't need embeddings)
    if not args.scores_only:
        build_trie_index(paths, lexicon_data)
        build_binary_lexicon(paths, lexicon_data)

    # Compute document scores (always - doesn't need embeddings)
    if not args.trie_only:
        compute_document_scores(paths)

    # Download and process embeddings (optional)
    if not args.skip_embeddings and not args.trie_only and not args.scores_only:
        try:
            glove_path = download_glove(paths)
            vocab = convert_to_binary(glove_path, paths, lexicon_words)
        except Exception as e:
            print(f"\nWarning: Embeddings setup failed: {e}")
            print("Semantic word similarity will be disabled.")
            print("Other features (autocomplete, PageRank) will still work.")

    print("\n" + "=" * 50)
    print("  Setup Complete!")
    print("=" * 50)
    print(f"\nFiles created in: {paths['embeddings']}")
    if (paths['embeddings'] / 'embeddings.bin').exists():
        print("  - embeddings.bin     (word vectors)")
        print("  - vocab.json         (word -> index mapping)")
    if (paths['embeddings'] / 'autocomplete.json').exists():
        print("  - autocomplete.json  (autocomplete index)")
    if (paths['embeddings'] / 'trie.txt').exists():
        print("  - trie.txt           (word list for autocomplete)")
    if (paths['embeddings'] / 'doc_scores.json').exists():
        print("  - doc_scores.json    (document authority scores)")

if __name__ == '__main__':
    main()
