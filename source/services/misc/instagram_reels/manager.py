import json
import logging
import os
import asyncio
from typing import Set, Dict, Any, Optional
import yt_dlp
from pathlib import Path

logger = logging.getLogger(__name__)


class InstagramReelsManager:
    def __init__(
        self, context=None, config_path: str = "assets/config.json", reels_dir: str = "assets/reels"
    ):
        self.context = context
        self.config_path = config_path
        self.reels_dir = Path(reels_dir)
        self.monitoring_channels: Set[int] = set()
        self._load_config()
        self._ensure_directories()

        # Start cleanup task
        self.cleanup_task = asyncio.create_task(self._periodic_cleanup())

    def _ensure_directories(self):
        self.reels_dir.mkdir(parents=True, exist_ok=True)

    def _load_config(self):
        try:
            if os.path.exists(self.config_path):
                with open(self.config_path, "r") as f:
                    # Handle empty file
                    content = f.read().strip()
                    if not content:
                        data = {}
                    else:
                        data = json.loads(content)
                    self.monitoring_channels = set(data.get("reels_monitoring_channels", []))
            else:
                self.monitoring_channels = set()
        except Exception as e:
            logger.error(f"Failed to load config: {e}")
            self.monitoring_channels = set()

    def save_config(self):
        try:
            existing_data = {}
            if os.path.exists(self.config_path):
                try:
                    with open(self.config_path, "r") as f:
                        content = f.read().strip()
                        if content:
                            existing_data = json.loads(content)
                except json.JSONDecodeError:
                    pass  # Overwrite if corrupt

            existing_data["reels_monitoring_channels"] = list(self.monitoring_channels)

            with open(self.config_path, "w") as f:
                json.dump(existing_data, f, indent=4)
            logger.info("Saved reels monitoring config.")
        except Exception as e:
            logger.error(f"Failed to save config: {e}")

    def add_channel(self, channel_id: int):
        self.monitoring_channels.add(channel_id)
        # Requirement: "when the program closes down, make sure the config file is updated"
        # implicit: keep in memory until then, but saving periodically or on change is safer.
        # I'll stick to save on shutdown as strictly requested, but maybe add a manual save capability.

    def remove_channel(self, channel_id: int):
        if channel_id in self.monitoring_channels:
            self.monitoring_channels.remove(channel_id)

    def is_channel_monitored(self, channel_id: int) -> bool:
        return channel_id in self.monitoring_channels

    async def _periodic_cleanup(self):
        while True:
            try:
                await asyncio.sleep(3600)  # 1 hour
                self._cleanup_reels()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in cleanup task: {e}")

    def _cleanup_reels(self):
        logger.info("Cleaning up reels directory...")
        for file in self.reels_dir.glob("*"):
            try:
                if file.is_file() and file.name != ".gitkeep":
                    file.unlink()
            except Exception as e:
                logger.error(f"Failed to delete {file}: {e}")

    async def process_reel(self, reel_url: str) -> Dict[str, Any]:
        """
        Download audio and extract description from a Reel URL.
        Returns a dictionary with 'audio_path' and 'description'.
        """
        # Run in executor because yt_dlp is blocking
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self._process_reel_sync, reel_url)

    def _process_reel_sync(self, reel_url: str) -> Dict[str, Any]:
        output_template = str(self.reels_dir / "%(title)s.%(ext)s")

        ydl_opts = {
            "format": "bestaudio/best",
            "outtmpl": output_template,
            "postprocessors": [
                {
                    "key": "FFmpegExtractAudio",
                    "preferredcodec": "mp3",
                    "preferredquality": "192",
                }
            ],
            "quiet": True,
            "no_warnings": True,
        }

        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                logger.info(f"Fetching metadata for: {reel_url}...")

                # 1. Extract Metadata
                info = ydl.extract_info(reel_url, download=False)

                description = (
                    info.get("description") or info.get("caption") or "No description found."
                )

                # 2. Download Audio
                logger.info("Downloading audio...")
                error_code = ydl.download([reel_url])

                if error_code:
                    raise Exception("Download failed")

                # Find the downloaded file
                # yt_dlp might change extension
                filename = ydl.prepare_filename(info)
                # If postprocessed to mp3, the extension changes
                base_filename = os.path.splitext(filename)[0]
                mp3_path = f"{base_filename}.mp3"

                # Check actual file existence (sometimes title sanitization varies)
                # But using prepare_filename gives us the base.

                return {
                    "audio_path": mp3_path,
                    "description": description,
                    "title": info.get("title", ""),
                    "id": info.get("id", ""),
                }

        except Exception as e:
            logger.error(f"Error processing reel: {e}")
            raise e

    @property
    def services(self):
        return self.context.services_manager if self.context else None

    async def run_analysis_workflow(self, url: str, job_id_suffix: str) -> Dict[str, Any]:
        """
        Run the full analysis workflow: Download -> Transcribe -> LLM Extraction.
        """
        # 1. Download
        reel_data = await self.process_reel(url)
        audio_path = reel_data["audio_path"]
        description = reel_data["description"]

        # 2. Transcribe
        transcript_text = ""
        # Acquire GPU lock for transcription
        async with self.services.gpu_resource_manager.acquire_lock(
            "misc_chat_job", job_id=f"reels-transcribe-{job_id_suffix}"
        ):
            transcript_response = await self.services.server.whisper_server_client.inference(
                audio_path=audio_path,
                word_timestamps=False,
                temperature="0.0",
                response_format="json",
            )

            # Extract text from JSON response
            if isinstance(transcript_response, dict):
                transcript_text = transcript_response.get("text", "")
            else:
                transcript_text = str(transcript_response)

        # 3. Extraction using LangGraph Subroutine
        # Acquire GPU lock for LLM
        async with self.services.gpu_resource_manager.acquire_lock(
            "misc_chat_job", job_id=f"reels-llm-{job_id_suffix}"
        ):
            from source.services.misc.instagram_reels.subroutine import (
                InstagramReelsAnalysisSubroutine,
            )

            subroutine = InstagramReelsAnalysisSubroutine(
                ollama_request_manager=self.services.ollama_request_manager, model="ministral-3:8b"
            )

            result = await subroutine.ainvoke(
                {"description": description, "transcript": transcript_text}
            )

            return result

    async def shutdown(self):
        self.save_config()
        self.cleanup_task.cancel()
        try:
            await self.cleanup_task
        except asyncio.CancelledError:
            pass
