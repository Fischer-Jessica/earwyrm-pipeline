<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Doto:wght@100..900&family=New+Rocker&family=Wavefont:wght@4..1000&display=swap" rel="stylesheet">

<p align="center">
  <img src="./assets/Earwyrm-Pipeline.png" alt="Earwyrm Pipeline Logo" width="300" />
</p>

<h1 align="center" style="font-family: New Rocker, monospace;">Earwyrm Pipeline</h1>
<h2 align="center" style="font-family: Wavefont, monospace;">Your tome hoard, synthesized.</h2>
<p align="center" style="font-family: Doto, monospace;">Your tome hoard, synthesized.</p>

<p align="center">
  <strong>Current version:</strong> <code>3.3.6</code> &nbsp;|&nbsp;
  <strong>Last updated:</strong> <code>21-10-2026</code>
</p>

---

## Table of Contents

- [Description](#description)
- [Setup Guide](#setup-guide)
  - [Installation](#installation)
- [Usage](#usage)
  - [Example](#example)
- [Notes](#notes)
- [Changelog](CHANGELOG.md) - stored in a separate file for better organization and readability

---

## Description

The **Earwyrm Pipeline** is a Python script that processes an EPUB file and uses the Microsoft Edge TTS engine to read it aloud, saving the result as a single MP3 file.

The pipeline automatically extracts book metadata from the EPUB, generates audiobook chapter markers, embeds the available metadata and cover art into the finished MP3, and supports resuming interrupted runs.

This script was developed and tested on Ubuntu 24.04, using Python 3.12 and edge-tts.

---

## Setup Guide

### Installation

1. **Download the Earwyrm Pipeline script**
   - Clone or download this repository to your local machine.

2. **Install the required system dependency**
   - Ensure that FFmpeg is installed:
     ```bash
     sudo apt install ffmpeg
     ```

3. **Install the required Python packages**
   - Ensure that Python 3.12 is installed.
   - Install the dependencies:
     ```bash
     pip install -r requirements.txt
     ```

---

## Usage

Run the script with the following command:

```bash
python main.py <epub_path> <language> [<voice> [<marker_voice>]] [--description DESCRIPTION] [--publisher PUBLISHER]
```

### Positional arguments

- `<epub_path>`: Path to the input EPUB file.
- `<language>`: Language code of the narration. Currently supported values are `en` for English and `de` for German.

### Optional arguments

- `<voice>`: Optional Edge TTS voice for the main narration.
- `<marker_voice>`: Optional Edge TTS voice for chapter markers.
- `--description DESCRIPTION`: Overrides the description extracted from the EPUB. If omitted, the description is fetched from the EPUB metadata.
- `--publisher PUBLISHER`: Overrides the publisher extracted from the EPUB. If omitted, the publisher is fetched from the EPUB metadata.

If no voices are specified, the default voice profiles for the selected language are used. They are defined in `_DEFAULT_VOICE_PROFILES` in the script. Explicitly specified voices take precedence. If only `<voice>` is supplied, the default marker voice is retained. The voices actually used are printed at startup.

See [tts.travisvn.com](https://tts.travisvn.com) for available voices.

### Example

Use the default German voices and metadata from the EPUB:

```bash
python main.py ~/Documents/Eragon.epub de
```

Specify custom voices:

```bash
python main.py ~/Documents/Eragon.epub de de-DE-ConradNeural de-DE-SeraphinaMultilingualNeural
```

Override the description and publisher:

```bash
python main.py ~/Documents/Eragon.epub de --description "A fantasy adventure" --publisher "Example Publishing"
```

Combine custom voices with metadata overrides:

```bash
python main.py ~/Documents/Eragon.epub de de-DE-ConradNeural de-DE-SeraphinaMultilingualNeural --description "A fantasy adventure" --publisher "Example Publishing"
```

In all examples, the resulting audiobook is saved as an MP3 file in `./output/`, using the input EPUB's filename.

---

## Notes

- **Metadata:** The pipeline extracts available metadata from the source EPUB, including the title, author, language, publisher, description, source, series information and custom fields. The optional `--description` and `--publisher` arguments override the corresponding EPUB values when provided. Otherwise, the values are fetched from the EPUB metadata.
- **MP3 tags:** Standard metadata is written to the corresponding MP3 tags. Series information is mapped to album and track metadata where applicable. Custom `Ordner` and `Version` fields are preserved as custom tags. Books whose series name is `Standalone` are not assigned series-part metadata.
- **Cover art:** If the source EPUB contains a cover image, it is automatically embedded as the MP3's cover art. The pipeline also generates an audiobook cover using the original cover, the Earwyrm Pipeline logo, the pipeline version and the audiobook duration.
- **Language metadata:** The generated MP3 uses the three-letter language codes expected by ID3, such as `eng` for English and `deu` for German.
- **Chapter markers:** Chapter start markers announce the chapter heading as it appears in the EPUB. Chapters without a heading do not receive a start marker. Chapter end markers announce the end of the chapter and the estimated duration of the next chapter, where applicable. The introduction is not counted as chapter 1 and has its own end marker. Markers are synthesized using the configured `marker_voice`.
- **Progress reporting:** Console output uses a consistent color scheme to distinguish progress information, successful operations, warnings and errors. Progress messages include chunk counts, completion percentages, estimated remaining time and synthesis summaries.
- **Interrupted runs:** Intermediate MP3 chunks are stored in `./output/` and are deleted only after successful final assembly. If a run is interrupted or fails, the chunks are retained so that synthesis can resume.
- **Resuming runs:** Use the same parameters and a compatible pipeline version when resuming an interrupted run. Existing chunks are reused rather than re-synthesized, so changing voices or other settings may result in inconsistent audio. Runs from before version 3.3.0 cannot be resumed with version 3.3.0 or later. Version 3.3.5 changed marker text and chunk numbering, so clear `./output/` before the first run with version 3.3.5 or later if temporary chunks from an earlier version are present.
- **Edge TTS errors:** If the Edge TTS WebSocket handshake repeatedly fails with HTTP `403` errors, the pipeline aborts after five consecutive failures and recommends updating `edge-tts` rather than retrying indefinitely. Already synthesized chunks are preserved so the run can be resumed after the issue has been resolved.
- **Supported languages:** Only `de` (German) and `en` (English) are currently supported because marker text is implemented only for these languages.
- **Output filename:** The generated MP3 uses the input EPUB's filename with the `.mp3` extension.
- **Chunk assembly errors:** If a chunk fails to load during final assembly, the pipeline reports a warning instead of silently omitting the audio. The warning identifies whether the affected chunk is a chapter-end marker.
- **Audiobook duration:** The total duration is printed automatically at the end of a run. To check the duration of an MP3 manually, use:
  ```bash
  ffprobe -i <filename>.mp3 -show_entries format=duration -v quiet -of csv="p=0" | awk '{printf "%02d:%02d:%02d\\n", $1/3600, ($1%3600)/60, $1%60}'
  ```
  Replace `<filename>` with the name of your MP3 file.
- **Replacing cover art:** To replace an MP3's cover art without re-encoding the audio or intentionally changing its other metadata:
  ```bash
  ffmpeg -i "<filename>.mp3" -i "<cover>.png" -map 0:a -map 1 -c copy -id3v2_version 3 "<filename>.tmp.mp3" && mv "<filename>.tmp.mp3" "<filename>.mp3"
  ```
  Replace `<filename>` and `<cover>` with the names of your MP3 and replacement cover image. The temporary `.tmp.mp3` file is required because FFmpeg cannot read and overwrite the same file simultaneously. The `mv` command runs only if FFmpeg succeeds, preventing a failed operation from overwriting the original file.
- **File and folder names:** Avoid spaces or special characters in file and folder names if they cause unexpected behavior or errors during processing.