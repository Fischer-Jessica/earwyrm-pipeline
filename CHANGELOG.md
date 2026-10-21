# Changelog
All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [3.3.5] - 21-10-2026
### Added
- abort after 5 repeated `403` errors during the WebSocket handshake, with a hint to update `edge-tts` instead of retrying indefinitely; already synthesized chunks are preserved so the next run can resume

### Changed
- chapter start markers now speak the chapter heading as it appears in the EPUB instead of a running chapter number
- chapters without a heading no longer use the first line of their text as a title; they receive no start marker, and their end markers use "End of the chapter" / "Ende des Kapitels"
- chapter end markers no longer announce the next chapter's title, but still announce its estimated duration
- `epub_to_chapters()` now returns the heading separately from the text, preventing the heading from being narrated a second time after the start marker
- marker text changes affect chunk numbering, so temporary chunk files from an earlier version must be cleared from `./output/` before the first run with 3.3.5

## [3.3.4] - 21-10-2026
### Fixed
- synthesis failing with `403, message='Invalid response status'` during the WebSocket handshake to the Edge TTS endpoint, by updating `edge-tts` from 7.2.7 to 7.3.1

## [3.3.3] - 07-10-2026
### Added
- default voice profile per language (German: `de-DE-SeraphinaMultilingualNeural` / `de-DE-ConradNeural`, English: `en-GB-RyanNeural` / `en-GB-SoniaNeural`), defined in `_DEFAULT_VOICE_PROFILES`
- startup line showing which voices are used and which of them are defaults

### Changed
- `voice` and `marker_voice` are now optional command-line arguments, explicitly given voices take precedence, and giving only `voice` keeps the default marker voice

### Fixed
- MP3 language metadata now uses the three-letter codes (`eng`/`deu`) that ID3 expects instead of the full language names

## [3.3.2] - 07-10-2026
### Changed
- chapter duration estimates in the end markers now use the narration rate measured in the current run, including chunks reused from an interrupted run, instead of only the fixed words-per-minute rate
- the fixed rate (German: 157, English: 173) is still used until 2 minutes of narration have been measured
- words are counted from the cleaned text, which means exactly what is spoken

### Added
- log line before every end marker with the word count, the estimated minutes and whether the rate was measured or the default
- the measured narration rate is printed at the end of a run, so the fixed rates can be calibrated

## [3.3.1] - 07-10-2026
### Added
- progress prefix on every status line showing the finished chunks out of the total, the percentage and the estimated remaining time (ETA), chunks reused from an interrupted run are not counted in the ETA
- plan line at the start with the total number of chunks and how many of them already exist from a previous run
- summary after the synthesis (synthesized, reused, retries), assembly progress in 10% steps and the total runtime

## [3.3.0] - 07-10-2026
### Added
- spoken chapter start marker followed by 1 second of silence, the introduction gets none

### Changed
- chapter end markers now also announce the number and title of the next chapter, chapters without a heading are announced by their number only
- the start markers shift the chunk numbering, so an interrupted run of an earlier version can't be resumed with 3.3.0, clear `./output/` before the first run

## [3.2.0] - 06-10-2026
### Added
- automatic generation of audiobook covers, combining the original EPUB cover with the Earwyrm Pipeline logo, pipeline version and audiobook duration

### Fixed
- MP3 language metadata now uses the full language name (`English`/`German`) instead of the EPUB language code (`en`/`de`)

## [3.1.0] - 05-10-2026
### Changed
- chapter duration estimates use a per-language words-per-minute rate (de: 157, en: 173, the latter measured on a 29-hour English audiobook) and round to the nearest minute instead of always rounding up

## [3.0.1] - 05-10-2026
### Fixed
- a hyphen directly before a quote mark (e.g. interrupted speech like `"I-"`) is no longer read aloud as "dash" by edge-tts, since it is now mapped to a comma
- closing curly quotes (”) are now converted to straight quotes instead of being silently stripped by the character allowlist
- importing `pydub` no longer fails on Python 3.13 and newer, since the removed `audioop` module is now provided by `audioop-lts`

## [3.0.0] - 02-09-2026
### Added
- book metadata (title, author, language, series, series index, source, custom Ordner/Version fields) and cover art are embedded into the finished MP3, read from the EPUB
- audiobook duration is printed automatically at the end of a run

### Fixed
- chapter end markers announce the correct chapter number, since the version intro was previously counted as chapter 1
- clean_text no longer forces spaces around every hyphen, since that broke compound words like "E-Mail" and "Ich-Erzähler" into two spoken words
- short chunks are no longer merged into the previous one if the combined result would exceed max_length
- sentence splitting no longer cuts mid-abbreviation (e.g. "Dr.", "z. B."), based on a curated but non-exhaustive abbreviation list
- a chunk that fails to load during final MP3 assembly is now reported explicitly, including whether it was a chapter-end marker, instead of silently disappearing from the output

## [2.3.1] - 02-09-2026
### Fixed
- clean_text no longer mangles accented proper names
- en/em dashes, ellipses and semicolons map to a comma instead of being silently dropped
- euro, dollar and pound signs survive instead of being stripped
- asterisks, underscores, hashes and backticks are stripped, since edge-tts's Azure backend interprets CommonMark markdown syntax and would otherwise swallow them as formatting instead of reading them aloud

## [2.3.0] - 02-09-2026
### Fixed
- epub chapters now follow spine reading order instead of manifest order, and skip non-linear entries and the navigation document
- long sentences split across chunks no longer duplicate their tail text
- css and script tags inside chapter bodies are stripped instead of being read aloud
- nested tags in chapter headings no longer produce a missing space or duplicate text in the chapter body

## [2.2.0] - 02-09-2026
### Added
- interrupted runs can now be resumed because chunk MP3s that already exist are reused instead of being synthesised again
- chunks are written atomically through a temporary `.part` file, so an existing chunk is always complete and an interrupted run cannot leave a truncated chunk behind

### Changed
- temporary MP3 chunks are only deleted once the audiobook has been assembled successfully, instead of also being deleted when the run was interrupted or failed

## [2.1.1] - 02-09-2026
### Fixed
- fixed the MP3 export failing for audiobooks above about 25 hours of length due to the limit of the WAV format

### Changed
- output bitrate is now set to 48 kbps, matching what edge-tts delivers for individual chunks, so that the quality is kept during the final re-encoding

## [2.1.0] - 12-03-2026
### Changed
- chapter duration estimate now in hours and minutes instead of minutes only
- words-per-minute estimate corrected from 200 to 157 based on measured data

## [2.0.0] - 06-03-2026
### Added
- intro chunk now includes the voices used for narration and markers

### Changed
- replaced Picovoice Orca TTS engine with edge-tts
- intermediate audio files are now MP3 instead of WAV
- output is now written to `./output/` relative to the script
- gender argument replaced by `voice` and `marker_voice` arguments

### Removed
- removed `MODEL_PATH`, `ACCESS_KEY`, `OUTPUT_PATH` environment variables and therefore the usage of the .env file

## [1.6.0] - 28-01-2026
### Added
- added the estimated length of the next chapter, addressing issue #10
- added the version number at the start of the audiobook

## [1.5.1] - 24-09-2025
### Added
- added a subheadline
- use Google Fonts for the headlines

### Changed
- updated project logo to the version following the [Fischer-Ink styleguide](https://fischernetz.icu/fischer-ink.html)

### Removed
- removed GIMP source file `assets/logo_earwyrm-pipeline.xcf`

## [1.5.0] - 25-07-2025
### Added
- implemented structured error handling across all major functions to improve reliability and user feedback, addressing issue #9

## [1.4.2] - 25-07-2025
### Fixed
- fixed incorrect order of incrementing `global_chunk_counter` and appending to `chapter_end_chunk_indices` when saving chapter end markers, which caused the pause to be added one chunk too late  
- fixed spacing issue in `clean_text` where a dot followed by a closing parenthesis (e.g. '.)') was causing the dot to be read aloud unnaturally

## [1.4.1] - 25-07-2025
### Added
- chapter end markers ("End of chapter x" / "Ende des Kapitels x") are now spoken using the opposite voice gender to distinguish them clearly from the main narration, addressing issue #8

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