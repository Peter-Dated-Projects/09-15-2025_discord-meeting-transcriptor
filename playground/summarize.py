import asyncio
import os
import json
from datetime import datetime
from typing import List, Dict, Any

from source.server.common.whisper_server import construct_whisper_server_client


async def main():
    meeting_id = "example_meeting_001"
    user_ids = ["user_123"]  # Add more user IDs as needed

    # Path to the audio file to transcribe
    audio_path = os.path.join("playground", "assets", "podcast.mp3")
    transcript_path = os.path.join("playground", "assets", "transcript.json")
    compiled_path = os.path.join("playground", "assets", f"transcript_{meeting_id}.json")

    # Create Whisper server client
    whisper_client = construct_whisper_server_client(endpoint="http://localhost:5000")
    await whisper_client.connect()

    # Send transcription request
    print(f"Transcribing: {audio_path}")
    result = await whisper_client.inference(audio_path, response_format="verbose_json")

    # Save result to JSON file
    os.makedirs(os.path.dirname(transcript_path), exist_ok=True)
    with open(transcript_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print(f"Transcription saved to: {transcript_path}")

    await whisper_client.disconnect()

    # Phase 2 -- use the compilation tool to build a flow for the transcript
    print("Starting transcription compilation...")

    # Example: Compile multiple transcription files
    # In a real scenario, these would be different user transcriptions for the same meeting
    transcript_files = [
        transcript_path,
    ]

    all_segments = []
    for t_file in transcript_files:
        with open(t_file, "r") as f:
            segment_data = json.load(f)

        segments = segment_data["segments"]
        for s in segments:
            # normalize data
            n_result = {
                "timestamp": {
                    "start_time": s.get("start", 0),
                    "end_time": s.get("end", 0),
                },
                "speaker": {
                    "user_id": segment_data.get("user_id", "unknown_user"),
                    "user_transcription_file": t_file,
                },
                "content": s["text"],
            }
            all_segments.append(n_result)

    # sort segments
    all_segments.sort(key=lambda x: x["timestamp"]["start_time"])

    # create new json object wiht compiled data
    compilation_result = {
        "meeting_id": meeting_id,
        "compiled_at": datetime.utcnow().isoformat() + "Z",
        "transcript_count": len(transcript_files),
        "user_ids": list(set(m["speaker"]["user_id"] for m in all_segments)),
        "segment_count": len(all_segments),
        "segments": all_segments,
    }

    # save data into file
    with open(compiled_path, "w", encoding="utf-8") as f:
        json.dump(compilation_result, f, ensure_ascii=False, indent=2)
    print(f"Compiled transcription saved to: {compiled_path}")


if __name__ == "__main__":
    asyncio.run(main())
