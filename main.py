import os  # For environment variables and file path operations
from dotenv import load_dotenv  # Load environment variables from a .env file
import argparse  # For parsing command-line arguments

import pvorca  # Picovoice Orca TTS engine for speech synthesis
from pydub import AudioSegment  # For audio processing and combining WAV files into MP3

from ebooklib import epub, ITEM_DOCUMENT  # To read EPUB files and extract document parts
from bs4 import BeautifulSoup  # To parse and clean up HTML content from EPUB
import re  # For regular expressions (text splitting & cleaning)

# Load environment variables from .env file
load_dotenv()

# Extract plain text from an EPUB file
def epub_to_text(epub_path):
    book = epub.read_epub(epub_path)
    text_parts = []

    # Iterate through all HTML-like documents in the EPUB
    for item in book.get_items_of_type(ITEM_DOCUMENT):
        soup = BeautifulSoup(item.get_content(), 'html.parser')
        text = soup.get_text()
        text_parts.append(text)

    return '\n'.join(text_parts)

# Split text into chunks of max `max_length` characters, preserving sentence boundaries
def split_text(text, max_length):
    sentences = re.split(r'(?<=[.!?])\s+', text.strip())
    chunks = []
    current_chunk = ""

    for sentence in sentences:
        sentence = sentence.strip()
        if not sentence:
            continue

        # If the sentence is longer than max_length, split it at the word level
        if len(sentence) > max_length:
            words = sentence.split()
            for word in words:
                if len(current_chunk) + len(word) + 1 <= max_length:
                    current_chunk += (" " if current_chunk else "") + word
                else:
                    chunks.append(current_chunk)
                    current_chunk = word
            if current_chunk:
                chunks.append(current_chunk)
        else:
            chunks.append(sentence)

    return chunks

# Clean up the text by replacing special quotes and removing unsupported characters
def clean_text(text, language):
    text = text.replace("«", '"').replace("»", '"') \
        .replace("„", '"').replace("“", '"') \
        .replace("‘", "'").replace("’", "'")

    if language.lower() == "de":
        text = re.sub(r"[^a-zA-Z0-9äöüÄÖÜß.,:!?\"()\n\- ]", "", text)
    elif language.lower() == "en":
        text = re.sub(r"[^a-zA-Z0-9.,:!?\"'()\n\- ]", "", text)

    # Ensure there's a space after sentence-ending punctuation
    text = re.sub(r'([.!?])(?=\w)', r'\1 ', text)
    # Ensure space before opening parenthesis
    text = re.sub(r'(?<![\s(])\(', ' (', text)

    return text

# Convert the cleaned text into audio files using Orca, then combine to one MP3 file
def text_to_wav(language, gender, text, mp3_filename):
    model_folder = os.getenv("MODEL_PATH") # Path to Orca model files
    output_dir = os.getenv("OUTPUT_PATH") # Output directory for audio files
    os.makedirs(output_dir, exist_ok=True)

    # Select appropriate model based on language and gender
    if language.lower() == "de":
        if gender.lower() == "male":
            model_path = os.path.join(model_folder, "orca_params_de_male.pv")
        else:
            model_path = os.path.join(model_folder, "orca_params_de_female.pv")
    else:
        if gender.lower() == "male":
            model_path = os.path.join(model_folder, "orca_params_en_male.pv")
        else:
            model_path = os.path.join(model_folder, "orca_params_en_female.pv")

    cleaned_text = clean_text(text, language)
    chunks = split_text(cleaned_text, max_length=500)

    # Convert each chunk to a WAV file using Orca
    for i, chunk in enumerate(chunks):
        orca = pvorca.create(access_key=os.getenv("ACCESS_KEY"), model_path=model_path)
        output_file = os.path.join(output_dir, f"output_chunk_{i}.wav")
        orca.synthesize_to_file(text=chunk, output_path=output_file)
        orca.delete()
        print(f"Saved chunk {i} from {len(chunks)}")

    # Combine all WAV files into a single MP3 file
    combined = AudioSegment.empty()
    for i in range(len(chunks)):
        wav_path = os.path.join(output_dir, f"output_chunk_{i}.wav")
        chunk_audio = AudioSegment.from_wav(wav_path)
        combined += chunk_audio

    mp3_output_path = os.path.join(output_dir, mp3_filename)
    combined.export(mp3_output_path, format="mp3")
    print(f"Exported combined audio to {mp3_output_path}")

    # Optional: delete the intermediate WAV files
    for i in range(len(chunks)):
        os.remove(os.path.join(output_dir, f"output_chunk_{i}.wav"))

# Command-line entry point
def main():
    parser = argparse.ArgumentParser(description="Convert EPUB to TTS audio")
    parser.add_argument("epub_path", help="Path to the EPUB file")
    parser.add_argument("language", choices=["de", "en"], help="Language code (de or en)")
    parser.add_argument("gender", choices=["male", "female"], help="Gender code (male or female)")

    args = parser.parse_args()

    # Extract base filename for the output file
    base_name = os.path.splitext(os.path.basename(args.epub_path))[0]
    mp3_filename = base_name + ".mp3"

    text = epub_to_text(args.epub_path)
    text_to_wav(args.language, args.gender, text, mp3_filename)

# Run main() if script is called directly
if __name__ == "__main__":
    main()