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
    try:
        ebook = epub.read_epub(epub_path)
    except Exception as e:
        print(f"\033[31mError reading EPUB file '{epub_path}': {e}\033[0m")
        return []

    chapters = []

    for doc_item in ebook.get_items_of_type(ITEM_DOCUMENT):
        try:
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
        except Exception as e:
            print(f"\033[31mError processing EPUB document item: {e}\033[0m")
            continue

    return chapters

def split_text_into_chunks(text, max_length):
    """
    Split the given text into chunks not exceeding max_length characters, trying to preserve sentence boundaries.

    :param text: The text to be split into chunks.
    :param max_length: Maximum number of characters per chunk.

    :return: A list of text chunks, each not exceeding max_length characters.
    """
    try:
        sentences = re.split(r'(?<=[.!?])\s+', text.strip())
    except Exception as e:
        print(f"\033[31mError splitting text into sentences: {e}\033[0m")
        return [text]

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
    try:
        # Replace various types of quotes with standard ASCII quotes
        text = text.replace("«", '"').replace("»", '"')
        text = text.replace("„", '"').replace("“", '"')
        text = text.replace("‘", "'").replace("’", "'")

        # Remove unsupported characters based on language
        if language.lower() == "de":
            text = re.sub(r"[^a-zA-Z0-9äöüÄÖÜß.,:!?\"()\n\- /]", "", text)
        elif language.lower() == "en":
            text = re.sub(r"[^a-zA-Z0-9.,:!?\"'()\n\- /]", "", text)

        # Spaces after punctuation
        text = re.sub(r'([.!?])(?=\S)', r'\1 ', text)
        text = re.sub(r'([,;:])(?=\S)', r'\1 ', text)

        # Spaces before opening parenthesis
        text = re.sub(r'(?<!\s)\(', ' (', text)

        # Spaces around dash
        text = re.sub(r'(?<!\s)-', ' -', text)
        text = re.sub(r'-(?!\s)', '- ', text)

        return text
    except Exception as e:
        print(f"\033[31mError cleaning text: {e}\033[0m")
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

    if not model_folder or not output_dir:
        print(f"\033[31mError: MODEL_PATH or OUTPUT_PATH environment variables are not set.\033[0m")
        return

    try:
        os.makedirs(output_dir, exist_ok=True)
    except Exception as e:
        print(f"\033[31mError creating output directory '{output_dir}': {e}\033[0m")
        return

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
                    try:
                        tts_engine = pvorca.create(access_key=os.getenv("ACCESS_KEY"), model_path=model_path)
                        tts_engine.synthesize_to_file(text=chunk, output_path=wav_path)
                        tts_engine.delete()
                        action = "Saved"
                        # Green text
                        color = "\033[32m"
                    except Exception as e:
                        print(f"\033[31mError synthesizing chunk {local_chunk_counter} of chapter {chapter_index}: {e}\033[0m")
                        continue
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
                try:
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
                except Exception as e:
                    print(f"\033[31mError synthesizing chapter end marker for chapter {chapter_index}: {e}\033[0m")
                    continue
            else:
                action = "Skipped existing"
                # Bright blue text
                color = "\033[94m"

            print(f"{color}        {action} chapter {chapter_index} end marker saved as chunk {global_chunk_counter}")
            chapter_end_chunk_indices.append(global_chunk_counter)
            global_chunk_counter += 1

        # Combine all WAV chunks into a single MP3 audiobook
        audiobook = AudioSegment.empty()
        for i in range(1, global_chunk_counter):
            wav_path = os.path.join(output_dir, f"{base_name}_chunk_{i}.wav")
            try:
                chunk_audio = AudioSegment.from_wav(wav_path)
            except Exception as e:
                print(f"\033[31mError loading WAV chunk {i}: {e}\033[0m")
                continue

            audiobook += chunk_audio

            # Add 2 seconds of silence after end-of-chapter markers
            if i in chapter_end_chunk_indices:
                audiobook += AudioSegment.silent(duration=2000)

        mp3_output_path = os.path.join(output_dir, base_name + ".mp3")
        try:
            audiobook.export(mp3_output_path, format="mp3")
            # Cyan text
            print(f"\033[36mAudiobook assembled and saved to: {mp3_output_path}\033[0m")
        except Exception as e:
            print(f"\033[31mError exporting MP3 file '{mp3_output_path}': {e}\033[0m")

    finally:
        # Gray text
        print(f"\033[37mCleaning up temporary WAV files...\033[0m")
        for i in range(1, global_chunk_counter):
            wav_to_remove = os.path.join(output_dir, f"{base_name}_chunk_{i}.wav")
            try:
                if os.path.exists(wav_to_remove):
                    os.remove(wav_to_remove)
            except Exception as e:
                print(f"\033[31mError deleting temporary file '{wav_to_remove}': {e}\033[0m")

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

    # Check if EPUB file exists
    if not os.path.isfile(args.epub_path):
        print(f"\033[31mError: EPUB file '{args.epub_path}' does not exist.\033[0m")
        return

    # Check required environment variables
    missing_env_vars = []
    for var in ["ACCESS_KEY", "MODEL_PATH", "OUTPUT_PATH"]:
        if not os.getenv(var):
            missing_env_vars.append(var)
    if missing_env_vars:
        print(f"\033[31mError: Missing environment variables: {', '.join(missing_env_vars)}\033[0m")
        return

    base_name = os.path.splitext(os.path.basename(args.epub_path))[0]

    chapters = epub_to_chapters(args.epub_path)

    if not chapters:
        print(f"\033[31mNo chapters found or error reading EPUB. Aborting.\033[0m")
        return

    chapters_to_mp3(args.language, args.gender, chapters, base_name)

# Run main() if script is called directly
if __name__ == "__main__":
    main()