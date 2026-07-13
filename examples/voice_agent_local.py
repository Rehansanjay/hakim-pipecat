"""Runnable example: a local-audio Pipecat voice agent using Hakim for STT + TTS.

Mirrors Pipecat's own `examples/getting-started/06a-voice-agent-local.py`
quickstart, swapping in `HakimSTTService` / `HakimTTSService` (talking
directly to Hakim's public WebSocket API — see `../hakim_pipecat/`) in place
of the Deepgram/Cartesia services used there. Swap in your own LLM plugin;
`OpenAILLMService` here is unrelated to Hakim.

Setup:
    cd integrations/pipecat
    pip install -r requirements.txt
    cp .env.example .env   # fill in HAKIM_API_KEY, HAKIM_VOICE, OPENAI_API_KEY
    python examples/voice_agent_local.py

Talks over your machine's default microphone/speakers. See ../README.md for
the full walkthrough (auth, regions, troubleshooting).
"""

from __future__ import annotations

import asyncio
import os
import sys

from dotenv import load_dotenv
from loguru import logger

from pipecat.audio.vad.silero import SileroVADAnalyzer
from pipecat.frames.frames import LLMRunFrame
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.worker import PipelineParams, PipelineWorker
from pipecat.processors.aggregators.llm_context import LLMContext
from pipecat.processors.aggregators.llm_response_universal import (
    LLMContextAggregatorPair,
    LLMUserAggregatorParams,
)
from pipecat.services.openai.llm import OpenAILLMService
from pipecat.transports.local.audio import LocalAudioTransport, LocalAudioTransportParams
from pipecat.workers.runner import WorkerRunner

from hakim_pipecat import HakimSTTService, HakimTTSService

load_dotenv(override=True)

logger.remove(0)
logger.add(sys.stderr, level="DEBUG")


async def main():
    transport = LocalAudioTransport(
        LocalAudioTransportParams(
            audio_in_enabled=True,
            audio_out_enabled=True,
        )
    )

    stt = HakimSTTService(
        api_key=os.environ["HAKIM_API_KEY"],
        region=os.environ.get("HAKIM_REGION", "auto"),
    )

    tts = HakimTTSService(
        api_key=os.environ["HAKIM_API_KEY"],
        voice=os.environ["HAKIM_VOICE"],
        region=os.environ.get("HAKIM_REGION", "auto"),
    )

    # Swap for any LLM plugin — Hakim doesn't provide one.
    llm = OpenAILLMService(
        api_key=os.environ["OPENAI_API_KEY"],
        settings=OpenAILLMService.Settings(
            system_instruction=(
                "You are a helpful Arabic-speaking voice assistant. Your responses will be "
                "spoken aloud, so avoid emojis, bullet points, or other formatting that can't "
                "be spoken. Keep responses short and conversational."
            ),
        ),
    )

    context = LLMContext()
    user_aggregator, assistant_aggregator = LLMContextAggregatorPair(
        context,
        user_params=LLMUserAggregatorParams(vad_analyzer=SileroVADAnalyzer()),
    )

    pipeline = Pipeline(
        [
            transport.input(),  # Transport user input
            stt,
            user_aggregator,  # User responses
            llm,  # LLM
            tts,  # TTS
            transport.output(),  # Transport bot output
            assistant_aggregator,  # Assistant spoken responses
        ]
    )

    worker = PipelineWorker(
        pipeline,
        params=PipelineParams(
            enable_metrics=True,
            enable_usage_metrics=True,
        ),
    )

    context.add_message(
        {"role": "developer", "content": "Please introduce yourself to the user in Arabic."}
    )
    await worker.queue_frames([LLMRunFrame()])

    runner = WorkerRunner()

    await runner.add_workers(worker)
    await runner.run()


if __name__ == "__main__":
    asyncio.run(main())
