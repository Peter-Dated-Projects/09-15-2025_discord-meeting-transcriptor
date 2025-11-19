# load env
import os
from dotenv import load_dotenv
import json
import glob

load_dotenv("../../.env.local")


# open up all files in the transcripts directory
TRANSCRIPTS_DIR = "assets/data/transcriptions/compilations/storage"

if not TRANSCRIPTS_DIR:
    print("TRANSCRIPTS_STORAGE_PATH not set")
    exit(1)

# Find all JSON files in the directory
transcript_files = glob.glob(os.path.join(TRANSCRIPTS_DIR, "*.json"))

for file_path in transcript_files:
    print(f"Processing {file_path}")
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        # Add summary_layers and summary if not present
        if "summary_layers" not in data:
            data["summary_layers"] = {}
        if "summary" not in data:
            data["summary"] = ""

        # Save back
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

        print(f"Updated {file_path}")
    except Exception as e:
        print(f"Error processing {file_path}: {e}")

print("Done")
