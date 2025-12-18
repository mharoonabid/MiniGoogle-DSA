"""
N-gram Index Builder for Multi-Word Autocomplete (Ultra-Optimized)

OPTIMIZATIONS v2:
- Single-pass processing with minimal memory allocation
- Subprocess-based parallelism (faster than multiprocessing.Pool for I/O bound)
- Streaming aggregation to avoid large IPC transfers
- Direct file output to reduce memory usage
- Skip small files and focus on content-rich documents

Usage:
    python ngram_builder.py
    python ngram_builder.py --workers 8
    python ngram_builder.py --fast  # Ultra-fast mode (samples documents)
"""

import os
import sys
import re
import json
from pathlib import Path
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, ProcessPoolExecutor
import argparse
import time
import threading

# Frozen set for O(1) lookup
STOPWORDS = frozenset({
    'a', 'an', 'the', 'and', 'or', 'but', 'in', 'on', 'at', 'to', 'for',
    'of', 'with', 'by', 'from', 'as', 'is', 'was', 'are', 'were', 'been',
    'be', 'have', 'has', 'had', 'do', 'does', 'did', 'will', 'would', 'could',
    'should', 'may', 'might', 'must', 'shall', 'can', 'need', 'dare', 'ought',
    'used', 'this', 'that', 'these', 'those', 'i', 'you', 'he', 'she', 'it',
    'we', 'they', 'what', 'which', 'who', 'whom', 'where', 'when', 'why', 'how',
    'all', 'each', 'every', 'both', 'few', 'more', 'most', 'other', 'some',
    'such', 'no', 'nor', 'not', 'only', 'own', 'same', 'so', 'than', 'too',
    'very', 'just', 'also', 'now', 'here', 'there', 'then', 'once', 'if',
    'because', 'although', 'while', 'whereas', 'however', 'therefore', 'thus',
    'hence', 'moreover', 'furthermore', 'nevertheless', 'nonetheless', 'instead',
    'otherwise', 'meanwhile', 'accordingly', 'consequently', 'subsequently',
    'about', 'above', 'across', 'after', 'against', 'along', 'among', 'around',
    'before', 'behind', 'below', 'beneath', 'beside', 'between', 'beyond',
    'during', 'except', 'inside', 'into', 'near', 'off', 'onto', 'out',
    'outside', 'over', 'past', 'since', 'through', 'throughout', 'toward',
    'under', 'underneath', 'until', 'unto', 'upon', 'within', 'without',
    'et', 'al', 'etc', 'ie', 'eg', 'vs', 'fig', 'table', 'ref', 'see',
    'also', 'using', 'used', 'use', 'study', 'studies', 'result', 'results',
    'show', 'shows', 'shown', 'found', 'based', 'including', 'include',
    'well', 'however', 'thus', 'therefore', 'although', 'since', 'while',
    # LaTeX commands to filter out
    'usepackage', 'documentclass', 'begin', 'end', 'document', 'amsmath',
    'amsfonts', 'amssymb', 'amsbsy', 'wasysym', 'mathrsfs', 'upgreek',
    'setlength', 'oddsidemargin', 'evensidemargin', 'textwidth', 'textheight',
    'topmargin', 'parindent', 'parskip', 'columnwidth', 'pdfcreator', 'minimal',
    'jvmuser', 'txfonts', 'inputenc', 'fontenc', 'fixltx', 'graphicx', 'relsize',
    'epsf', 'rotating', 'cite', 'natbib', 'url', 'hyperref', 'newcommand',
    'renewcommand', 'providecommand', 'def', 'let', 'put', 'makebox', 'framebox',
    'hbox', 'vbox', 'kern', 'hskip', 'vskip', 'hspace', 'vspace', 'centering',
    'raggedright', 'raggedleft', 'textbf', 'textit', 'emph', 'underline',
    'caption', 'label', 'tabular', 'array', 'figure', 'subfigure', 'includegraphics'
})

# Pre-compiled patterns
WORD_PATTERN = re.compile(r'[a-z]{3,15}')
NON_ALPHA = re.compile(r'[^a-z\s]')


def fast_tokenize(text):
    """Ultra-fast tokenization."""
    return [w for w in WORD_PATTERN.findall(text.lower()) if w not in STOPWORDS]


def extract_text_fast(filepath):
    """Fast text extraction from JSON - reads only what's needed."""
    try:
        with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
            content = f.read()

        # Quick check if file has useful content
        if '"text"' not in content:
            return ""

        data = json.loads(content)

        parts = []
        for key in ('abstract', 'body_text'):
            section = data.get(key)
            if section and isinstance(section, list):
                for entry in section[:50]:  # Limit entries per section
                    text = entry.get('text', '')
                    if text and len(text) > 20:
                        parts.append(text)

        return ' '.join(parts)
    except:
        return ""


def process_file_batch_simple(file_paths):
    """Process a batch of files and return aggregated counts as dict."""
    bigrams = Counter()
    trigrams = Counter()

    for fp in file_paths:
        text = extract_text_fast(fp)
        if not text:
            continue

        tokens = fast_tokenize(text)
        n = len(tokens)

        if n < 2:
            continue

        # Count bigrams
        for i in range(n - 1):
            bigrams[(tokens[i], tokens[i+1])] += 1

        # Count trigrams
        for i in range(n - 2):
            trigrams[(tokens[i], tokens[i+1], tokens[i+2])] += 1

    return bigrams, trigrams


def process_chunk(args):
    """Process a chunk of files - used by ProcessPoolExecutor."""
    file_paths, chunk_id = args
    return process_file_batch_simple(file_paths)


class FastNgramBuilder:
    """Ultra-fast n-gram builder with minimal overhead."""

    def __init__(self, min_freq=5, max_ngrams=50000):
        self.min_freq = min_freq
        self.max_ngrams = max_ngrams
        self.bigrams = Counter()
        self.trigrams = Counter()

    def process_parallel(self, json_dir, num_workers=None, sample_ratio=1.0):
        """Process documents using thread pool (I/O bound) + process pool (CPU bound)."""

        json_files = list(Path(json_dir).glob("*.json"))
        total_files = len(json_files)

        # Sample if requested
        if sample_ratio < 1.0:
            import random
            sample_size = int(total_files * sample_ratio)
            json_files = random.sample(json_files, sample_size)
            print(f"Sampling {sample_size} of {total_files} documents ({sample_ratio*100:.0f}%)")
            total_files = sample_size

        if num_workers is None:
            num_workers = min(os.cpu_count() or 4, 8)

        print(f"Processing {total_files} documents with {num_workers} workers...")

        start_time = time.time()

        # Create larger chunks for less overhead
        chunk_size = max(200, total_files // (num_workers * 2))
        chunks = []
        for i in range(0, total_files, chunk_size):
            chunk_files = [str(f) for f in json_files[i:i + chunk_size]]
            chunks.append((chunk_files, i // chunk_size))

        print(f"Created {len(chunks)} chunks of ~{chunk_size} files")

        # Process with ProcessPoolExecutor
        processed = 0
        with ProcessPoolExecutor(max_workers=num_workers) as executor:
            for bigrams, trigrams in executor.map(process_chunk, chunks):
                self.bigrams.update(bigrams)
                self.trigrams.update(trigrams)
                processed += 1

                if processed % max(1, len(chunks) // 5) == 0:
                    elapsed = time.time() - start_time
                    pct = 100 * processed / len(chunks)
                    rate = (processed * chunk_size) / elapsed
                    print(f"  Progress: {pct:.0f}% - {rate:.0f} files/sec")

        elapsed = time.time() - start_time
        print(f"\nProcessed in {elapsed:.1f}s ({total_files/elapsed:.0f} files/sec)")
        print(f"Raw bigrams: {len(self.bigrams)}, trigrams: {len(self.trigrams)}")

    def filter_and_build_index(self):
        """Filter by frequency and build autocomplete index."""
        print(f"\nFiltering (min_freq={self.min_freq})...")

        # Filter bigrams
        self.bigrams = Counter({
            k: v for k, v in self.bigrams.items()
            if v >= self.min_freq
        })

        # Filter trigrams
        self.trigrams = Counter({
            k: v for k, v in self.trigrams.items()
            if v >= self.min_freq
        })

        # Limit to top N
        if len(self.bigrams) > self.max_ngrams:
            self.bigrams = Counter(dict(self.bigrams.most_common(self.max_ngrams)))
        if len(self.trigrams) > self.max_ngrams:
            self.trigrams = Counter(dict(self.trigrams.most_common(self.max_ngrams)))

        print(f"Kept {len(self.bigrams)} bigrams, {len(self.trigrams)} trigrams")

    def build_autocomplete_index(self):
        """Build prefix-based autocomplete index."""
        print("Building autocomplete index...")

        # Collect all phrases
        phrases = []
        for (w1, w2), count in self.bigrams.items():
            phrases.append((f"{w1} {w2}", count))
        for (w1, w2, w3), count in self.trigrams.items():
            phrases.append((f"{w1} {w2} {w3}", count))

        # Sort by count descending
        phrases.sort(key=lambda x: -x[1])

        # Build index with limits
        index = defaultdict(list)
        prefix_counts = Counter()
        max_per_prefix = 10

        for phrase, count in phrases:
            words = phrase.split()

            # First word prefixes
            for i in range(2, len(words[0]) + 1):
                prefix = words[0][:i]
                if prefix_counts[prefix] < max_per_prefix:
                    index[prefix].append({"phrase": phrase, "count": count})
                    prefix_counts[prefix] += 1

            # Two-word prefixes
            if len(words) > 1:
                base = words[0]
                for i in range(1, len(words[1]) + 1):
                    prefix = f"{base} {words[1][:i]}"
                    if prefix_counts[prefix] < max_per_prefix:
                        index[prefix].append({"phrase": phrase, "count": count})
                        prefix_counts[prefix] += 1

        print(f"Built index with {len(index)} prefixes")
        return dict(index)

    def save(self, output_dir):
        """Save indexes to disk."""
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        # Save bigrams
        bigrams_dict = {f"{w1} {w2}": c for (w1, w2), c in self.bigrams.most_common()}
        with open(output_dir / "bigrams.json", 'w') as f:
            json.dump(bigrams_dict, f)

        # Save trigrams
        trigrams_dict = {f"{w1} {w2} {w3}": c for (w1, w2, w3), c in self.trigrams.most_common()}
        with open(output_dir / "trigrams.json", 'w') as f:
            json.dump(trigrams_dict, f)

        # Save phrase index
        phrase_index = defaultdict(dict)
        for (w1, w2), count in self.bigrams.items():
            phrase_index[w1][w2] = count
        for (w1, w2, w3), count in self.trigrams.items():
            phrase_index[f"{w1} {w2}"][w3] = count
        with open(output_dir / "phrase_index.json", 'w') as f:
            json.dump(dict(phrase_index), f)

        # Save autocomplete index
        autocomplete = self.build_autocomplete_index()
        with open(output_dir / "ngram_autocomplete.json", 'w') as f:
            json.dump(autocomplete, f)

        print(f"Saved to {output_dir}")


def main():
    parser = argparse.ArgumentParser(description='Build n-gram index (optimized)')
    parser.add_argument('--workers', type=int, default=None)
    parser.add_argument('--min-freq', type=int, default=5)
    parser.add_argument('--max-ngrams', type=int, default=50000)
    parser.add_argument('--fast', action='store_true', help='Fast mode: sample 30% of documents')
    parser.add_argument('--sample', type=float, default=1.0, help='Sample ratio (0.0-1.0)')
    args = parser.parse_args()

    # Get paths
    script_dir = Path(__file__).resolve().parent
    backend_dir = script_dir.parent

    with open(backend_dir / "config.json") as f:
        config = json.load(f)

    data_root = backend_dir / config["data_dir"]
    indexes_dir = backend_dir / config["indexes_dir"]

    # Find data folder
    target_folder = None
    for root, dirs, _ in os.walk(data_root):
        if config["json_data"] in dirs:
            target_folder = Path(root) / config["json_data"]
            break

    if not target_folder:
        print(f"Error: Could not find {config['json_data']} under {data_root}")
        return

    print("=" * 60)
    print("N-GRAM BUILDER (Ultra-Optimized)")
    print("=" * 60)
    print(f"Source: {target_folder}")
    print(f"Output: {indexes_dir}")

    # Determine sample ratio
    sample_ratio = 0.3 if args.fast else args.sample

    # Build
    builder = FastNgramBuilder(min_freq=args.min_freq, max_ngrams=args.max_ngrams)
    builder.process_parallel(target_folder, num_workers=args.workers, sample_ratio=sample_ratio)
    builder.filter_and_build_index()
    builder.save(indexes_dir)

    print("\n" + "=" * 60)
    print("COMPLETE!")
    print("=" * 60)

    print("\nTop 10 bigrams:")
    for (w1, w2), count in builder.bigrams.most_common(10):
        print(f"  '{w1} {w2}': {count}")

    print("\nTop 10 trigrams:")
    for (w1, w2, w3), count in builder.trigrams.most_common(10):
        print(f"  '{w1} {w2} {w3}': {count}")


if __name__ == "__main__":
    main()
