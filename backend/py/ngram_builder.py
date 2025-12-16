"""
N-gram Index Builder for Multi-Word Autocomplete

Analyzes the document corpus to find common 2-word and 3-word phrases.
Builds a frequency index for fast multi-word autocomplete suggestions.

Usage:
    python ngram_builder.py

Output:
    indexes/ngrams.json - Phrase frequency index
    indexes/ngram_trie.json - Optimized trie structure for autocomplete
"""

import os
import json
import re
from pathlib import Path
from collections import defaultdict, Counter
from nltk.corpus import stopwords
from nltk.tokenize import word_tokenize
from nltk.stem import WordNetLemmatizer
from tqdm import tqdm


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
        self.bigrams = Counter()  # 2-word phrases
        self.trigrams = Counter()  # 3-word phrases

        # Phrase index: "covid" -> {"vaccine": 1500, "pandemic": 1200}
        self.phrase_index = defaultdict(lambda: defaultdict(int))

        self.stop_words = set(stopwords.words('english'))
        self.lemmatizer = WordNetLemmatizer()

    def clean_and_tokenize(self, text):
        """Clean text and return tokens."""
        # Remove URLs, special chars
        text = re.sub(r'http[s]?://\S+|[^a-zA-Z0-9\s]+', ' ', text)
        text = re.sub(r'\s+', ' ', text).strip()

        # Tokenize
        tokens = word_tokenize(text.lower())

        # Filter: keep only alphabetic, non-stopword tokens
        cleaned = [
            self.lemmatizer.lemmatize(word)
            for word in tokens
            if word.isalpha() and word not in self.stop_words and len(word) > 2
        ]

        return cleaned

    def extract_ngrams(self, tokens):
        """Extract bigrams and trigrams from token list."""
        # Bigrams (2-word phrases)
        for i in range(len(tokens) - 1):
            bigram = (tokens[i], tokens[i+1])
            self.bigrams[bigram] += 1

            # Build phrase index: first_word -> {second_word: count}
            self.phrase_index[tokens[i]][tokens[i+1]] += 1

        # Trigrams (3-word phrases)
        for i in range(len(tokens) - 2):
            trigram = (tokens[i], tokens[i+1], tokens[i+2])
            self.trigrams[trigram] += 1

            # Build phrase index for 3-word: "first_word second_word" -> {third_word: count}
            prefix = f"{tokens[i]} {tokens[i+1]}"
            self.phrase_index[prefix][tokens[i+2]] += 1

    def process_documents(self, json_dir):
        """Process all JSON documents to build n-gram index."""
        json_files = list(Path(json_dir).glob("*.json"))
        print(f"Processing {len(json_files)} documents...")

        for json_file in tqdm(json_files):
            try:
                with open(json_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)

                # Extract text from abstract and body
                text_parts = []
                for key in ["abstract", "body_text"]:
                    if key in data:
                        for entry in data[key]:
                            text_parts.append(entry.get("text", ""))

                full_text = "\n".join(text_parts)

                # Tokenize and extract n-grams
                tokens = self.clean_and_tokenize(full_text)
                self.extract_ngrams(tokens)

            except Exception as e:
                continue

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

    def build_autocomplete_index(self):
        """Build optimized index for autocomplete: prefix -> suggestions."""
        autocomplete_index = {}

        # For each phrase, add to all possible prefixes
        # Example: "covid vaccine" adds to "c", "co", "cov", "covi", "covid"

        print("\nBuilding autocomplete index...")

        all_phrases = []

        # Add bigrams
        for (word1, word2), count in self.bigrams.items():
            phrase = f"{word1} {word2}"
            all_phrases.append((phrase, count))

        # Add trigrams
        for (word1, word2, word3), count in self.trigrams.items():
            phrase = f"{word1} {word2} {word3}"
            all_phrases.append((phrase, count))

        # Group by prefix
        for phrase, count in tqdm(all_phrases):
            words = phrase.split()

            # Add to single-word prefix (for first word)
            for i in range(1, len(words[0]) + 1):
                prefix = words[0][:i]
                if prefix not in autocomplete_index:
                    autocomplete_index[prefix] = []
                autocomplete_index[prefix].append({"phrase": phrase, "count": count})

            # Add to multi-word prefix (for second+ words)
            if len(words) > 1:
                for i in range(1, len(words[1]) + 1):
                    prefix = f"{words[0]} {words[1][:i]}"
                    if prefix not in autocomplete_index:
                        autocomplete_index[prefix] = []
                    autocomplete_index[prefix].append({"phrase": phrase, "count": count})

            # Add to 3-word prefix
            if len(words) > 2:
                for i in range(1, len(words[2]) + 1):
                    prefix = f"{words[0]} {words[1]} {words[2][:i]}"
                    if prefix not in autocomplete_index:
                        autocomplete_index[prefix] = []
                    autocomplete_index[prefix].append({"phrase": phrase, "count": count})

        # Sort each prefix by count and keep top 10
        for prefix in autocomplete_index:
            autocomplete_index[prefix] = sorted(
                autocomplete_index[prefix],
                key=lambda x: x["count"],
                reverse=True
            )[:10]

        print(f"Built index for {len(autocomplete_index)} prefixes")
        return autocomplete_index

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
            json.dump(bigrams_dict, f, indent=2)
        print(f"Saved bigrams to {bigrams_file}")

        # Save trigrams
        trigrams_file = output_dir / "trigrams.json"
        with open(trigrams_file, 'w', encoding='utf-8') as f:
            trigrams_dict = {
                f"{w1} {w2} {w3}": count
                for (w1, w2, w3), count in self.trigrams.most_common()
            }
            json.dump(trigrams_dict, f, indent=2)
        print(f"Saved trigrams to {trigrams_file}")

        # Save phrase index (for API)
        phrase_index_file = output_dir / "phrase_index.json"
        with open(phrase_index_file, 'w', encoding='utf-8') as f:
            # Convert defaultdict to regular dict
            phrase_dict = {
                k: dict(v) for k, v in self.phrase_index.items()
            }
            json.dump(phrase_dict, f, indent=2)
        print(f"Saved phrase index to {phrase_index_file}")

        # Save autocomplete index
        autocomplete_index = self.build_autocomplete_index()
        autocomplete_file = output_dir / "ngram_autocomplete.json"
        with open(autocomplete_file, 'w', encoding='utf-8') as f:
            json.dump(autocomplete_index, f, indent=2)
        print(f"Saved autocomplete index to {autocomplete_file}")


def extract_text_from_json(file_path):
    """Extract text from CORD-19 JSON file."""
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        text_parts = []
        for key in ["abstract", "body_text"]:
            if key in data:
                for entry in data[key]:
                    text_parts.append(entry.get("text", ""))
        return "\n".join(text_parts)

    except Exception:
        return ""


def main():
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
    print("N-GRAM INDEX BUILDER")
    print("=" * 60)
    print(f"Data source: {target_folder}")
    print(f"Output directory: {indexes_dir}")
    print()

    # Build n-gram index
    builder = NgramBuilder(min_freq=5, max_ngrams=50000)
    builder.process_documents(target_folder)
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
