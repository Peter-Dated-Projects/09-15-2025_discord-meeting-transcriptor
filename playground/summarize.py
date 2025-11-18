import asyncio
import os
import json
import requests
from datetime import datetime
from typing import List, Dict, Any
from dotenv import load_dotenv

from source.server.common.whisper_server import construct_whisper_server_client

load_dotenv(".env.local")


async def main():
    meeting_id = "example_meeting_001"
    user_ids = ["user_123"]  # Add more user IDs as needed

    # Configuration
    max_words_per_request = 2000

    # Path to the audio file to transcribe
    audio_path = os.path.join("playground", "assets", "podcast.mp3")
    transcript_path = os.path.join("playground", "assets", "transcript.json")
    compiled_path = os.path.join("playground", "assets", f"transcript_{meeting_id}.json")
    raw_text_path = os.path.join("playground", "assets", f"transcript_{meeting_id}_raw.txt")

    # # phase 1 -- Create Whisper server client
    # whisper_client = construct_whisper_server_client(endpoint="http://localhost:5000")
    # await whisper_client.connect()

    # # Send transcription request
    # print(f"Transcribing: {audio_path}")
    # result = await whisper_client.inference(audio_path, response_format="verbose_json")

    # # Save result to JSON file
    # os.makedirs(os.path.dirname(transcript_path), exist_ok=True)
    # with open(transcript_path, "w", encoding="utf-8") as f:
    #     json.dump(result, f, ensure_ascii=False, indent=2)
    # print(f"Transcription saved to: {transcript_path}")

    # await whisper_client.disconnect()

    # # Phase 2 -- use the compilation tool to build a flow for the transcript
    # print("Starting transcription compilation...")

    # # Example: Compile multiple transcription files
    # # In a real scenario, these would be different user transcriptions for the same meeting
    # transcript_files = [
    #     transcript_path,
    # ]

    # all_segments = []
    # for t_file in transcript_files:
    #     with open(t_file, "r") as f:
    #         segment_data = json.load(f)

    #     segments = segment_data["segments"]
    #     for s in segments:
    #         # normalize data
    #         n_result = {
    #             "timestamp": {
    #                 "start_time": s.get("start", 0),
    #                 "end_time": s.get("end", 0),
    #             },
    #             "speaker": {
    #                 "user_id": segment_data.get("user_id", "unknown_user"),
    #                 "user_transcription_file": t_file,
    #             },
    #             "content": s["text"],
    #         }
    #         all_segments.append(n_result)

    # # sort segments
    # all_segments.sort(key=lambda x: x["timestamp"]["start_time"])

    # # create new json object wiht compiled data
    # compilation_result = {
    #     "meeting_id": meeting_id,
    #     "compiled_at": datetime.utcnow().isoformat() + "Z",
    #     "transcript_count": len(transcript_files),
    #     "user_ids": list(set(m["speaker"]["user_id"] for m in all_segments)),
    #     "segment_count": len(all_segments),
    #     "segments": all_segments,
    # }

    # # save data into file
    # with open(compiled_path, "w", encoding="utf-8") as f:
    #     json.dump(compilation_result, f, ensure_ascii=False, indent=2)
    # print(f"Compiled transcription saved to: {compiled_path}")

    # # phase 3 -- create summary of the transcription with ollama
    # print("Creating raw text of transcription for summarization...")

    # with open(compiled_path, "r", encoding="utf-8") as f:
    #     compilation_data = json.load(f)
    # raw = "\n".join([segment["content"] for segment in compilation_data.get("segments", [])])
    # print(f"Raw transcription text length: {len(raw)} characters")

    # with open(raw_text_path, "w", encoding="utf-8") as f:
    #     f.write(raw)
    # print(f"Raw transcription text saved to: {raw_text_path}")

    # Phase 4 -- recursive summarization with ollama
    print("\n" + "=" * 60)
    print("PHASE 4: RECURSIVE SUMMARIZATION")
    print("=" * 60)

    # Setup
    OLLAMA_HOST = os.getenv("OLLAMA_HOST", "localhost")
    OLLAMA_PORT = os.getenv("OLLAMA_PORT", "11434")
    OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "gpt-oss:20b")
    BASE_URL = f"http://{OLLAMA_HOST}:{OLLAMA_PORT}"

    summaries_dir = os.path.join("playground", "assets", "summaries")
    os.makedirs(summaries_dir, exist_ok=True)

    # Load raw text
    print(f"Loading raw text from: {raw_text_path}")
    with open(raw_text_path, "r", encoding="utf-8") as f:
        text = f.read()

    all_summaries = []  # Track all summaries at each level
    level = 0

    # Recursive summarization loop
    while True:
        word_count = len(text.split())
        print(f"\n--- Level {level} ---")
        print(f"Current word count: {word_count}")

        # Base case: already under max_words_per_request words
        if word_count <= max_words_per_request:
            print(f"✅ Under {max_words_per_request} words! Done.")
            final_summary = text
            break

        # Split into max_words_per_request word chunks
        words = text.split()
        chunks = []
        for i in range(0, len(words), max_words_per_request):
            chunk = " ".join(words[i : i + max_words_per_request])
            chunks.append(chunk)

        print(f"Split into {len(chunks)} chunks")

        # Summarize each chunk
        level_summaries = []
        for i, chunk in enumerate(chunks):
            print(f"\nSummarizing chunk {i+1}/{len(chunks)} ({len(chunk.split())} words)...")

            # Choose system message and user content based on level
            if level == 0:
                system_message = "<|start|>system<|message|>You are an expert at summarizing meeting transcripts. Extract key topics, decisions, and action items concisely.<|end|>"
                user_content = f"""
<|start|>developer<|message|>Summarize this meeting transcript section (part {i+1} of {len(chunks)}). 
Provide a 200-500 word summary covering: 
- Main topics discussed
- Key points and decisions for each topic discussed
- Important action items
- Notable speakers/perspectives
<|end|>

<|start|>user<|message|>
Transcript:
{chunk}

<|end|><|start|>assistant
"""
            else:
                system_message = """
<|start|>system<|message|>
You are an expert at summarizing summaries of meeting transcripts. Create a concise overview that preserves the most important information from multiple summaries.
<|end|>
"""
                user_content = f"""
<|start|>developer<|message|>
Create a consolidated summary from this summary section (part {i+1} of {len(chunks)}).
Provide a 200-500 word overview that combines and preserves the most important information:
<|end|>

<|start|>user<|message|>
Summary section:
{chunk}
<|end|><|start|>assistant
"""

            # Call ollama
            payload = {
                "model": OLLAMA_MODEL,
                "messages": [
                    {
                        "role": "system",
                        "content": system_message,
                    },
                    {
                        "role": "user",
                        "content": user_content,
                    },
                ],
                "stream": False,
            }

            response = requests.post(f"{BASE_URL}/api/chat", json=payload, timeout=120)
            result = response.json()
            summary = result["message"]["content"]

            print(f"Generated summary: {len(summary.split())} words")
            level_summaries.append(summary)

        # Save this level's summaries
        level_file = os.path.join(summaries_dir, f"{meeting_id}_level_{level}.json")
        with open(level_file, "w", encoding="utf-8") as f:
            json.dump(
                {
                    "level": level,
                    "num_chunks": len(chunks),
                    "summaries": level_summaries,
                    "total_words": sum(len(s.split()) for s in level_summaries),
                },
                f,
                indent=2,
            )
        print(f"Saved level {level} summaries to: {level_file}")

        all_summaries.append(level_summaries)

        # Combine summaries for next iteration
        text = "\n\n".join(level_summaries)
        level += 1

    # Save final summary
    final_path = os.path.join(summaries_dir, f"{meeting_id}_final_summary.txt")
    with open(final_path, "w", encoding="utf-8") as f:
        f.write(f"Meeting: {meeting_id}\n")
        f.write(f"Generated: {datetime.utcnow().isoformat()}Z\n")
        f.write(f"Levels processed: {level}\n")
        f.write(f"Final word count: {len(final_summary.split())}\n")
        f.write("\n" + "=" * 60 + "\n")
        f.write(final_summary)

    print(f"\n✅ Final summary saved to: {final_path}")
    print(f"Total levels: {level}")
    print(f"Final word count: {len(final_summary.split())}")


if __name__ == "__main__":
    asyncio.run(main())
