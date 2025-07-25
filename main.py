import os   # For environment variables and file path operations
from dotenv import load_dotenv   # To load environment variables from a .env file
import argparse   # For parsing command-line arguments

import pvorca   # Picovoice Orca TTS engine for speech synthesis
from pydub import AudioSegment   # For audio processing and combining WAV files into MP3

from ebooklib import epub, ITEM_DOCUMENT   # To read EPUB files and extract document parts
from bs4.element import NavigableString  # Represents text nodes within the HTML parse tree
from bs4 import BeautifulSoup   # To parse and clean up HTML content from EPUB
from bs4 import Tag   # For handling HTML tags in BeautifulSoup
import re   # Regular expressions for text processing

load_dotenv()   # Load environment variables from .env file

def epub_to_chapters(epub_path):
    """
    Extract chapters from an EPUB by splitting text between <h1> and <h2> headings.

    :param epub_path: Path to the EPUB file.

    :return: List of chapters, each as a string "Title\nContent".
    """
    ebook = epub.read_epub(epub_path)
    chapters = []

    for doc_item in ebook.get_items_of_type(ITEM_DOCUMENT):
        soup = BeautifulSoup(doc_item.get_content(), 'html.parser')
        body = soup.body
        if not body:
            continue

        current_title = None
        current_content = []

        for el in body.descendants:
            if isinstance(el, Tag) and el.name in ['h1', 'h2']:
                # Start new chapter, save previous if exists
                if current_title or current_content:
                    full_text = f"{current_title}\n{''.join(current_content).strip()}"
                    # Filter out None-Strings and empty rows
                    full_text = '\n'.join([line for line in full_text.splitlines() if line.strip() and line.strip().lower() != 'none'])
                    chapters.append(full_text)
                    current_content = []

                current_title = el.get_text(strip=True)

            elif isinstance(el, NavigableString):
                # Collect chapter content, skip headings
                if el.parent and el.parent.name not in ['h1', 'h2']:
                    text = el.strip()
                    if text and text.lower() != 'none':
                        current_content.append(text + "\n")

        # Save last chapter
        if current_title or current_content:
            full_text = f"{current_title}\n{''.join(current_content).strip()}"
            full_text = '\n'.join([line for line in full_text.splitlines() if line.strip() and line.strip().lower() != 'none'])
            chapters.append(full_text)

    return chapters

def split_text_into_chunks(text, max_length):
    """
    Split the given text into chunks not exceeding max_length characters, trying to preserve sentence boundaries.

    :param text: The text to be split into chunks.
    :param max_length: Maximum number of characters per chunk.

    :return: A list of text chunks, each not exceeding max_length characters.
    """
    sentences = re.split(r'(?<=[.!?])\s+', text.strip())
    text_chunks = []
    current_chunk = ""

    for sentence in sentences:
        sentence = sentence.strip()
        if not sentence:
            continue

        # If the sentence is longer than max_length, split it at the word level
        if len(sentence) > max_length:
            words = sentence.split()
            for word in words:
                # Append words to the current chunk until exceeding max_length
                if len(current_chunk) + len(word) + 1 <= max_length:
                    current_chunk += (" " if current_chunk else "") + word
                else:
                    text_chunks.append(current_chunk)
                    current_chunk = word
            if current_chunk:
                text_chunks.append(current_chunk)
        else:
            text_chunks.append(sentence)

    return text_chunks

def clean_text(text, language):
    """
    Clean up the text by replacing special quotes and removing unsupported characters.

    :param text: The text to clean.
    :param language: Language code ('de' or 'en') to determine allowed characters.

    :return: The cleaned text.
    """
    # Replace various types of quotes with standard ASCII quotes
    text = text.replace("«", '"').replace("»", '"')
    text = text.replace("„", '"').replace("“", '"')
    text = text.replace("‘", "'").replace("’", "'")

    # Remove unsupported characters based on language
    if language.lower() == "de":
        text = re.sub(r"[^a-zA-Z0-9äöüÄÖÜß.,:!?\"()\n\- ]", "", text)
    elif language.lower() == "en":
        text = re.sub(r"[^a-zA-Z0-9.,:!?\"'()\n\- ]", "", text)

    # Ensure there's a space after sentence-ending punctuation if missing
    text = re.sub(r'([.!?])(?=\w)', r'\1 ', text)
    # Ensure there's a space before opening parentheses if missing
    text = re.sub(r'(?<![\s(])\(', ' (', text)

    return text

def chapters_to_mp3(language, gender, chapters, base_name):
    """
    Convert chapters into speech and combine them into a single MP3 file.

    :param language: Language code ('de' or 'en') for the text-to-speech model.
    :param gender: Voice gender ('male' or 'female') for the text-to-speech model.
    :param chapters: List of chapters, each containing text to be converted to speech.
    :param base_name: Base filename for output files (no extension).
    """
    model_folder = os.getenv("MODEL_PATH")   # Path to Orca model files
    output_dir = os.getenv("OUTPUT_PATH")   # Output directory for audio files
    os.makedirs(output_dir, exist_ok=True)

    # Select appropriate Orca model file based on language and gender
    model_path = os.path.join(model_folder, f'orca_params_{language.lower()}_{gender.lower()}.pv')

    global_chunk_counter = 1
    chapter_end_chunk_indices = []

    try:
        for chapter_index, chapter in enumerate(chapters, start=1):
            cleaned_chapter = clean_text(chapter, language)
            text_chunks = split_text_into_chunks(cleaned_chapter, max_length=500)
            local_chunk_counter = 1

            # Magenta text
            print(f"\033[35m    Processing chapter {chapter_index}/{len(chapters)} with {len(text_chunks)} chunks\033[0m")

            # Convert each text chunk to a WAV file using Orca TTS
            for chunk in text_chunks:
                wav_path = os.path.join(output_dir, f"{base_name}_chunk_{global_chunk_counter}.wav")

                if not os.path.exists(wav_path):
                    tts_engine = pvorca.create(access_key=os.getenv("ACCESS_KEY"), model_path=model_path)
                    tts_engine.synthesize_to_file(text=chunk, output_path=wav_path)
                    tts_engine.delete()
                    action = "Saved"
                    # Green text
                    color = "\033[32m"
                else:
                    action = "Skipped existing"
                    # Blue text
                    color = "\033[34m"

                print(f"{color}            {action} chunk {local_chunk_counter} of {len(text_chunks)} for chapter {chapter_index}/{len(chapters)} as chunk {global_chunk_counter}\033[0m")
                local_chunk_counter += 1
                global_chunk_counter += 1

            # Add an audio marker for end of chapter
            wav_path = os.path.join(output_dir, f"{base_name}_chunk_{global_chunk_counter}.wav")

            if not os.path.exists(wav_path):
                # Use the opposite voice gender for chapter end markers to make them acoustically distinct
                if gender.lower() == "male":
                    model_path_chapter_break = os.path.join(model_folder, f'orca_params_{language.lower()}_female.pv')
                else:
                    model_path_chapter_break = os.path.join(model_folder, f'orca_params_{language.lower()}_male.pv')

                tts_engine = pvorca.create(access_key=os.getenv("ACCESS_KEY"), model_path=model_path_chapter_break)
                if language.lower() == "de":
                    tts_engine.synthesize_to_file(text=f"Ende des Kapitels {chapter_index}", output_path=wav_path)
                elif language.lower() == "en":
                    tts_engine.synthesize_to_file(text=f"End of chapter {chapter_index}", output_path=wav_path)
                tts_engine.delete()
                action = "Saved"
                # Bright green text
                color = "\033[92m"
            else:
                action = "Skipped existing"
                # Bright blue text
                color = "\033[94m"

            print(f"{color}        {action} chapter {chapter_index} end marker saved as chunk {global_chunk_counter}")
            global_chunk_counter += 1

            chapter_end_chunk_indices.append(global_chunk_counter)

        # Combine all WAV chunks into a single MP3 audiobook
        audiobook = AudioSegment.empty()
        for i in range(1, global_chunk_counter):
            wav_path = os.path.join(output_dir, f"{base_name}_chunk_{i}.wav")
            chunk_audio = AudioSegment.from_wav(wav_path)
            audiobook += chunk_audio

            # Add 2 seconds of silence after end-of-chapter markers
            if i in chapter_end_chunk_indices:
                audiobook += AudioSegment.silent(duration=2000)

        mp3_output_path = os.path.join(output_dir, base_name + ".mp3")
        audiobook.export(mp3_output_path, format="mp3")
        # Cyan text
        print(f"\033[36mAudiobook assembled and saved to: {mp3_output_path}\033[0m")

    finally:
        # Gray text
        print(f"\033[37mCleaning up temporary WAV files...\033[0m")
        for i in range(1, global_chunk_counter):
            wav_to_remove = os.path.join(output_dir, f"{base_name}_chunk_{i}.wav")
            if os.path.exists(wav_to_remove):
                os.remove(wav_to_remove)

# Command-line entry point
def main():
    """
    Command-line entry point: parse arguments and convert EPUB to audio.
    """
    parser = argparse.ArgumentParser(description="Convert EPUB to TTS audio")
    parser.add_argument("epub_path", help="Path to the EPUB file")
    parser.add_argument("language", choices=["de", "en"], help="Language code (de or en)")
    parser.add_argument("gender", choices=["male", "female"], help="Gender code (male or female)")

    args = parser.parse_args()
    base_name = os.path.splitext(os.path.basename(args.epub_path))[0]

    chapters = epub_to_chapters(args.epub_path)
    chapters_to_mp3(args.language, args.gender, chapters, base_name)

# Run main() if script is called directly
if __name__ == "__main__":
    main()