import math
import os   # For environment variables and file path operations
import argparse   # For parsing command-line arguments

import asyncio   # For running async edge-tts synthesis
import aiohttp   # For handling edge-tts connection errors
import edge_tts   # Edge TTS engine for speech synthesis
from pydub import AudioSegment   # For audio processing and combining chunk MP3 files into a single MP3

from ebooklib import epub, ITEM_DOCUMENT   # To read EPUB files and extract document parts
from bs4.element import NavigableString  # Represents text nodes within the HTML parse tree
from bs4 import BeautifulSoup   # To parse and clean up HTML content from EPUB
from bs4 import Tag   # For handling HTML tags in BeautifulSoup
import re   # Regular expressions for text processing

async def synthesize_chunk(text, output_path, voice):
    """
    Synthesize a single text chunk to an MP3 file using edge-tts.

    :param text: The text to synthesize.
    :param output_path: File path where the MP3 will be saved.
    :param voice: Edge-TTS voice name.
    """
    communicate = edge_tts.Communicate(text, voice)
    await communicate.save(output_path)

async def synthesize_chunk_safe(text, output_path, voice, max_wait=60):
    """
    Synthesize a single text chunk with infinite retries and exponential backoff.

    :param text: The text to synthesize.
    :param output_path: File path where the MP3 will be saved.
    :param voice: Edge-TTS voice name.
    :param max_wait: Maximum wait time in seconds between retries (default: 60).
    """
    attempt = 0
    while True:
        try:
            await synthesize_chunk(text, output_path, voice)
            if attempt > 0:
                # Yellow text — recovered after retries
                print(f"\033[33m            Recovered after {attempt} retries: {text[:50]}...\033[0m")
            return
        except (edge_tts.exceptions.NoAudioReceived, aiohttp.client_exceptions.WSServerHandshakeError) as e:
            attempt += 1
            wait_time = min(2 ** (attempt - 1), max_wait)  # 1s, 2s, 4s, 8s, ... capped at max_wait
            # Red text for failure, but we keep going
            print(f"\033[31m            Attempt {attempt} failed (len={len(text)}): {e} — retrying in {wait_time}s...\033[0m")
            await asyncio.sleep(wait_time)
        except Exception as e:
            # For unexpected errors, also retry with max_wait delay
            attempt += 1
            print(f"\033[31m            Attempt {attempt} unexpected error (len={len(text)}): {e} — retrying in {max_wait}s...\033[0m")
            await asyncio.sleep(max_wait)

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

    # Merge chunks shorter than 50 characters into the previous chunk
    merged = []
    for chunk in text_chunks:
        if len(chunk.strip()) < 50 and merged:
            merged[-1] += " " + chunk
        else:
            merged.append(chunk)

    return merged

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

def chapters_to_mp3(language, voice, marker_voice, chapters, base_name):
    """
    Convert chapters into speech and combine them into a single MP3 file.

    :param language: Language code ('de' or 'en') for the text-to-speech model.
    :param voice: Edge-TTS voice name for main narration.
    :param marker_voice: Edge-TTS voice name for chapter end markers.
    :param chapters: List of chapters, each containing text to be converted to speech.
    :param base_name: Base filename for output files (no extension).
    """
    output_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "output")   # Output directory for audio files

    try:
        os.makedirs(output_dir, exist_ok=True)
    except Exception as e:
        print(f"\033[31mError creating output directory '{output_dir}': {e}\033[0m")
        return

    global_chunk_counter = 1
    chapter_end_chunk_indices = []

    async def process():
        nonlocal global_chunk_counter

        for chapter_index, chapter in enumerate(chapters, start=1):
            cleaned_chapter = clean_text(chapter, language)
            text_chunks = split_text_into_chunks(cleaned_chapter, max_length=500)
            local_chunk_counter = 1

            # Magenta text
            print(f"\033[35m    Processing chapter {chapter_index}/{len(chapters)} with {len(text_chunks)} chunks\033[0m")

            # Convert each text chunk to an MP3 file using edge-tts
            for chunk in text_chunks:
                chunk_mp3_path = os.path.join(output_dir, f"{base_name}_chunk_{global_chunk_counter}.mp3")

                # synthesize_chunk_safe retries indefinitely so that no chunks will be skipped
                await synthesize_chunk_safe(chunk, chunk_mp3_path, voice)
                await asyncio.sleep(0.5)

                # Green text
                print(f"\033[32m            Saved chunk {local_chunk_counter} of {len(text_chunks)} for chapter {chapter_index}/{len(chapters)} as chunk {global_chunk_counter}\033[0m")
                local_chunk_counter += 1
                global_chunk_counter += 1

            # Add an audio marker for end of chapter
            marker_mp3_path = os.path.join(output_dir, f"{base_name}_chunk_{global_chunk_counter}.mp3")

            if chapter_index < len(chapters):
                next_chapter = chapters[chapter_index]
                word_count = len(next_chapter.split())

                estimated_minutes = max(1, math.ceil(word_count / 200))

                if language.lower() == "de":
                    minute_word = "Minute" if estimated_minutes == 1 else "Minuten"
                    marker_text = (
                        f"Ende des Kapitels {chapter_index}. "
                        f"Das nächste Kapitel dauert etwa {estimated_minutes} {minute_word}."
                    )
                else:
                    minute_word = "minute" if estimated_minutes == 1 else "minutes"
                    marker_text = (
                        f"End of chapter {chapter_index}. "
                        f"The next chapter will take about {estimated_minutes} {minute_word}."
                    )
            else:
                if language.lower() == "de":
                    marker_text = f"Ende des Kapitels {chapter_index}"
                else:
                    marker_text = f"End of chapter {chapter_index}"

            # Markers also retry indefinitely
            await synthesize_chunk_safe(marker_text, marker_mp3_path, marker_voice)

            # Bright green text
            print(f"\033[92m        Saved chapter {chapter_index} end marker as chunk {global_chunk_counter}\033[0m")
            chapter_end_chunk_indices.append(global_chunk_counter)
            global_chunk_counter += 1

    try:
        asyncio.run(process())

        # Combine all MP3 chunks into a single MP3 audiobook
        audiobook = AudioSegment.empty()
        for i in range(1, global_chunk_counter):
            assembly_mp3_path = os.path.join(output_dir, f"{base_name}_chunk_{i}.mp3")
            try:
                chunk_audio = AudioSegment.from_mp3(assembly_mp3_path)
            except Exception as e:
                print(f"\033[31mError loading MP3 chunk {i}: {e}\033[0m")
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
        print(f"\033[37mCleaning up temporary MP3 files...\033[0m")
        for i in range(1, global_chunk_counter):
            mp3_to_remove = os.path.join(output_dir, f"{base_name}_chunk_{i}.mp3")
            try:
                if os.path.exists(mp3_to_remove):
                    os.remove(mp3_to_remove)
            except Exception as e:
                print(f"\033[31mError deleting temporary file '{mp3_to_remove}': {e}\033[0m")

# Command-line entry point
def main():
    """
    Command-line entry point: parse arguments and convert EPUB to audio.
    """
    parser = argparse.ArgumentParser(description="Convert EPUB to TTS audio")
    parser.add_argument("epub_path", help="Path to the EPUB file")
    parser.add_argument("language", choices=["de", "en"], help="Language code (de or en)")
    parser.add_argument("voice", help="Edge-TTS voice for main narration (see https://tts.travisvn.com for options)")
    parser.add_argument("marker_voice", help="Edge-TTS voice for markers (see https://tts.travisvn.com for options)")

    args = parser.parse_args()

    # Check if EPUB file exists
    if not os.path.isfile(args.epub_path):
        print(f"\033[31mError: EPUB file '{args.epub_path}' does not exist.\033[0m")
        return

    base_name = os.path.splitext(os.path.basename(args.epub_path))[0]

    chapters = epub_to_chapters(args.epub_path)

    if not chapters:
        print(f"\033[31mNo chapters found or error reading EPUB. Aborting.\033[0m")
        return

    # Add version of script as first chapter
    if args.language.lower() == "de":
        version_intro = f"Version zwei null null der Earwyrm Pipeline. Generiert mit der Stimme {args.voice} und der Markierungsstimme {args.marker_voice}."
    else:
        version_intro = f"Version two zero zero of the Earwyrm Pipeline. Generated with voice {args.voice} and marker voice {args.marker_voice}."
    chapters.insert(0, version_intro)

    chapters_to_mp3(args.language, args.voice, args.marker_voice, chapters, base_name)

# Run main() if script is called directly
if __name__ == "__main__":
    main()