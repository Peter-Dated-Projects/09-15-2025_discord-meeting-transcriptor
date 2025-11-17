import asyncio
import os
import json

from source.server.common.whisper_server import construct_whisper_server_client


async def main():
    # Path to the audio file to transcribe
    audio_path = os.path.join("tests", "assets", "pokemon_song.mp3")
    output_path = os.path.join("playground", "assets", "transcript.json")

    # Create Whisper server client
    whisper_client = construct_whisper_server_client(endpoint="http://localhost:5000")
    await whisper_client.connect()

    # Send transcription request
    print(f"Transcribing: {audio_path}")
    result = await whisper_client.inference(audio_path, response_format="verbose_json")

    # Save result to JSON file
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print(f"Transcription saved to: {output_path}")

    await whisper_client.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
