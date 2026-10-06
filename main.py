import math
import os   # For environment variables and file path operations
import argparse   # For parsing command-line arguments
import subprocess   # For piping raw PCM directly into ffmpeg
import itertools   # For chaining the first segment back onto the generator

import asyncio   # For running async edge-tts synthesis
import aiohttp   # For handling edge-tts connection errors
import edge_tts   # Edge TTS engine for speech synthesis
from pydub import AudioSegment   # For audio processing and combining chunk MP3 files into a single MP3

from ebooklib import epub, ITEM_DOCUMENT, ITEM_COVER   # To read EPUB files and extract document parts
from bs4.element import NavigableString  # Represents text nodes within the HTML parse tree
from bs4 import BeautifulSoup   # To parse and clean up HTML content from EPUB
from bs4 import Tag   # For handling HTML tags in BeautifulSoup
import re   # Regular expressions for text processing

from cover import make_cover   # To compose the audiobook cover (book cover + logo strip + version and duration)

VERSION = "3.2.0"   # Single source of truth: spoken in the intro and shown on the cover

_SPOKEN_DIGITS = {
    "de": ["null", "eins", "zwei", "drei", "vier", "fünf", "sechs", "sieben", "acht", "neun"],
    "en": ["zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine"],
}

def spoken_version(language):
    """
    Spell out VERSION digit by digit for the intro.

    :param language: Language code ('de' or 'en').

    :return: The spoken version string.
    """
    digits = _SPOKEN_DIGITS[language.lower()]
    return " ".join(digits[int(digit)] for part in VERSION.split(".") for digit in part)

async def synthesize_chunk(text, output_path, voice):
    """
    Synthesize a single text chunk to an MP3 file using edge-tts.

    The audio is written to a temporary ".part" file and only moved to
    output_path once edge-tts has finished. edge_tts.Communicate.save() opens
    the target file before streaming, so a file interrupted mid-write would
    otherwise be left truncated. A truncated MP3 still decodes without any
    error, just shorter, which would silently clip audio when the chunk is
    reused on a later run. os.replace() is atomic, so output_path existing
    always means it is complete.

    :param text: The text to synthesize.
    :param output_path: File path where the MP3 will be saved.
    :param voice: Edge-TTS voice name.
    """
    partial_path = output_path + ".part"
    communicate = edge_tts.Communicate(text, voice)
    await communicate.save(partial_path)
    os.replace(partial_path, output_path)

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

    Documents are walked in spine order (the book's actual reading order),
    not manifest order, since nothing guarantees the two agree. Spine entries
    marked non-linear and the navigation document are skipped, since neither
    is narratable chapter content.

    :param epub_path: Path to the EPUB file.

    :return: List of chapters, each as a string "Title\nContent".
    """
    try:
        ebook = epub.read_epub(epub_path)
    except Exception as e:
        print(f"\033[31mError reading EPUB file '{epub_path}': {e}\033[0m")
        return []

    chapters = []

    for idref, linear in ebook.spine:
        if linear == 'no':
            continue

        doc_item = ebook.get_item_with_id(idref)
        if doc_item is None or doc_item.get_type() != ITEM_DOCUMENT or isinstance(doc_item, epub.EpubNav):
            continue

        try:
            soup = BeautifulSoup(doc_item.get_content(), 'html.parser')
            # Strip CSS and scripts so they never turn up as spoken text
            for unwanted in soup(['style', 'script']):
                unwanted.decompose()

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

                    # " " join separator so nested tags (e.g. <h1>Kapitel <em>Zwei</em></h1>)
                    # don't get concatenated without a space
                    current_title = el.get_text(" ", strip=True)

                elif isinstance(el, NavigableString):
                    # Collect chapter content, skip headings. Checks all ancestors,
                    # not just the direct parent, so text nested inside a heading
                    # (e.g. the <em> in the example above) isn't also picked up as body text.
                    if not any(isinstance(parent, Tag) and parent.name in ['h1', 'h2'] for parent in el.parents):
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

def epub_metadata_for_mp3(epub_path):
    """
    Extract the book metadata and cover image intended for embedding into
    the finished MP3, as opposed to bookkeeping fields that describe the
    EPUB file itself rather than the book (e.g. Sigil's own version, the
    calibre UUID, the last-modified date, or maintainer-specific custom
    fields like "Ordner"/"Version").

    "calibre:series" is embedded as-is, including the literal value
    "Standalone" for works that aren't part of a series -- there is no
    special-casing here, by design. Similarly, the maintainer's own custom
    "Ordner" and "Version" fields are embedded as-is, as custom (TXXX) tags,
    despite not being standard book metadata -- this maintainer wants them
    kept regardless.

    :param epub_path: Path to the EPUB file.

    :return: A tuple (metadata, cover_item). metadata is a dict with any of
             the keys "title", "artist", "language", "album", "track",
             "comment", "Ordner", "Version" that could be determined; keys
             with no value are omitted. cover_item is the ebooklib item
             holding the cover image, or None if none was found.
    """
    ebook = epub.read_epub(epub_path)
    metadata = {}

    def first(namespace, name):
        values = ebook.get_metadata(namespace, name)
        return values[0][0] if values else None

    title = first('DC', 'title')
    if title:
        metadata['title'] = title

    creator = first('DC', 'creator')
    if creator:
        metadata['artist'] = creator

    language = first('DC', 'language')
    if language:
        language_names = {
            "de": "German",
            "en": "English",
        }
        metadata['language'] = language_names.get(language.lower(), language)

    source = first('DC', 'source')
    if source:
        metadata['comment'] = source

    series = None
    series_index = None
    cover_id = None
    ordner = None
    version = None
    for _, attrs in ebook.get_metadata('OPF', 'meta'):
        name = attrs.get('name')
        if name == 'calibre:series':
            series = attrs.get('content')
        elif name == 'calibre:series_index':
            series_index = attrs.get('content')
        elif name == 'cover':
            cover_id = attrs.get('content')
        elif name == 'Ordner':
            ordner = attrs.get('content')
        elif name == 'Version':
            version = attrs.get('content')

    if series:
        metadata['album'] = series
        if series_index is not None:
            metadata['track'] = series_index

    if ordner:
        metadata['Ordner'] = ordner
    if version:
        metadata['Version'] = version

    # The "cover" meta's content is normally a manifest item id, but some
    # tools have been seen using a filename-like id instead. get_item_with_id()
    # only matches a real id, so fall back to whichever image the EPUB marks
    # as ITEM_COVER if the direct lookup comes up empty.
    cover_item = ebook.get_item_with_id(cover_id) if cover_id else None
    if cover_item is None:
        cover_item = next(iter(ebook.get_items_of_type(ITEM_COVER)), None)

    return metadata, cover_item

# Common German/English abbreviations that end in a period but aren't a
# sentence boundary. Not exhaustive -- an abbreviation missing from this list
# still gets treated as a sentence end, same as before this fix.
_ABBREVIATIONS = {
    "z", "b", "d", "h", "u", "a",  # single letters from "z. B.", "d. h.", "u. a." etc.
    "z.b", "d.h", "u.a", "v.a", "bzw", "usw", "etc", "ca", "dr", "prof",
    "nr", "bspw", "sog", "inkl", "exkl", "vgl", "ggf", "evtl", "insb",
    "mr", "mrs", "ms", "sr", "jr", "vs", "st", "e.g", "i.e",
}

def _split_sentences(text):
    """
    Split text into sentences on '.', '!' or '?' followed by whitespace,
    except when the word immediately before the punctuation is a known
    abbreviation (see _ABBREVIATIONS) -- e.g. "Dr. Müller" or "z. B. Äpfel"
    aren't split into "Dr." / "Müller ging..." and "z." / "B." / "Äpfel...".

    :param text: The text to split into sentences.

    :return: A list of sentences.
    """
    sentences = []
    start = 0
    for match in re.finditer(r'[.!?]+\s+', text):
        preceding = re.search(r'(\S+)$', text[start:match.start() + 1])
        word = preceding.group(1).rstrip('.!?').lower() if preceding else ""
        if word in _ABBREVIATIONS:
            continue
        sentences.append(text[start:match.end()].strip())
        start = match.end()
    sentences.append(text[start:].strip())
    return sentences

def split_text_into_chunks(text, max_length):
    """
    Split the given text into chunks not exceeding max_length characters, trying to preserve sentence boundaries.

    Sentence boundaries are detected with _split_sentences(), which knows
    about a short list of common abbreviations (e.g. "Dr.", "z. B.") so it
    doesn't cut a sentence in half right after one of those. This list is a
    heuristic, not exhaustive -- an abbreviation not on it will still be
    split on like before.

    :param text: The text to be split into chunks.
    :param max_length: Maximum number of characters per chunk.

    :return: A list of text chunks, each not exceeding max_length characters.
    """
    try:
        sentences = _split_sentences(text.strip())
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
                current_chunk = ""
        else:
            text_chunks.append(sentence)

    # Merge chunks shorter than 50 characters into the previous chunk, but
    # only if the combined result still fits max_length. Otherwise, several
    # short sentences in a row could merge into one chunk far larger than the
    # limit this function is supposed to enforce.
    merged = []
    for chunk in text_chunks:
        if merged and len(chunk.strip()) < 50 and len(merged[-1]) + 1 + len(chunk) <= max_length:
            merged[-1] += " " + chunk
        else:
            merged.append(chunk)

    return merged

def clean_text(text, language):
    """
    Clean up the text by replacing special quotes, mapping pause-carrying
    punctuation onto a comma, and removing characters unsupported by edge-tts.

    :param text: The text to clean.
    :param language: Language code ('de' or 'en') to determine allowed characters.

    :return: The cleaned text.
    """
    try:
        # Replace various types of quotes with standard ASCII quotes
        text = text.replace("«", '"').replace("»", '"')
        text = text.replace("„", '"').replace("“", '"').replace("”", '"')
        text = text.replace("‘", "'").replace("’", "'")

        # En/em dashes, ellipses and semicolons carry pause information, so map
        # them onto a comma (e.g. "zögerte – dann" becoming "zögerte, dann").
        # Any surrounding whitespace is absorbed into the substitution so this
        # doesn't leave a stray space before the comma.
        text = re.sub(r'\s*[–—]\s*', ', ', text)
        text = re.sub(r'\s*…\s*', ', ', text)
        text = re.sub(r'\s*;\s*', ', ', text)

        # Hyphen before a closing quote is read aloud as "dash"; use a pause: "I-" -> "I,"
        text = re.sub(r'\s*-+(?=")', ',', text)

        # Keep any Unicode letter or digit (not just ASCII plus German
        # umlauts) so accented proper names like "José" or "François" survive
        # instead of being silently mangled, plus common currency symbols.
        if language.lower() == "de":
            text = re.sub(r"[^\w.,:!?\"()\n\- /€$£]", "", text)
        elif language.lower() == "en":
            text = re.sub(r"[^\w.,:!?\"'()\n\- /€$£]", "", text)

        # \w above also matches "_", which Azure's markdown-aware text
        # pipeline treats as emphasis syntax rather than a literal character,
        # so it's stripped separately here. "*", "#" and "`" are markdown-
        # special too, but those are already excluded by the allowlist above.
        text = text.replace("_", "")

        # Spaces after punctuation. Semicolons are handled above and mapped to
        # a comma before this point, so they never reach here.
        text = re.sub(r'([.!?])(?=\S)', r'\1 ', text)
        text = re.sub(r'([,:])(?=\S)', r'\1 ', text)

        # Spaces before opening parenthesis
        text = re.sub(r'(?<!\s)\(', ' (', text)

        return text
    except Exception as e:
        print(f"\033[31mError cleaning text: {e}\033[0m")
        return text

# Measured words per minute of the finished audio (including chapter markers).
# The "en" value was measured on a 29-hour audiobook narrated with en-GB-RyanNeural;
# the rate depends on the voice, so other voices may deviate somewhat.
_WORDS_PER_MINUTE = {"de": 157, "en": 173}

def format_duration(estimated_minutes, language):
    """
    Format a duration in minutes into a human-readable string with hours and minutes.
    Handles singular/plural for both German and English.

    :param estimated_minutes: Duration in minutes (integer).
    :param language: Language code ('de' or 'en').

    :return: Formatted duration string, e.g. "1 Stunde und 30 Minuten" or "1 hour and 30 minutes".
    """
    hours = estimated_minutes // 60
    minutes = estimated_minutes % 60

    if language.lower() == "de":
        if hours > 0 and minutes > 0:
            hour_word = "Stunde" if hours == 1 else "Stunden"
            minute_word = "Minute" if minutes == 1 else "Minuten"
            return f"{hours} {hour_word} und {minutes} {minute_word}"
        elif hours > 0:
            hour_word = "Stunde" if hours == 1 else "Stunden"
            return f"{hours} {hour_word}"
        else:
            minute_word = "Minute" if minutes == 1 else "Minuten"
            return f"{minutes} {minute_word}"
    else:
        if hours > 0 and minutes > 0:
            hour_word = "hour" if hours == 1 else "hours"
            minute_word = "minute" if minutes == 1 else "minutes"
            return f"{hours} {hour_word} and {minutes} {minute_word}"
        elif hours > 0:
            hour_word = "hour" if hours == 1 else "hours"
            return f"{hours} {hour_word}"
        else:
            minute_word = "minute" if minutes == 1 else "minutes"
            return f"{minutes} {minute_word}"

def iter_audio_segments(output_dir, base_name, total_chunks, chapter_end_chunk_indices, failed_chunks=None):
    """
    Yield the chunk MP3s one at a time as AudioSegments, inserting 2 seconds of
    silence after every end-of-chapter marker.

    This is a generator on purpose, because so only a single chunk is ever held in memory,
    instead of the whole audiobook.

    :param output_dir: Directory containing the temporary chunk MP3 files.
    :param base_name: Base filename used for the chunk MP3 files.
    :param total_chunks: Number of chunks written (i.e. global_chunk_counter).
    :param chapter_end_chunk_indices: Set of chunk indices that are chapter end markers.
    :param failed_chunks: Optional list. Any chunk index that fails to load is
                    appended to it, so the caller can warn about a resulting gap
                    in the final audio instead of it passing unnoticed.

    :return: AudioSegment objects in playback order.
    """
    for i in range(1, total_chunks):
        assembly_mp3_path = os.path.join(output_dir, f"{base_name}_chunk_{i}.mp3")
        try:
            chunk_audio = AudioSegment.from_mp3(assembly_mp3_path)
        except Exception as e:
            print(f"\033[31mError loading MP3 chunk {i}: {e}\033[0m")
            if failed_chunks is not None:
                failed_chunks.append(i)
            continue

        yield chunk_audio

        # Add 2 seconds of silence after end-of-chapter markers
        if i in chapter_end_chunk_indices:
            yield AudioSegment.silent(duration=2000, frame_rate=chunk_audio.frame_rate)

def print_duration(mp3_path):
    """
    Print the total duration of the finished audiobook as HH:MM:SS, using the
    same ffprobe query documented in the README (just run automatically
    instead of by hand, and formatted in Python instead of piping into awk).

    :param mp3_path: Path to the finished audiobook.

    :return: The duration as "HH:MM:SS", or None if it could not be determined.
    """
    try:
        result = subprocess.run(
            ["ffprobe", "-i", mp3_path, "-show_entries", "format=duration", "-v", "quiet", "-of", "csv=p=0"],
            capture_output=True, text=True, check=True,
        )
        total_seconds = int(float(result.stdout.strip()))
        hours, remainder = divmod(total_seconds, 3600)
        minutes, seconds = divmod(remainder, 60)
        # Cyan text, same as the "assembled" message above it
        duration = f"{hours:02d}:{minutes:02d}:{seconds:02d}"
        print(f"\033[36mDuration: {duration}\033[0m")
        return duration
    except Exception as e:
        print(f"\033[31mError determining audiobook duration: {e}\033[0m")
        return None

def replace_cover_art(mp3_path, cover_path):
    """
    Replace the cover art of an existing MP3 in place without re-encoding and
    without touching its other metadata (same approach as the README's ffmpeg
    one-liner). The audio is copied into a temporary file first, which only
    replaces the original once ffmpeg has succeeded.

    :param mp3_path: Path to the MP3 file.
    :param cover_path: Path to the new cover image.
    """
    temp_path = os.path.splitext(mp3_path)[0] + ".tmp.mp3"
    cmd = [
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
        "-i", mp3_path, "-i", cover_path,
        "-map", "0:a", "-map", "1:v", "-c", "copy", "-map_metadata", "0",
        "-disposition:v", "attached_pic", "-id3v2_version", "3", temp_path,
    ]
    try:
        subprocess.run(cmd, check=True)
        os.replace(temp_path, mp3_path)
    finally:
        if os.path.exists(temp_path):
            os.remove(temp_path)

def export_mp3_streaming(segments, mp3_output_path, bitrate="48k", metadata=None, cover_path=None):
    """
    Encode an iterable of AudioSegments into a single MP3 by piping raw PCM
    straight into ffmpeg.

    pydub's own export() writes a temporary WAV file first, and the WAV/RIFF
    header stores sizes as 32-bit unsigned integers. Anything past 4 GiB of PCM
    (roughly 25 hours at 24 kHz mono) therefore dies with
    "'L' format requires 0 <= number <= 4294967295". Raw PCM has no header and
    no size field, so this approach has no length limit.

    :param segments: Iterable of AudioSegment objects, in playback order.
    :param mp3_output_path: Path of the MP3 file to write.
    :param bitrate: MP3 bitrate passed to libmp3lame (default: "48k", matching the 48 kbps CBR that edge-tts
                    delivers for the individual chunks).
    :param metadata: Optional dict of ID3 tags to write (e.g. "title", "artist",
                     "album", "track", "language", "comment"). Passed straight
                     to ffmpeg's -metadata option, one key at a time.
    :param cover_path: Optional path to a cover image file. If given, it's added
                       as a second input and embedded as the MP3's attached picture.
    """
    stream = iter(segments)
    try:
        first = next(stream)
    except StopIteration:
        raise RuntimeError("No audio segments to export")

    # The first segment defines the output format. Everything else is coerced to match.
    frame_rate = first.frame_rate
    channels = first.channels

    cmd = [
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
        "-f", "s16le", "-ar", str(frame_rate), "-ac", str(channels),
        "-i", "pipe:0",
    ]

    if cover_path:
        cmd += ["-i", cover_path, "-map", "0:a", "-map", "1:v", "-c:v", "copy", "-disposition:v", "attached_pic"]

    cmd += ["-c:a", "libmp3lame", "-b:a", bitrate]

    for key, value in (metadata or {}).items():
        cmd += ["-metadata", f"{key}={value}"]

    cmd += ["-id3v2_version", "3", mp3_output_path]

    ffmpeg_process = subprocess.Popen(cmd, stdin=subprocess.PIPE)

    try:
        for segment in itertools.chain([first], stream):
            segment = segment.set_frame_rate(frame_rate).set_channels(channels).set_sample_width(2)
            ffmpeg_process.stdin.write(segment.raw_data)
    except BrokenPipeError:
        pass   # ffmpeg died early; the return code below reports why
    finally:
        try:
            ffmpeg_process.stdin.close()
        except BrokenPipeError:
            pass

    return_code = ffmpeg_process.wait()
    if return_code != 0:
        raise RuntimeError(f"ffmpeg exited with code {return_code}")

def chapters_to_mp3(language, voice, marker_voice, chapters, base_name, metadata=None, cover_item=None):
    """
    Convert chapters into speech and combine them into a single MP3 file.

    :param language: Language code ('de' or 'en') for the text-to-speech model.
    :param voice: Edge-TTS voice name for main narration.
    :param marker_voice: Edge-TTS voice name for markers.
    :param chapters: List of chapters, each containing text to be converted to speech.
    :param base_name: Base filename for output files (no extension).
    :param metadata: Optional dict of ID3 tags from epub_metadata_for_mp3(), passed
                     straight through to export_mp3_streaming().
    :param cover_item: Optional ebooklib item holding the cover image, from
                       epub_metadata_for_mp3(). Written to a temporary file next
                       to the chunk MP3s for the duration of the export, then removed.
    """
    output_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "output")

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

                # Reuse chunks from an interrupted run. Thanks to the atomic write in
                # synthesize_chunk, an existing file is guaranteed to be complete.
                if os.path.exists(chunk_mp3_path):
                    # Blue text
                    print(f"\033[34m            Reused chunk {local_chunk_counter} of {len(text_chunks)} for chapter {chapter_index}/{len(chapters)} as chunk {global_chunk_counter}\033[0m")
                    local_chunk_counter += 1
                    global_chunk_counter += 1
                    continue

                # synthesize_chunk_safe retries indefinitely so that no chunks will be skipped
                await synthesize_chunk_safe(chunk, chunk_mp3_path, voice)
                await asyncio.sleep(0.5)

                # Green text
                print(f"\033[32m            Saved chunk {local_chunk_counter} of {len(text_chunks)} for chapter {chapter_index}/{len(chapters)} as chunk {global_chunk_counter}\033[0m")
                local_chunk_counter += 1
                global_chunk_counter += 1

            # Add an audio marker for end of chapter. chapters[0] is always the
            # version_intro inserted by main(), not a real book chapter, so it's
            # numbered separately here rather than counted as "chapter 1".
            marker_mp3_path = os.path.join(output_dir, f"{base_name}_chunk_{global_chunk_counter}.mp3")
            display_number = chapter_index - 1

            if chapter_index < len(chapters):
                next_chapter = chapters[chapter_index]
                word_count = len(next_chapter.split())
                estimated_minutes = max(1, round(word_count / _WORDS_PER_MINUTE[language.lower()]))
                duration_str = format_duration(estimated_minutes, language)

                if language.lower() == "de":
                    this_part = "Ende der Einleitung" if display_number == 0 else f"Ende des Kapitels {display_number}"
                    marker_text = f"{this_part}. Das nächste Kapitel dauert etwa {duration_str}."
                else:
                    this_part = "End of the introduction" if display_number == 0 else f"End of chapter {display_number}"
                    marker_text = f"{this_part}. The next chapter will take about {duration_str}."
            else:
                if language.lower() == "de":
                    marker_text = "Ende der Einleitung" if display_number == 0 else f"Ende des Kapitels {display_number}"
                else:
                    marker_text = "End of the introduction" if display_number == 0 else f"End of chapter {display_number}"

            # Markers also retry indefinitely
            if os.path.exists(marker_mp3_path):
                # Bright blue text
                print(f"\033[94m        Reused chapter {display_number} end marker as chunk {global_chunk_counter}\033[0m")
            else:
                await synthesize_chunk_safe(marker_text, marker_mp3_path, marker_voice)

                # Bright green text
                print(f"\033[92m        Saved chapter {display_number} end marker as chunk {global_chunk_counter}\033[0m")

            chapter_end_chunk_indices.append(global_chunk_counter)
            global_chunk_counter += 1

    export_succeeded = False
    cover_path = None
    generated_cover_path = None

    try:
        asyncio.run(process())

        # Combine all MP3 chunks into a single MP3 audiobook.
        # Streamed chunk by chunk, so neither RAM nor the 4 GiB WAV limit apply.
        mp3_output_path = os.path.join(output_dir, base_name + ".mp3")
        marker_indices = set(chapter_end_chunk_indices)

        if cover_item is not None:
            cover_ext = {"image/jpeg": ".jpg", "image/png": ".png"}.get(cover_item.media_type, ".img")
            cover_path = os.path.join(output_dir, f"{base_name}_cover{cover_ext}")
            try:
                with open(cover_path, "wb") as cover_file:
                    cover_file.write(cover_item.get_content())
            except Exception as e:
                print(f"\033[31mError writing temporary cover file '{cover_path}': {e}\033[0m")
                cover_path = None

        try:
            failed_chunks = []
            export_mp3_streaming(
                iter_audio_segments(
                    output_dir,
                    base_name,
                    global_chunk_counter,
                    marker_indices,
                    failed_chunks=failed_chunks
                ),
                mp3_output_path,
                metadata=metadata,
                cover_path=cover_path,
            )
            export_succeeded = True

            # Cyan text
            print(f"\033[36mAudiobook assembled and saved to: {mp3_output_path}\033[0m")

            if failed_chunks:
                missing_markers = [i for i in failed_chunks if i in marker_indices]
                print(f"\033[31mWarning: {len(failed_chunks)} chunk(s) failed to load and are MISSING from the final audio: {failed_chunks}\033[0m")
                if missing_markers:
                    print(f"\033[31mThis includes {len(missing_markers)} chapter-end marker(s) (and the silence after them), so a chapter boundary was skipped silently in the output.\033[0m")

            duration = print_duration(mp3_output_path)

            # The duration is only known now, so the generated cover replaces the book's own cover afterwards.
            # If this fails, the MP3 simply keeps the original cover.
            if duration:
                generated_cover_path = os.path.join(output_dir, f"{base_name}_cover_generated.png")
                try:
                    make_cover(cover_path, VERSION, duration, generated_cover_path)
                    replace_cover_art(mp3_output_path, generated_cover_path)
                    print(f"\033[36mCover generated and embedded\033[0m")
                except Exception as e:
                    print(f"\033[31mError generating or embedding the cover (the original cover was kept): {e}\033[0m")
        except Exception as e:
            print(f"\033[31mError exporting MP3 file '{mp3_output_path}': {e}\033[0m")

    finally:
        for temp_cover in (cover_path, generated_cover_path):
            if temp_cover and os.path.exists(temp_cover):
                try:
                    os.remove(temp_cover)
                except Exception as e:
                    print(f"\033[31mError deleting temporary cover file '{temp_cover}': {e}\033[0m")

        if not export_succeeded:
            # Yellow text: keeping chunks lets the next run resume instead of starting over
            print(f"\033[33mRun did not finish. Keeping temporary MP3 chunks in '{output_dir}' so the next run can resume.\033[0m")
        else:
            # Gray text
            print(f"\033[37mCleaning up temporary MP3 files...\033[0m")
            for i in range(1, global_chunk_counter):
                for mp3_to_remove in (
                    os.path.join(output_dir, f"{base_name}_chunk_{i}.mp3"),
                    os.path.join(output_dir, f"{base_name}_chunk_{i}.mp3.part"),
                ):
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
    parser.add_argument("language", type=str.lower,choices=["de", "en"], metavar="{de,en}", help="Language code of the book")
    parser.add_argument("voice", help="Edge-TTS voice for main narration (see https://tts.travisvn.com for options)")
    parser.add_argument("marker_voice", help="Edge-TTS voice for markers (see https://tts.travisvn.com for options)")

    args = parser.parse_args()
    language = args.language

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
    if language == "de":
        version_intro = f"Version {spoken_version(language)} der Earwyrm Pipeline. Generiert mit der Stimme {args.voice} und der Markierungsstimme {args.marker_voice}."
    else:
        version_intro = f"Version {spoken_version(language)} of the Earwyrm Pipeline. Generated with voice {args.voice} and marker voice {args.marker_voice}."

    chapters.insert(0, version_intro)

    metadata, cover_item = epub_metadata_for_mp3(args.epub_path)

    chapters_to_mp3(
        language,
        args.voice,
        args.marker_voice,
        chapters,
        base_name,
        metadata=metadata,
        cover_item=cover_item
    )

# Run main() if script is called directly
if __name__ == "__main__":
    main()