import os
import pvorca
from dotenv import load_dotenv

load_dotenv()

language = "en"
text = "This is a test to find out how the Orca TTS sounds in different languages."

if language == "de":
    model_path = os.getenv("MODEL_PATH") + "orca_params_de_male.pv"
else:
    model_path = os.getenv("MODEL_PATH") + "orca_params_en_male.pv"

orca = pvorca.create(access_key=os.getenv("ACCESS_KEY"), model_path=model_path)

orca.synthesize_to_file(text=text, output_path=os.getenv("OUTPUT_PATH"))

orca.delete()