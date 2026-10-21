import os   # For environment variables and file path operations
import argparse   # For parsing command-line arguments
import subprocess   # For piping raw PCM directly into ffmpeg
import itertools   # For chaining the first segment back onto the generator
import time   # For measuring elapsed time and estimating the remaining runtime

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

VERSION = "3.3.5"   # Single source of truth: spoken in the intro and shown on the cover

_SPOKEN_DIGITS = {
    "de": ["null", "eins", "zwei", "drei", "vier", "fünf", "sechs", "sieben", "acht", "neun"],
    "en": ["zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine"],
}

# Default voices per language, used when voice and/or marker voice are not
# given on the command line. The narration voice and the marker voice are
# deliberately different, so markers stand out from the narration.
_DEFAULT_VOICE_PROFILES = {
    "de": {"voice": "de-DE-SeraphinaMultilingualNeural", "marker_voice": "de-DE-ConradNeural"},
    "en": {"voice": "en-GB-RyanNeural", "marker_voice": "en-GB-SoniaNeural"},
}

def resolve_voices(language, voice=None, marker_voice=None):
    """
    Fill in missing voices from the default voice profile of the language.

    :param language: Language code ('de' or 'en').
    :param voice: Narration voice from the command line, or None.
    :param marker_voice: Marker voice from the command line, or None.

    :return: A tuple (voice, marker_voice, voice_is_default, marker_voice_is_default).
    """
    profile = _DEFAULT_VOICE_PROFILES[language.lower()]
    voice_is_default = not voice
    marker_voice_is_default = not marker_voice
    return (
        profile["voice"] if voice_is_default else voice,
        profile["marker_voice"] if marker_voice_is_default else marker_voice,
        voice_is_default,
        marker_voice_is_default,
    )

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
    Synthesize a single text chunk with retries and exponential backoff.

    Retries are unlimited, except for repeated 403 errors during the
    WebSocket handshake: those are not transient (usually an outdated
    edge-tts), so the run is aborted after 5 attempts.

    :param text: The text to synthesize.
    :param output_path: File path where the MP3 will be saved.
    :param voice: Edge-TTS voice name.
    :param max_wait: Maximum wait time in seconds between retries (default: 60).

    :return: The number of failed attempts before synthesis succeeded (0 if it worked first time).

    :raises RuntimeError: If the handshake is rejected with 403 five times in a row.
    """
    attempt = 0
    while True:
        try:
            await synthesize_chunk(text, output_path, voice)
            if attempt > 0:
                # Yellow text — recovered after retries
                print(f"\033[33m            Recovered after {attempt} retries: {text[:50]}...\033[0m")
            return attempt
        except (edge_tts.exceptions.NoAudioReceived, aiohttp.client_exceptions.WSServerHandshakeError) as e:
            attempt += 1

            # A 403 on the handshake is not a transient error, so retrying forever is pointless
            if getattr(e, "status", None) == 403 and attempt >= 5:
                raise RuntimeError(
                    "Edge TTS rejects the request with 403. Update edge-tts: uv pip install -U edge-tts"
                ) from e

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

    :return: List of chapters, each as a tuple (title, body). title is None
             if the section has no <h1>/<h2> heading, body never contains the heading.
    """
    try:
        ebook = epub.read_epub(epub_path)
    except Exception as e:
        print(f"\033[31mError reading EPUB file '{epub_path}': {e}\033[0m")
        return []

    chapters = []

    def save_chapter(title, content):
        # Filter out None-Strings and empty rows
        body = '\n'.join(
            line for line in ''.join(content).splitlines()
            if line.strip() and line.strip().lower() != 'none'
        )
        if title or body:
            chapters.append((title or None, body))

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
                        save_chapter(current_title, current_content)
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
                save_chapter(current_title, current_content)
        except Exception as e:
            print(f"\033[31mError processing EPUB document item: {e}\033[0m")
            continue

    return chapters

def epub_metadata_for_mp3(epub_path, language):
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
    :param language: Output language code ('de' or 'en'). This is mapped
                     explicitly to the ISO 639-2 code used by the MP3 ID3
                     language tag ('deu' or 'eng').

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

    # Use the language selected for the audiobook, not the EPUB's DC language
    # metadata. Internally the pipeline uses "de" / "en"; for the MP3 ID3
    # language tag FFmpeg writes these as the ISO 639-2 codes "deu" / "eng".
    language_names = {
        "de": "deu",
        "en": "eng",
    }
    metadata['language'] = language_names[language.lower()]

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
# Since 3.3.2 this table is only the fallback until enough narration of the
# current run has been measured (see estimate_chapter_minutes()).
_WORDS_PER_MINUTE = {"de": 157, "en": 173}

# edge-tts delivers its chunks as 48 kbps CBR MP3, so a chunk's duration
# follows directly from its file size, without decoding it.
_EDGE_TTS_BITS_PER_SECOND = 48000

# Minimum amount of measured narration (in seconds) before the measured rate
# replaces the _WORDS_PER_MINUTE fallback. Below that, a few short chunks
# (e.g. only the intro) would make the estimate jumpy.
_MIN_MEASURED_SECONDS = 120

def mp3_chunk_seconds(mp3_path):
    """
    Determine the duration of an edge-tts chunk MP3 from its file size.

    :param mp3_path: Path to the chunk MP3.

    :return: Duration in seconds, or None if the file size could not be read.
    """
    try:
        return os.path.getsize(mp3_path) * 8 / _EDGE_TTS_BITS_PER_SECOND
    except OSError:
        return None

def estimate_chapter_minutes(word_count, language, measured_words=0, measured_seconds=0.0):
    """
    Estimate how long a chapter will take, based on the narration rate
    actually measured in the current run if there is enough of it, otherwise
    on the static _WORDS_PER_MINUTE table.

    :param word_count: Number of words in the chapter.
    :param language: Language code ('de' or 'en').
    :param measured_words: Number of narrated words measured so far.
    :param measured_seconds: Audio duration of those words in seconds.

    :return: A tuple (estimated_minutes, words_per_minute, is_measured).
    """
    if measured_seconds >= _MIN_MEASURED_SECONDS and measured_words > 0:
        words_per_minute = measured_words / (measured_seconds / 60)
        is_measured = True
    else:
        words_per_minute = _WORDS_PER_MINUTE[language.lower()]
        is_measured = False

    estimated_minutes = max(1, round(word_count / words_per_minute))
    return estimated_minutes, words_per_minute, is_measured

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

def chapter_labels(chapters, language):
    """
    Return the spoken label of every chapter: its heading as it stands in the
    EPUB, or None if the section has no heading. Index 0 is the introduction.

    :param chapters: List of (title, body) tuples, the introduction first.
    :param language: Language code ('de' or 'en').

    :return: List of labels (str or None), same length as chapters.
    """
    labels = ["introduction"]
    for title, _ in chapters[1:]:
        cleaned = clean_text(title, language).strip().rstrip(".,:!?").strip() if title else ""
        labels.append(cleaned or None)
    return labels

def format_clock(seconds):
    """
    Format a number of seconds as HH:MM:SS for progress output.

    :param seconds: Duration in seconds (int or float).

    :return: The formatted duration, e.g. "01:02:03".
    """
    total_seconds = max(0, int(round(seconds)))
    hours, remainder = divmod(total_seconds, 3600)
    minutes, secs = divmod(remainder, 60)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}"

class ProgressTracker:
    """
    Keep track of the overall synthesis progress across all chapters.

    Every audio chunk (narration, chapter start marker or chapter end marker)
    counts as one unit. The ETA is extrapolated from the average time newly
    synthesized chunks took so far. Chunks already present from an earlier,
    interrupted run are counted up front and excluded from the ETA, since
    reusing them takes no time.
    """

    def __init__(self, total, already_present):
        """
        :param total: Total number of chunks this run will produce.
        :param already_present: Number of those chunks that already exist on disk.
        """
        self.total = total
        self.pending_reuse = already_present
        self.done = 0
        self.synthesized = 0
        self.reused = 0
        self.retries = 0
        self.synthesis_seconds = 0.0
        self.started = time.monotonic()

    def record_reused(self):
        """Record a chunk that was reused from an earlier run."""
        self.done += 1
        self.reused += 1
        self.pending_reuse = max(0, self.pending_reuse - 1)

    def record_synthesized(self, seconds, retries=0):
        """
        Record a newly synthesized chunk.

        :param seconds: Wall-clock time spent on this chunk, including retries and pauses.
        :param retries: Number of failed attempts before it succeeded.
        """
        self.done += 1
        self.synthesized += 1
        self.retries += retries
        self.synthesis_seconds += seconds

    def eta_seconds(self):
        """
        :return: Estimated seconds until all chunks are synthesized, or None
                 if nothing has been synthesized yet to base an estimate on.
        """
        if self.synthesized == 0:
            return None
        remaining = max(0, self.total - self.done - self.pending_reuse)
        return remaining * self.synthesis_seconds / self.synthesized

    def prefix(self):
        """
        :return: A progress prefix like "[ 123/4567   2.7% | ETA 01:23:45]".
        """
        percent = 100.0 * self.done / self.total if self.total else 100.0
        eta = self.eta_seconds()
        eta_text = format_clock(eta) if eta is not None else "--:--:--"
        width = len(str(self.total))
        return f"[{self.done:>{width}}/{self.total} {percent:5.1f}% | ETA {eta_text}]"

    def summary(self):
        """
        :return: A one-line summary of the synthesis phase.
        """
        elapsed = format_clock(time.monotonic() - self.started)
        return (f"Synthesis finished after {elapsed}: {self.synthesized} chunk(s) synthesized, "
                f"{self.reused} reused, {self.retries} retry(s)")

def iter_audio_segments(output_dir, base_name, total_chunks, chapter_end_chunk_indices, failed_chunks=None, chapter_start_chunk_indices=None, show_progress=False):
    """
    Yield the chunk MP3s one at a time as AudioSegments, inserting 2 seconds of
    silence after every end-of-chapter marker and 1 second of silence after
    every start-of-chapter marker.

    This is a generator on purpose, because so only a single chunk is ever held in memory,
    instead of the whole audiobook.

    :param output_dir: Directory containing the temporary chunk MP3 files.
    :param base_name: Base filename used for the chunk MP3 files.
    :param total_chunks: Number of chunks written (i.e. global_chunk_counter).
    :param chapter_end_chunk_indices: Set of chunk indices that are chapter end markers.
    :param failed_chunks: Optional list. Any chunk index that fails to load is
                    appended to it, so the caller can warn about a resulting gap
                    in the final audio instead of it passing unnoticed.
    :param chapter_start_chunk_indices: Optional set of chunk indices that are
                    chapter start markers.
    :param show_progress: If True, print the assembly progress in steps of 10%.

    :return: AudioSegment objects in playback order.
    """
    chunk_count = total_chunks - 1
    progress_step = max(1, chunk_count // 10)

    for i in range(1, total_chunks):
        if show_progress and (i % progress_step == 0 or i == chunk_count):
            # Gray text
            print(f"\033[37m    Assembling: {i}/{chunk_count} chunks ({100.0 * i / chunk_count:.0f}%)\033[0m")

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

        # Add 1 second of silence after start-of-chapter markers, so the
        # announcement doesn't run straight into the narration
        if chapter_start_chunk_indices and i in chapter_start_chunk_indices:
            yield AudioSegment.silent(duration=1000, frame_rate=chunk_audio.frame_rate)

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
    :param chapters: List of (title, body) tuples as returned by epub_to_chapters(),
                     with the version intro as (None, text) at index 0.
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

    # Clean and split every chapter up front, so the total number of chunks
    # (and thereby the overall progress) is known before synthesis starts.
    # The headings are not part of the bodies, the start markers speak them.
    chapter_chunks = [
        split_text_into_chunks(clean_text(body, language), max_length=500)
        for _, body in chapters
    ]
    labels = chapter_labels(chapters, language)

    # Narration chunks + one start marker for each titled real chapter + one end marker per chapter.
    # Untitled sections deliberately have no start marker.
    total_start_markers = sum(1 for label in labels[1:] if label)
    total_units = sum(len(text_chunks) for text_chunks in chapter_chunks) + total_start_markers + len(chapters)
    already_present = sum(
        1 for i in range(1, total_units + 1)
        if os.path.exists(os.path.join(output_dir, f"{base_name}_chunk_{i}.mp3"))
    )
    progress = ProgressTracker(total_units, already_present)

    # Cyan text
    plan = f"Plan: introduction + {len(chapters) - 1} chapter(s), {total_units} audio chunks including markers"
    if already_present:
        plan += f", {already_present} already present from a previous run"
    print(f"\033[36m{plan}\033[0m")

    global_chunk_counter = 1
    chapter_end_chunk_indices = []
    chapter_start_chunk_indices = []

    # Narration rate measured in this run (narration chunks only, no markers),
    # used for the "next chapter takes about ..." announcements
    measured_words = 0
    measured_seconds = 0.0

    def measure_chunk(chunk_text, chunk_mp3_path):
        nonlocal measured_words, measured_seconds
        seconds = mp3_chunk_seconds(chunk_mp3_path)
        if seconds:
            measured_words += len(chunk_text.split())
            measured_seconds += seconds

    async def process():
        nonlocal global_chunk_counter

        for chapter_index in range(1, len(chapters) + 1):
            text_chunks = chapter_chunks[chapter_index - 1]
            local_chunk_counter = 1

            # chapters[0] is always the version intro inserted by main(), not a
            # real book chapter. A chapter without a heading has label None.
            label = labels[chapter_index - 1]
            part_label = label or "untitled"

            # Magenta text
            print(f"\033[35m{progress.prefix()}     Processing chapter {chapter_index}/{len(chapters)} ({part_label}) with {len(text_chunks)} chunks\033[0m")

            # Add a start marker only for titled real chapters. The introduction
            # and untitled sections get no start marker.
            if chapter_index > 1 and label:
                start_marker_mp3_path = os.path.join(output_dir, f"{base_name}_chunk_{global_chunk_counter}.mp3")
                start_marker_text = f"{label}."

                if os.path.exists(start_marker_mp3_path):
                    progress.record_reused()
                    # Bright blue text
                    print(f"\\033[94m{progress.prefix()}         Reused {part_label} start marker as chunk {global_chunk_counter}\\033[0m")
                else:
                    started = time.monotonic()
                    retries = await synthesize_chunk_safe(start_marker_text, start_marker_mp3_path, marker_voice)
                    progress.record_synthesized(time.monotonic() - started, retries)

                    # Bright green text
                    print(f"\\033[92m{progress.prefix()}         Saved {part_label} start marker as chunk {global_chunk_counter}\\033[0m")

                chapter_start_chunk_indices.append(global_chunk_counter)
                global_chunk_counter += 1

            # Convert each text chunk to an MP3 file using edge-tts
            for chunk in text_chunks:
                chunk_mp3_path = os.path.join(output_dir, f"{base_name}_chunk_{global_chunk_counter}.mp3")

                # Reuse chunks from an interrupted run. Thanks to the atomic write in
                # synthesize_chunk, an existing file is guaranteed to be complete.
                if os.path.exists(chunk_mp3_path):
                    measure_chunk(chunk, chunk_mp3_path)
                    progress.record_reused()
                    # Blue text
                    print(f"\033[34m{progress.prefix()}             Reused chunk {local_chunk_counter} of {len(text_chunks)} for chapter {chapter_index}/{len(chapters)} as chunk {global_chunk_counter}\033[0m")
                    local_chunk_counter += 1
                    global_chunk_counter += 1
                    continue

                # synthesize_chunk_safe retries so that no chunks will be skipped
                started = time.monotonic()
                retries = await synthesize_chunk_safe(chunk, chunk_mp3_path, voice)
                await asyncio.sleep(0.5)
                progress.record_synthesized(time.monotonic() - started, retries)
                measure_chunk(chunk, chunk_mp3_path)

                # Green text
                print(f"\033[32m{progress.prefix()}             Saved chunk {local_chunk_counter} of {len(text_chunks)} for chapter {chapter_index}/{len(chapters)} as chunk {global_chunk_counter}\033[0m")
                local_chunk_counter += 1
                global_chunk_counter += 1

            # Add an audio marker for end of chapter, announcing the heading of
            # the next chapter (or that it has none) and its estimated duration.
            marker_mp3_path = os.path.join(output_dir, f"{base_name}_chunk_{global_chunk_counter}.mp3")

            if chapter_index < len(chapters):
                # Count the words of the cleaned chunks, i.e. exactly what will be
                # spoken, matching how the measured rate is counted
                word_count = sum(len(text_chunk.split()) for text_chunk in chapter_chunks[chapter_index])
                estimated_minutes, words_per_minute, is_measured = estimate_chapter_minutes(
                    word_count, language, measured_words, measured_seconds
                )
                duration_str = format_duration(estimated_minutes, language)

                # Gray text
                rate_source = "measured" if is_measured else "default"
                print(f"\033[37m{progress.prefix()}         Next chapter: {word_count} words, about {estimated_minutes} min at {words_per_minute:.0f} words/min ({rate_source})\033[0m")
                if language.lower() == "de":
                    this_part = "Ende der Einleitung" if chapter_index == 1 else (
                        f"Ende von {label}" if label else "Ende des Kapitels")
                    marker_text = f"{this_part}. Das nächste Kapitel dauert etwa {duration_str}."
                else:
                    this_part = "End of the introduction" if chapter_index == 1 else (
                        f"End of {label}" if label else "End of the chapter")
                    marker_text = f"{this_part}. The next chapter will take about {duration_str}."
            else:
                if language.lower() == "de":
                    marker_text = "Ende der Einleitung" if chapter_index == 1 else (
                        f"Ende von {label}" if label else "Ende des Kapitels")
                else:
                    marker_text = "End of the introduction" if chapter_index == 1 else (
                        f"End of {label}" if label else "End of the chapter")

            if os.path.exists(marker_mp3_path):
                progress.record_reused()
                # Bright blue text
                print(f"\033[94m{progress.prefix()}         Reused {part_label} end marker as chunk {global_chunk_counter}\033[0m")
            else:
                started = time.monotonic()
                retries = await synthesize_chunk_safe(marker_text, marker_mp3_path, marker_voice)
                progress.record_synthesized(time.monotonic() - started, retries)

                # Bright green text
                print(f"\033[92m{progress.prefix()}         Saved {part_label} end marker as chunk {global_chunk_counter}\033[0m")

            chapter_end_chunk_indices.append(global_chunk_counter)
            global_chunk_counter += 1

    export_succeeded = False
    cover_path = None
    generated_cover_path = None

    try:
        asyncio.run(process())

        # Cyan text
        print(f"\033[36m{progress.summary()}\033[0m")

        if measured_seconds > 0:
            print(f"\033[36mMeasured narration rate: {measured_words / (measured_seconds / 60):.0f} words/min "
                  f"over {format_clock(measured_seconds)} of narration (default table: {_WORDS_PER_MINUTE[language.lower()]} words/min)\033[0m")

        # Combine all MP3 chunks into a single MP3 audiobook.
        # Streamed chunk by chunk, so neither RAM nor the 4 GiB WAV limit apply.
        mp3_output_path = os.path.join(output_dir, base_name + ".mp3")
        marker_indices = set(chapter_end_chunk_indices)
        start_marker_indices = set(chapter_start_chunk_indices)

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
            # Cyan text
            print(f"\033[36mAssembling audiobook from {global_chunk_counter - 1} chunks...\033[0m")
            export_mp3_streaming(
                iter_audio_segments(
                    output_dir,
                    base_name,
                    global_chunk_counter,
                    marker_indices,
                    failed_chunks=failed_chunks,
                    chapter_start_chunk_indices=start_marker_indices,
                    show_progress=True
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

        # Cyan text
        print(f"\033[36mTotal runtime: {format_clock(time.monotonic() - progress.started)}\033[0m")

# Command-line entry point
def main():
    """
    Command-line entry point: parse arguments and convert EPUB to audio.
    """
    parser = argparse.ArgumentParser(description="Convert EPUB to TTS audio")
    parser.add_argument("epub_path", help="Path to the EPUB file")
    parser.add_argument("language", type=str.lower, choices=["de", "en"], metavar="{de,en}", help="Language code of the book")
    parser.add_argument("voice", nargs="?", default=None,
                        help="Edge-TTS voice for main narration (optional, default depends on language: "
                             + ", ".join(f"{lang}={profile['voice']}" for lang, profile in _DEFAULT_VOICE_PROFILES.items())
                             + "; see https://tts.travisvn.com for options)")
    parser.add_argument("marker_voice", nargs="?", default=None,
                        help="Edge-TTS voice for markers (optional, default depends on language: "
                             + ", ".join(f"{lang}={profile['marker_voice']}" for lang, profile in _DEFAULT_VOICE_PROFILES.items())
                             + "; see https://tts.travisvn.com for options)")

    args = parser.parse_args()
    language = args.language

    args.voice, args.marker_voice, voice_is_default, marker_voice_is_default = resolve_voices(
        language, args.voice, args.marker_voice
    )

    # Cyan text
    print(f"\033[36mVoice: {args.voice}{' (default)' if voice_is_default else ''}, "
          f"marker voice: {args.marker_voice}{' (default)' if marker_voice_is_default else ''}\033[0m")

    # Check if EPUB file exists
    if not os.path.isfile(args.epub_path):
        print(f"\033[31mError: EPUB file '{args.epub_path}' does not exist.\033[0m")
        return

    base_name = os.path.splitext(os.path.basename(args.epub_path))[0]

    chapters = epub_to_chapters(args.epub_path)

    if not chapters:
        print(f"\033[31mNo chapters found or error reading EPUB. Aborting.\033[0m")
        return

    # Add version of script as first chapter (no heading, so no title)
    if language == "de":
        version_intro = f"Version {spoken_version(language)} der Earwyrm Pipeline. Generiert mit der Stimme {args.voice} und der Markierungsstimme {args.marker_voice}."
    else:
        version_intro = f"Version {spoken_version(language)} of the Earwyrm Pipeline. Generated with voice {args.voice} and marker voice {args.marker_voice}."

    chapters.insert(0, (None, version_intro))

    metadata, cover_item = epub_metadata_for_mp3(args.epub_path, language)

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