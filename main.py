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
def split_text(text, max_length=300):
    sentences = re.split(r'(?<=[.!?]) +', text) # Split on sentence endings
    chunks = []
    current_chunk = ""

    for sentence in sentences:
        if len(current_chunk) + len(sentence) + 1 <= max_length:
            # Add sentence to current chunk if it fits within the max length
            current_chunk += " " + sentence if current_chunk else sentence
        else:
            # If current chunk exceeds max length, save it and start a new chunk
            chunks.append(current_chunk.strip())
            current_chunk = sentence
    if current_chunk:
        chunks.append(current_chunk.strip())

    return chunks

# Clean up the text by replacing special quotes and removing unsupported characters
def clean_text(text):
    text = text.replace("«", '"').replace("»", '"')
    text = re.sub(r"[^a-zA-Z0-9äöüÄÖÜß.,:!?\"' \n\r\t-]", "", text)
    return text

# Convert the cleaned text into audio files using Orca, then combine to one MP3 file
def text_to_wav(language, text):
    model_folder = os.getenv("MODEL_PATH") # Path to Orca model files
    output_dir = os.getenv("OUTPUT_PATH") # Output directory for audio files
    os.makedirs(output_dir, exist_ok=True)

    # Select appropriate model based on language
    if language == "de":
        model_path = os.path.join(model_folder, "orca_params_de_male.pv")
    else:
        model_path = os.path.join(model_folder, "orca_params_en_male.pv")

    cleaned_text = clean_text(text)
    chunks = split_text(cleaned_text, max_length=300)

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

    mp3_output_path = os.path.join(output_dir, "combined_output.mp3")
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

    args = parser.parse_args()

    text = epub_to_text(args.epub_path)
    text_to_wav(args.language, text)

# Run main() if script is called directly
if __name__ == "__main__":
    main()