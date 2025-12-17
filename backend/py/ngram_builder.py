"""
N-gram Index Builder for Multi-Word Autocomplete

Analyzes the document corpus to find common 2-word and 3-word phrases.
Builds a frequency index for fast multi-word autocomplete suggestions.

Usage:
    python ngram_builder.py
    python ngram_builder.py --workers 8  # Use 8 parallel workers

Output:
    indexes/ngrams.json - Phrase frequency index
    indexes/ngram_trie.json - Optimized trie structure for autocomplete
"""

import os
import json
import re
from pathlib import Path
from collections import defaultdict, Counter
from concurrent.futures import ProcessPoolExecutor, as_completed
from multiprocessing import cpu_count
import argparse

# Try to import tqdm, fallback to simple progress if not available
try:
    from tqdm import tqdm
    HAS_TQDM = True
except ImportError:
    HAS_TQDM = False
    def tqdm(iterable, **kwargs):
        total = kwargs.get('total', len(iterable) if hasattr(iterable, '__len__') else None)
        for i, item in enumerate(iterable):
            if total and i % max(1, total // 20) == 0:
                print(f"  Progress: {i}/{total} ({100*i//total}%)")
            yield item

# Simple stopwords set (avoids NLTK dependency for speed)
STOPWORDS = {
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
    'et', 'al', 'etc', 'ie', 'eg', 'vs', 'fig', 'table', 'ref', 'see'
}

# Compile regex once for speed
WORD_PATTERN = re.compile(r'\b[a-z]{3,}\b')
CLEAN_PATTERN = re.compile(r'[^a-z\s]')


def fast_tokenize(text):
    """Fast tokenization using regex - much faster than NLTK."""
    text = text.lower()
    text = CLEAN_PATTERN.sub(' ', text)
    words = WORD_PATTERN.findall(text)
    return [w for w in words if w not in STOPWORDS]


def process_single_file(file_path):
    """Process a single JSON file and extract n-grams. Used for multiprocessing."""
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            data = json.load(f)

        # Extract text from abstract and body
        text_parts = []
        for key in ["abstract", "body_text"]:
            if key in data:
                for entry in data[key]:
                    text_parts.append(entry.get("text", ""))

        full_text = "\n".join(text_parts)
        tokens = fast_tokenize(full_text)

        # Extract bigrams and trigrams
        bigrams = []
        trigrams = []

        for i in range(len(tokens) - 1):
            bigrams.append((tokens[i], tokens[i+1]))

        for i in range(len(tokens) - 2):
            trigrams.append((tokens[i], tokens[i+1], tokens[i+2]))

        return bigrams, trigrams

    except Exception:
        return [], []


class NgramBuilder:
    """Builds n-gram phrase index from document corpus."""

    def __init__(self, min_freq=5, max_ngrams=100000):
        """
        Args:
            min_freq: Minimum frequency for phrase to be included
            max_ngrams: Maximum number of phrases to store
        """
        self.min_freq = min_freq
        self.max_ngrams = max_ngrams

        # N-gram counters
        self.bigrams = Counter()
        self.trigrams = Counter()

        # Phrase index: "covid" -> {"vaccine": 1500, "pandemic": 1200}
        self.phrase_index = defaultdict(lambda: defaultdict(int))

    def process_documents_parallel(self, json_dir, num_workers=None):
        """Process all JSON documents using parallel workers."""
        json_files = list(Path(json_dir).glob("*.json"))
        total_files = len(json_files)
        print(f"Processing {total_files} documents with {num_workers or cpu_count()} workers...")

        if num_workers is None:
            num_workers = min(cpu_count(), 8)  # Cap at 8 workers

        processed = 0
        batch_size = 500  # Process in batches for better memory management

        with ProcessPoolExecutor(max_workers=num_workers) as executor:
            # Process in batches
            for batch_start in range(0, total_files, batch_size):
                batch_end = min(batch_start + batch_size, total_files)
                batch_files = json_files[batch_start:batch_end]

                # Submit batch
                futures = {executor.submit(process_single_file, f): f for f in batch_files}

                # Collect results
                for future in as_completed(futures):
                    bigrams, trigrams = future.result()
                    self.bigrams.update(bigrams)
                    self.trigrams.update(trigrams)
                    processed += 1

                    if processed % 1000 == 0:
                        print(f"  Processed {processed}/{total_files} documents ({100*processed//total_files}%)")

        print(f"\nExtracted {len(self.bigrams)} unique bigrams")
        print(f"Extracted {len(self.trigrams)} unique trigrams")

    def process_documents(self, json_dir):
        """Process documents sequentially (fallback for single-threaded mode)."""
        json_files = list(Path(json_dir).glob("*.json"))
        print(f"Processing {len(json_files)} documents...")

        for json_file in tqdm(json_files, desc="Processing"):
            bigrams, trigrams = process_single_file(json_file)
            self.bigrams.update(bigrams)
            self.trigrams.update(trigrams)

        print(f"\nExtracted {len(self.bigrams)} unique bigrams")
        print(f"Extracted {len(self.trigrams)} unique trigrams")

    def filter_and_rank(self):
        """Filter low-frequency phrases and rank by popularity."""
        print(f"\nFiltering phrases (min_freq={self.min_freq})...")

        # Filter bigrams
        filtered_bigrams = {
            phrase: count
            for phrase, count in self.bigrams.items()
            if count >= self.min_freq
        }

        # Filter trigrams
        filtered_trigrams = {
            phrase: count
            for phrase, count in self.trigrams.items()
            if count >= self.min_freq
        }

        print(f"Kept {len(filtered_bigrams)} bigrams")
        print(f"Kept {len(filtered_trigrams)} trigrams")

        # Update counters
        self.bigrams = Counter(filtered_bigrams)
        self.trigrams = Counter(filtered_trigrams)

        # Limit to max_ngrams
        if len(self.bigrams) > self.max_ngrams:
            self.bigrams = Counter(dict(self.bigrams.most_common(self.max_ngrams)))
        if len(self.trigrams) > self.max_ngrams:
            self.trigrams = Counter(dict(self.trigrams.most_common(self.max_ngrams)))

        # Build phrase index from filtered data
        print("Building phrase index...")
        for (w1, w2), count in self.bigrams.items():
            self.phrase_index[w1][w2] = count

        for (w1, w2, w3), count in self.trigrams.items():
            prefix = f"{w1} {w2}"
            self.phrase_index[prefix][w3] = count

    def build_autocomplete_index(self):
        """Build optimized index for autocomplete: prefix -> suggestions."""
        print("\nBuilding autocomplete index...")

        # Collect all phrases with counts
        all_phrases = []

        for (word1, word2), count in self.bigrams.items():
            phrase = f"{word1} {word2}"
            all_phrases.append((phrase, count))

        for (word1, word2, word3), count in self.trigrams.items():
            phrase = f"{word1} {word2} {word3}"
            all_phrases.append((phrase, count))

        # Sort by count descending for efficient prefix building
        all_phrases.sort(key=lambda x: x[1], reverse=True)

        # Build prefix index using defaultdict for speed
        autocomplete_index = defaultdict(list)
        prefix_counts = Counter()  # Track how many items per prefix

        for phrase, count in all_phrases:
            words = phrase.split()

            # Generate prefixes for first word
            for i in range(1, len(words[0]) + 1):
                prefix = words[0][:i]
                if prefix_counts[prefix] < 10:  # Keep max 10 per prefix
                    autocomplete_index[prefix].append({"phrase": phrase, "count": count})
                    prefix_counts[prefix] += 1

            # Generate prefixes for "first second" combination
            if len(words) > 1:
                for i in range(1, len(words[1]) + 1):
                    prefix = f"{words[0]} {words[1][:i]}"
                    if prefix_counts[prefix] < 10:
                        autocomplete_index[prefix].append({"phrase": phrase, "count": count})
                        prefix_counts[prefix] += 1

            # Generate prefixes for "first second third" combination
            if len(words) > 2:
                for i in range(1, len(words[2]) + 1):
                    prefix = f"{words[0]} {words[1]} {words[2][:i]}"
                    if prefix_counts[prefix] < 10:
                        autocomplete_index[prefix].append({"phrase": phrase, "count": count})
                        prefix_counts[prefix] += 1

        print(f"Built index for {len(autocomplete_index)} prefixes")
        return dict(autocomplete_index)

    def save(self, output_dir):
        """Save n-gram indices to JSON files."""
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        # Save bigrams
        bigrams_file = output_dir / "bigrams.json"
        with open(bigrams_file, 'w', encoding='utf-8') as f:
            bigrams_dict = {
                f"{w1} {w2}": count
                for (w1, w2), count in self.bigrams.most_common()
            }
            json.dump(bigrams_dict, f)
        print(f"Saved bigrams to {bigrams_file}")

        # Save trigrams
        trigrams_file = output_dir / "trigrams.json"
        with open(trigrams_file, 'w', encoding='utf-8') as f:
            trigrams_dict = {
                f"{w1} {w2} {w3}": count
                for (w1, w2, w3), count in self.trigrams.most_common()
            }
            json.dump(trigrams_dict, f)
        print(f"Saved trigrams to {trigrams_file}")

        # Save phrase index (for API)
        phrase_index_file = output_dir / "phrase_index.json"
        with open(phrase_index_file, 'w', encoding='utf-8') as f:
            phrase_dict = {
                k: dict(v) for k, v in self.phrase_index.items()
            }
            json.dump(phrase_dict, f)
        print(f"Saved phrase index to {phrase_index_file}")

        # Save autocomplete index
        autocomplete_index = self.build_autocomplete_index()
        autocomplete_file = output_dir / "ngram_autocomplete.json"
        with open(autocomplete_file, 'w', encoding='utf-8') as f:
            json.dump(autocomplete_index, f)
        print(f"Saved autocomplete index to {autocomplete_file}")


def main():
    parser = argparse.ArgumentParser(description='Build n-gram index for multi-word autocomplete')
    parser.add_argument('--workers', type=int, default=None,
                        help='Number of parallel workers (default: auto)')
    parser.add_argument('--min-freq', type=int, default=5,
                        help='Minimum frequency threshold (default: 5)')
    parser.add_argument('--max-ngrams', type=int, default=50000,
                        help='Maximum n-grams to keep (default: 50000)')
    parser.add_argument('--sequential', action='store_true',
                        help='Use sequential processing instead of parallel')
    args = parser.parse_args()

    # Get paths
    script_dir = Path(__file__).resolve().parent
    backend_dir = script_dir.parent

    # Load config
    config_path = backend_dir / "config.json"
    with open(config_path, "r") as f:
        config = json.load(f)

    data_root = backend_dir / config["data_dir"]
    indexes_dir = backend_dir / config["indexes_dir"]

    # Find pmc_json folder
    target_folder = None
    for root, dirs, files in os.walk(data_root):
        if config["json_data"] in dirs:
            target_folder = Path(root) / config["json_data"]
            break

    if target_folder is None:
        print(f"Error: Could not find {config['json_data']} folder under {data_root}")
        print("\nNote: If you don't have the dataset, this step can be skipped.")
        print("Multi-word autocomplete will work once you process documents.")
        return

    print("=" * 60)
    print("N-GRAM INDEX BUILDER (Optimized)")
    print("=" * 60)
    print(f"Data source: {target_folder}")
    print(f"Output directory: {indexes_dir}")
    print(f"Workers: {args.workers or 'auto'}")
    print(f"Min frequency: {args.min_freq}")
    print()

    # Build n-gram index
    builder = NgramBuilder(min_freq=args.min_freq, max_ngrams=args.max_ngrams)

    if args.sequential:
        builder.process_documents(target_folder)
    else:
        builder.process_documents_parallel(target_folder, num_workers=args.workers)

    builder.filter_and_rank()
    builder.save(indexes_dir)

    print("\n" + "=" * 60)
    print("N-GRAM INDEX BUILD COMPLETE!")
    print("=" * 60)
    print("\nTop 10 bigrams:")
    for (w1, w2), count in builder.bigrams.most_common(10):
        print(f"  '{w1} {w2}': {count}")

    print("\nTop 10 trigrams:")
    for (w1, w2, w3), count in builder.trigrams.most_common(10):
        print(f"  '{w1} {w2} {w3}': {count}")


if __name__ == "__main__":
    main()
