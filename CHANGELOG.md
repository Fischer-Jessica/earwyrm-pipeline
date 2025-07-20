# Changelog
All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.4.0] - 20-07-2025
### Added
- introduced colored `print()` output to improve visibility and readability in the console
- when the application is stopped manually and restarted already generated WAV files are reused instead of being regenerated

### Changed
- enhanced progress messages for clarity and consistency across the application
- progress counters now start at 1 instead of 0 for better user-friendliness
- clarify WAV file deletion conditions in README.md

### Fixed
- corrected the total chunk count display in messages like "Saved chunk x of y for chapter i"
- fixed a bug that caused duplicated text chunks during the EPUB parsing phase, resulting in repeated audio output

## [1.3.1] - 18-07-2025
### Changed
- enhance layer structure of the logo file for better maintainability and export clarity

## [1.3.0] - 17-07-2025
### Added
- add short pauses between chapters to provide natural breakpoints in the generated audio file, addressing issue #3
- add automatic cleanup of intermediate WAV files even in case of unexpected errors

### Changed
- WAV files are now named based on the input EPUB filename to reduce the risk of overwriting files and to improve traceability
- update the README.md table of contents to clarify that the changelog is stored in a separate file
- rename variables and functions to improve code readability and maintainability
- enhance `print()` statements to provide more informative messages during execution

## [1.2.3] - 04-07-2025
### Changed
- move changelog to a separate file for better organization and readability

### Fixed
- fix a misplaced pixel in the logo image

## [1.2.2] - 03-07-2025
### Fixed
- fix logo display issues caused by GitHub’s Markdown renderer limitations

## [1.2.1] - 03-07-2025
### Added
- add logo as requested in issue #5
- add table of contents to the README.md for easier navigation

### Fixed
- fix inconsistencies in the changelog
- fix usage example flags in README.md to match actual command line arguments

## [1.2.0] - 01-07-2025
### Added
- add '(' and ')' to the list of allowed symbols in the regex to ensure proper pauses for them in the text, addressing issue #7
- add note to the README.md clarifying outdated `OUTPUT_PATH` behavior for versions prior to commit [ebce5a1](https://github.com/Fischer-Jessica/earwyrm-pipeline/commit/ebce5a1b7ca439a2a9e0b12b0b4046da7d4158a9)
- add note to the README.md warning against spaces or special characters in filenames and paths

### Changed
- normalize `language` and `gender` parameters to lowercase to ensure consistent handling of input

### Removed
- remove (') from the list of allowed symbols for German in the regex to prevent issues with the Picovoice Orca TTS engine, as discussed in issue #6

## [1.1.3] - 27-06-2025
### Added
- splitting text into individual sentences now works as expected and introduces natural pauses, addressing issue #2

### Changed
- standardize quotation marks while cleaning input text
- adapt regex per language to exclude invalid symbols

### Fixed
- ensure space after sentence-ending punctuation to prevent issues with the Picovoice Orca TTS engine
  - root cause of the bug reported in issue #1
- change max_length of chunks to enforce single sentence chunks to avoid weird pauses in sentences
- set correct release date for `1.1.2` in the changelog

## [1.1.2] - 27-06-2025
### Added
- lay foundation to split text into individual sentence chunks

## [1.1.1] - 22-06-2025
### Added
- add note about the `ffprobe` command to check the length of generated MP3 file

## [1.1.0] - 22-06-2025
### Added
- add support for choosing between male and female voices (selectable via command line argument)

## [1.0.0] - 21-06-2025
### Added
- initial release of the Earwyrm Pipeline: convert EPUB to MP3 using Picovoice Orca TTS
- support English and German (male voices only)
- use `.env` to configure model path, output path and Picovoice access key