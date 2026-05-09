"""Google Cloud Text-to-Speech helpers (optional at runtime)."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Iterable


def synthesize_to_mp3(
    text: str,
    mp3_path: str | Path,
    *,
    lang: str = "en-US",
    model: str = "en-US-Wavenet-A",
    gender: str = "FEMALE",
) -> None:
    from google.cloud import texttospeech

    if not os.environ.get("GOOGLE_APPLICATION_CREDENTIALS"):
        raise RuntimeError(
            "Set GOOGLE_APPLICATION_CREDENTIALS to a service account JSON path for voice output."
        )

    gender_map = {
        "MALE": texttospeech.SsmlVoiceGender.MALE,
        "FEMALE": texttospeech.SsmlVoiceGender.FEMALE,
        "NEUTRAL": texttospeech.SsmlVoiceGender.NEUTRAL,
        "SSML_VOICE_GENDER_UNSPECIFIED": texttospeech.SsmlVoiceGender.SSML_VOICE_GENDER_UNSPECIFIED,
    }
    g = gender_map.get(gender.upper(), texttospeech.SsmlVoiceGender.FEMALE)

    client = texttospeech.TextToSpeechClient()
    input_text = texttospeech.SynthesisInput(text=text)
    voice = texttospeech.VoiceSelectionParams(
        language_code=lang,
        name=model,
        ssml_gender=g,
    )
    audio_config = texttospeech.AudioConfig(
        audio_encoding=texttospeech.AudioEncoding.MP3
    )
    response = client.synthesize_speech(
        request={"input": input_text, "voice": voice, "audio_config": audio_config}
    )
    Path(mp3_path).write_bytes(response.audio_content)


def merge_mp3_files(input_files: Iterable[str | Path], output_path: str | Path) -> None:
    from pydub import AudioSegment

    paths = list(input_files)
    if not paths:
        return
    combined: AudioSegment | None = None
    for mp3 in paths:
        sound = AudioSegment.from_mp3(str(mp3))
        combined = sound if combined is None else combined + sound
    if combined is not None:
        combined.export(str(output_path), format="mp3")
