# Earwyrm Pipeline
**Current version:** `1.2.0`

---

## Description
The **Earwyrm Pipeline** is a Python script that processes an EPUB file and uses the Picovoice Orca TTS engine to read it aloud, saving the result as a single MP3 file.

This script was developed and tested on Ubuntu 24.04, using Python 3.12 and the Picovoice Orca TTS engine.

---

## Setup Guide

### Installation

1. **Create a Picovoice account**
   - Go to the [Picovoice SignUp](https://console.picovoice.ai/signup) and create a free non-commercial account (*login via Google or GitHub required*).
2. **Get your access key**
   - After logging in, navigate to the [Developer Console](https://console.picovoice.ai/) and copy your access key.
3. **Download Orca TTS model files**
   - Download the required model files for English and German (male and female) from the [Picovoice Orca GitHub repository](https://github.com/Picovoice/orca/tree/main/lib/common).
     - `orca_params_de_male.pv`, `orca_params_de_female.pv`, `orca_params_en_male.pv`, `orca_params_en_female.pv`
   - Place these files in a directory of your choice.
4. **Download the Earwyrm Pipeline script**
   - Clone or download this repository to your local machine.
5. **Install required dependencies**
   - Ensure you have Python 3.12 installed.
   - Install the required system dependency:
     ```bash
     sudo apt install ffmpeg
     ```
   - Install the required Python packages using pip:
   ```bash
     pip install -r requirements.txt
     ```
6. **Configure environment variables**
    - Rename the provided `.env.example` file to `.env`.
    - Add your Picovoice access key to the `.env` file.
    - Set the path to the folder containing the Orca TTS model files in the `.env` file.
    - Set the path to the output directory where the MP3 file will be saved in the `.env` file.

---

## Usage
Run the script with the following command:
```bash
python main.py <path_to_your_epub_file> <language_code> <voice_type>
```
- Replace `<path_to_your_epub_file>` with the path to the EPUB file.
- Replace `<language_code>` with the desired language code (`en` for English, `de` for German).
- Replace `<voice_type>` with the desired voice type (`male` for a male voice, `female` for a female voice).

## Example
```bash
python main.py ~/Documents/Eragon.epub de male
```
This command will process the `Eragon.epub` file and read it aloud in German, using a male voice, saving the result as a single MP3 file in the specified output directory as `Eragon.mp3`.

---

## Notes
- Intermediate `.wav` files are created in the output directory during processing but will be deleted after the MP3 file is generated.
- The output file will be named after the EPUB file, with the `.mp3` extension.
- To check the length of the generated MP3 file, you can use the `ffprobe` command:
   ```bash
   ffprobe -i <filename>.mp3 -show_entries format=duration -v quiet -of csv="p=0" | awk '{printf "%02d:%02d:%02d\n", $1/3600, ($1%3600)/60, $1%60}'
   ```
   - Replace `<filename>` with the name of your generated MP3 file.
- If you're using a version **prior to** commit [ebce5a1](https://github.com/Fischer-Jessica/earwyrm-pipeline/commit/ebce5a1b7ca439a2a9e0b12b0b4046da7d4158a9), make sure that the `OUTPUT_PATH` in your `.env` file includes the **full filename** (e.g., `output.wav`), as shown in the `.env.example` file from that version.
  - This is no longer required because the `OUTPUT_PATH` now refers to a **directory**, and the MP3 filename is automatically derived from the EPUB file name.
- Avoid spaces or special characters in file or folder names as this may lead to unexpected behavior or errors during processing.

---

## Changelog
### [1.2.0] - 01-07-2025
- remove (') from the list of allowed symbols for German in the regex to prevent issues with the Picovoice Orca TTS engine, as discussed in issue #6
- add '(' and ')' to the list of allowed symbols in the regex to ensure proper pauses for them in the text, addressing issue #7
- normalize `language` and `gender` parameters to lowercase to ensure consistent handling of input
- add note to the README.md clarifying outdated `OUTPUT_PATH` behavior for versions prior to commit [ebce5a1](https://github.com/Fischer-Jessica/earwyrm-pipeline/commit/ebce5a1b7ca439a2a9e0b12b0b4046da7d4158a9)
- add note to the README.md warning against spaces or special characters in filenames and paths

### [1.1.3] - 27-06-2025
- standardize quotation marks while cleaning input text
- adapt regex per language to exclude invalid symbols
- ensure space after sentence-ending punctuation to prevent issues with the Picovoice Orca TTS engine
  - root cause of the bug reported in issue #1
- change max_length of chunks to enforce single sentence chunks to avoid weird pauses in sentences
- splitting text into individual sentences now works as expected and introduces natural pauses, addressing issue #2
- correct release date for `1.1.2` in the changelog

### [1.1.2] - 27-06-2025
- lay foundation to split text into individual sentence chunks

### [1.1.1] - 22-06-2025
- Add note about the `ffprobe` command to check the length of generated MP3 file

### [1.1.0] - 22-06-2025
- add support for choosing between male and female voices (selectable via command line argument)

### [1.0.0] - 21-06-2025
- initial release of the Earwyrm Pipeline: convert EPUB to MP3 using Picovoice Orca TTS
- support English and German (male voices only)
- use `.env` to configure model path, output path and Picovoice access key