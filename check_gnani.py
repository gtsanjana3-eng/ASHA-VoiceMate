"""Check the live Gnani connection from the command line.

Run (from the ASHA-VoiceMate folder):
    .\\.venv\\Scripts\\python.exe check_gnani.py

It uses the same code as the app:
  1. Gnani Timbre v3.0 TTS speaks one sentence in English, Hindi and Kannada.
  2. That audio is converted to WAV and sent to Gnani Prisma v3.0 STT.
  3. It prints what Gnani heard and Gnani's request IDs.
The audio files are saved in data/gnani_check/ so you can play them.
The API key is never printed.
"""
from __future__ import annotations

import asyncio
import io
import subprocess
import sys
import time
import wave
from pathlib import Path

from backend.config import BASE_DIR, gnani_key_present
from backend.services import gnani_stt, gnani_tts

OUT = BASE_DIR / "data" / "gnani_check"
SAMPLES = {
    "en-IN": "Beneficiary ID B two zero five, newborn visit, weight 2.8 kilo, next visit Monday.",
    "hi-IN": "खतरे का संकेत: नवजात को बुखार। तुरंत PHC रेफर करें।",
    "kn-IN": "ಅಪಾಯದ ಲಕ್ಷಣ: ಶಿಶುವಿಗೆ ಜ್ವರ. ತಕ್ಷಣ PHC ಗೆ ರೆಫರ್ ಮಾಡಿ.",
}


async def tts_wav(text: str, lang: str) -> bytes:
    """Ask Timbre for WAV directly (documented container 'wav', 16 kHz) for the STT round trip."""
    old = dict(gnani_tts.AUDIO_CONFIG)
    gnani_tts.AUDIO_CONFIG.clear()
    gnani_tts.AUDIO_CONFIG.update({"sample_rate": 16000, "container": "wav", "encoding": "linear_pcm",
                                   "num_channels": 1, "sample_width": 2})
    try:
        audio, _ = await gnani_tts.synthesize(text, lang)
    finally:
        gnani_tts.AUDIO_CONFIG.clear()
        gnani_tts.AUDIO_CONFIG.update(old)
    return audio


async def main() -> int:
    if not gnani_key_present():
        print("GNANI_API_KEY is not set in .env - add it first.")
        return 1
    OUT.mkdir(parents=True, exist_ok=True)
    print(f"TTS model: {gnani_tts.MODEL} (voice {gnani_tts.VOICE})   STT model: {gnani_stt.MODEL}\n")
    ok = True
    for lang, text in SAMPLES.items():
        print(f"[{lang}] said : {text}")
        try:
            t0 = time.perf_counter()
            audio = await tts_wav(text, lang)
            t_tts = time.perf_counter() - t0
            path = OUT / f"tts_{lang}.wav"
            path.write_bytes(audio)
            with wave.open(io.BytesIO(audio)) as w:
                secs = w.getnframes() / w.getframerate()
            print(f"        TTS  : OK  {secs:.1f}s of audio in {t_tts:.1f}s  -> {path.relative_to(BASE_DIR)}")

            t0 = time.perf_counter()
            res = await gnani_stt.transcribe(audio, "audio/wav", lang)
            t_stt = time.perf_counter() - t0
            print(f"        STT  : OK  in {t_stt:.1f}s  heard: {res['text']}")
            print(f"        Gnani request_id: {res['request_id']}  detected: {res['detected_language']}\n")
        except Exception as e:  # show the friendly Gnani error, never the key
            ok = False
            print(f"        FAILED: {e}\n")
    print("ALL CHECKS PASSED - Gnani STT and TTS are working." if ok else "Some checks failed - see messages above.")
    return 0 if ok else 2


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
