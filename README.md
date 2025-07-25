<p align="center">
  <img src="./assets/logo_earwyrm-pipeline.png" alt="Earwyrm Pipeline Logo" width="200" />
</p>

<h1 align="center">Earwyrm Pipeline</h1>

<p align="center">
  <strong>Current version:</strong> <code>1.5.0</code> &nbsp;|&nbsp;
  <strong>Last updated:</strong> <code>25-07-2025</code>
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
python main.py <epub_path> <language> <gender>
```
- Replace `<epub_path>` with the path to the EPUB file.
- Replace `<language>` with the desired language code (`en` for English, `de` for German).
- Replace `<gender>` with the desired voice type (`male` for a male voice, `female` for a female voice).

## Example
```bash
python main.py ~/Documents/Eragon.epub de male
```
This command will process the `Eragon.epub` file and read it aloud in German, using a male voice, saving the result as a single MP3 file in the specified output directory as `Eragon.mp3`.

---

## Notes
- Intermediate `.wav` files are created in the output directory during processing but will be deleted after the MP3 file is generated or when an error occurs.
- The output file will be named after the EPUB file, with the `.mp3` extension.
- To check the length of the generated MP3 file, you can use the `ffprobe` command:
   ```bash
   ffprobe -i <filename>.mp3 -show_entries format=duration -v quiet -of csv="p=0" | awk '{printf "%02d:%02d:%02d\n", $1/3600, ($1%3600)/60, $1%60}'
   ```
   - Replace `<filename>` with the name of your generated MP3 file.
- If you're using a version **prior to** commit [ebce5a1](https://github.com/Fischer-Jessica/earwyrm-pipeline/commit/ebce5a1b7ca439a2a9e0b12b0b4046da7d4158a9), make sure that the `OUTPUT_PATH` in your `.env` file includes the **full filename** (e.g., `output.wav`), as shown in the `.env.example` file from that version.
  - This is no longer required because the `OUTPUT_PATH` now refers to a **directory**, and the MP3 filename is automatically derived from the EPUB file name.
- Avoid spaces or special characters in file or folder names as this may lead to unexpected behavior or errors during processing.
- The chapter end markers are synthesized using the voice of the opposite gender to the main narration voice. This is intentional and serves to make chapter boundaries more distinguishable during playback.