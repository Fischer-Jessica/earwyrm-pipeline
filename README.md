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
  <strong>Current version:</strong> <code>3.2.0</code> &nbsp;|&nbsp;
  <strong>Last updated:</strong> <code>06-10-2026</code>
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

This script was developed and tested on Ubuntu 24.04, using Python 3.12 and edge-tts.

---

## Setup Guide

### Installation

1. **Download the Earwyrm Pipeline script**
   - Clone or download this repository to your local machine.
2. **Install required dependencies**
   - Ensure you have Python 3.12 installed.
   - Install the required system dependency:
     ```bash
     sudo apt install ffmpeg
     ```
   - Install the required Python packages using pip:
   ```bash
     pip install -r requirements.txt
     ```

---

## Usage
Run the script with the following command:
```bash
python main.py <epub_path> <language> <voice> <marker_voice>
```
- Replace `<epub_path>` with the path to the EPUB file.
- Replace `<language>` with the desired language code (`en` for English, `de` for German).
- Replace `<voice>` with the desired Edge-TTS voice for main narration.
- Replace `<marker_voice>` with the desired Edge-TTS voice for chapter end markers.

See [tts.travisvn.com](https://tts.travisvn.com) for available voices.

## Example
```bash
python main.py ~/Documents/Eragon.epub de de-DE-ConradNeural de-DE-SeraphinaMultilingualNeural
```
This command will process the `Eragon.epub` file and read it aloud in German, saving the result as `Eragon.mp3` in `./output/`.

---

## Notes
- Intermediate `.mp3` files are created in `./output/` during processing and are deleted once the final MP3 has been assembled successfully. If the run is interrupted or fails, they are kept so that interrupted runs can be resumed by running the same command again.
- When resuming it is vital to use the same parameters as before because existing chunks are not re-synthesised. This could lead to, for example, the voice changing partway through.
- Currently only supports `de` (German) and `en` (English), as marker text is only implemented for these two languages.
- The output file will be named after the EPUB file, with the `.mp3` extension.
- If the source EPUB has title, creator, language or source metadata, these are automatically embedded into the generated MP3's tags (`title`, `artist`, `language`, `comment`). calibre-style series/series index fields are embedded too, as `album`/`track`. Any custom `Ordner`/`Version` meta fields present are embedded as custom tags as well.
- If the EPUB has a cover image, it's automatically embedded as the MP3's cover art.
- The chapter end markers are synthesized using `<marker_voice>`, which is intended to be a different voice from the main narration to make chapter boundaries more distinguishable during playback. The very first marker, after the spoken version/voice announcement, says "End of the introduction" rather than being counted as chapter 1. Every marker after that announces the correct chapter number.
- If a chunk MP3 fails to load during the final assembly step, it's now reported explicitly with a warning (instead of silently missing from the output). Including whether it was a chapter-end marker, in which case the chapter boundary itself is affected too.
- The generated MP3's length is now printed automatically at the end of a run. To check the length of any MP3 file manually, you can use the `ffprobe` command:
    ```bash
    ffprobe -i <filename>.mp3 -show_entries format=duration -v quiet -of csv="p=0" | awk '{printf "%02d:%02d:%02d\n", $1/3600, ($1%3600)/60, $1%60}'
    ```
    - Replace `<filename>` with the name of your MP3 file.
- To replace an MP3's cover art in place, without touching its other metadata:
    ```bash
    ffmpeg -i "<filename>.mp3" -i "<cover>.png" -map 0:a -map 1 -c copy -id3v2_version 3 "<filename>.tmp.mp3" && mv "<filename>.tmp.mp3" "<filename>.mp3"
    ```
    - Replace `<filename>` and `<cover>` with your MP3 and new cover image. The `.tmp.mp3` temp file is required since ffmpeg can't read and overwrite the same file at once; `mv` only runs if ffmpeg succeeded (`&&`), so a failed run never corrupts your original file.
- Avoid spaces or special characters in file or folder names as this may lead to unexpected behavior or errors during processing.