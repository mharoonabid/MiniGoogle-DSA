import os
import json
import re
from pathlib import Path
from nltk.corpus import stopwords
from nltk.tokenize import word_tokenize
from nltk.stem import WordNetLemmatizer
from tqdm import tqdm


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
        text = re.sub(r'http[s]?://\S+|[^a-zA-Z0-9\s]+|\s+', ' ', text).strip()
        tokens = word_tokenize(text.lower())

        cleaned_tokens = [
            (word, self.lemmatizer.lemmatize(word))
            for word in tokens
            if word not in self.stop_words and word.isalpha()
        ]
        return cleaned_tokens

    def process_tokens(self, tokens):
        for word, lemma in tokens:
            if not word:
                continue

            word = word.lower()
            lemma = lemma.lower()

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
    # Determine backend directory
    source_dir = Path(__file__).resolve().parent.parent  # backend/

    # Load centralized config
    config_path = source_dir / "config.json"
    with open(config_path, "r") as f:
        config = json.load(f)

    data_root = source_dir / config["data_dir"]
    indexes_dir = source_dir / config["indexes_dir"]
    lexicon_file = config["lexicon_file"]
    indexes_dir.mkdir(parents=True, exist_ok=True)  # ensure folder exists

    # Traverse nested structure to find pmc-json folder
    target_folder = None
    for root, dirs, files in os.walk(data_root):
        if config["json_data"] in dirs:
            target_folder = Path(root) / config["json_data"]
            break

    if target_folder is None:
        raise FileNotFoundError(f"Could not find {config['json_data']} folder under dataset.")

    lexicon = Lexicon()

    print(f"Processing JSON files in {target_folder} ...")

    for filename in tqdm(os.listdir(target_folder)):
        if filename.endswith(".json"):
            file_path = target_folder / filename
            content = extract_text_from_json(file_path)
            tokens = lexicon.clean_and_tokenize(content)
            lexicon.process_tokens(tokens)

    # Save lexicon
    lexicon_file = indexes_dir / lexicon_file
    total_words = lexicon.save_lexicon_json(lexicon_file)

    print(f"\nLexicon created with {total_words} unique words.")
    print(f"Saved to {lexicon_file}")


if __name__ == "__main__":
    main()
