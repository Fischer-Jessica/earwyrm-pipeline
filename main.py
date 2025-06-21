import os
import pvorca
from dotenv import load_dotenv
from ebooklib import epub, ITEM_DOCUMENT
from bs4 import BeautifulSoup
import argparse
import re
from pydub import AudioSegment

load_dotenv()

def epub_to_text(epub_path):
    book = epub.read_epub(epub_path)
    text_parts = []

    for item in book.get_items_of_type(ITEM_DOCUMENT):
        soup = BeautifulSoup(item.get_content(), 'html.parser')
        text = soup.get_text()
        text_parts.append(text)

    return '\n'.join(text_parts)


def split_text(text, max_length=300):
    sentences = re.split(r'(?<=[.!?]) +', text)
    chunks = []
    current_chunk = ""

    for sentence in sentences:
        if len(current_chunk) + len(sentence) + 1 <= max_length:
            current_chunk += " " + sentence if current_chunk else sentence
        else:
            chunks.append(current_chunk.strip())
            current_chunk = sentence
    if current_chunk:
        chunks.append(current_chunk.strip())

    return chunks

def clean_text(text):
    text = text.replace("«", '"').replace("»", '"')
    text = re.sub(r"[^a-zA-Z0-9äöüÄÖÜß.,:!?\"' \n\r\t-]", "", text)
    return text

def text_to_wav(language, text):
    model_folder = os.getenv("MODEL_PATH")
    output_dir = os.getenv("OUTPUT_PATH")
    os.makedirs(output_dir, exist_ok=True)

    if language == "de":
        model_path = os.path.join(model_folder, "orca_params_de_male.pv")
    else:
        model_path = os.path.join(model_folder, "orca_params_en_male.pv")

    cleaned_text = clean_text(text)
    chunks = split_text(cleaned_text, max_length=300)

    for i, chunk in enumerate(chunks):
        orca = pvorca.create(access_key=os.getenv("ACCESS_KEY"), model_path=model_path)
        output_file = os.path.join(output_dir, f"output_chunk_{i}.wav")
        orca.synthesize_to_file(text=chunk, output_path=output_file)
        orca.delete()
        print(f"Saved chunk {i} from {len(chunks)}")

    combined = AudioSegment.empty()
    for i in range(len(chunks)):
        wav_path = os.path.join(output_dir, f"output_chunk_{i}.wav")
        chunk_audio = AudioSegment.from_wav(wav_path)
        combined += chunk_audio

    mp3_output_path = os.path.join(output_dir, "combined_output.mp3")
    combined.export(mp3_output_path, format="mp3")
    print(f"Exported combined audio to {mp3_output_path}")

    for i in range(len(chunks)):
        os.remove(os.path.join(output_dir, f"output_chunk_{i}.wav"))

def main():
    parser = argparse.ArgumentParser(description="Convert EPUB to TTS audio")
    parser.add_argument("epub_path", help="Path to the EPUB file")
    parser.add_argument("language", choices=["de", "en"], help="Language code (de or en)")

    args = parser.parse_args()

    text = epub_to_text(args.epub_path)
    text_to_wav(args.language, text)

if __name__ == "__main__":
    main()