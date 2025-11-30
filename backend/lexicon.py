import os
import json
import re
import nltk
from nltk.corpus import stopwords
from nltk.tokenize import word_tokenize
from nltk.stem import WordNetLemmatizer
from tqdm import tqdm  # progress bar


class Lexicon:
    """Builds lexicon from JSON dataset and saves as JSON."""

    def __init__(self, number_lemma_id=9999):
        self.wordID = {}
        self.lemmaID = {}
        self.wordToLemmaID = {}
        self.word_counter = 0
        self.lemma_counter = 0
        self.number_lemma_id = number_lemma_id

        self.stop_words = set(stopwords.words('english'))
        self.lemmatizer = WordNetLemmatizer()

    def clean_and_tokenize(self, text):
        """Cleans and tokenizes text."""
        text = re.sub(r'http[s]?://\S+|[^a-zA-Z0-9\s]+|\s+', ' ', text).strip()
        tokens = word_tokenize(text.lower())

        cleaned_tokens = [
            (word, self.lemmatizer.lemmatize(word))
            for word in tokens
            if word not in self.stop_words and word.isalpha()
        ]
        return cleaned_tokens

    def process_tokens(self, tokens):
        """Generates Word IDs and Lemma IDs."""
        for word, lemma in tokens:
            if not word:
                continue

            word = word.lower()
            lemma = lemma.lower()

            # Special case: numbers
            if word.isdigit():
                if word not in self.wordID:
                    self.wordID[word] = self.word_counter
                    self.word_counter += 1
                lemma = str(self.number_lemma_id)

            else:
                if word not in self.wordID:
                    self.wordID[word] = self.word_counter
                    self.word_counter += 1
                if lemma not in self.lemmaID:
                    self.lemmaID[lemma] = self.lemma_counter
                    self.lemma_counter += 1

            self.wordToLemmaID[self.wordID[word]] = self.lemmaID.get(lemma, self.number_lemma_id)

    def save_lexicon_json(self, file_path):
        lexicon_json = {
            "wordID": self.wordID,
            "lemmaID": self.lemmaID,
            "wordToLemmaID": self.wordToLemmaID
        }

        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(lexicon_json, f, indent=4)

        return len(self.wordID)


def extract_text_from_json(file_path):
    """Extracts text fields (abstract + body) from a CORD-19 JSON file."""
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        text_parts = []

        # Extract abstract
        if "abstract" in data:
            for entry in data["abstract"]:
                text_parts.append(entry.get("text", ""))

        # Extract body_text
        if "body_text" in data:
            for entry in data["body_text"]:
                text_parts.append(entry.get("text", ""))

        return "\n".join(text_parts)

    except Exception:
        return ""


def main():
    data_dir = os.path.join("..","dataset","2020-07-04","document_parses","pmc_json")
    source_dir = os.path.dirname(os.path.abspath(__file__))
    DATA_DIR = os.path.join(source_dir, data_dir)

    lexicon = Lexicon()

    print("Processing JSON files...")

    # Loop through 50,000 JSON files
    for filename in tqdm(os.listdir(DATA_DIR)):
        if filename.endswith(".json"):
            file_path = os.path.join(DATA_DIR, filename)

            content = extract_text_from_json(file_path)
            tokens = lexicon.clean_and_tokenize(content)
            lexicon.process_tokens(tokens)

    # Save final lexicon
    total_words = lexicon.save_lexicon_json("lexicon.json")

    print(f"\nLexicon created with {total_words} unique words.")
    print("Saved to lexicon.json")


if __name__ == "__main__":
    main()
