import pvorca
from dotenv import load_dotenv
import os

load_dotenv()

access_key = os.getenv("ACCESS_KEY")
output_path = os.getenv("OUTPUT_PATH")

text = "This is a test to find out how the Orca TTS sounds and how it works."

orca = pvorca.create(access_key=access_key)

orca.synthesize_to_file(text=text, output_path=output_path)

orca.delete()