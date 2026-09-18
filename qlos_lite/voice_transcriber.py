"""Voice message transcriber using faster-whisper.

Downloads QQ voice (.silk) via URL, converts to WAV, transcribes to text.
Supports Chinese, Japanese, English (tiny multilingual model).
"""

import subprocess
import tempfile
import urllib.request
from pathlib import Path

from faster_whisper import WhisperModel

_MODEL = None


def _get_model():
    global _MODEL
    if _MODEL is None:
        _MODEL = WhisperModel("tiny", device="cpu", compute_type="int8")
    return _MODEL


def transcribe_voice(url: str) -> str | None:
    """Download voice file, convert to wav, transcribe, return text.

    Returns None on any failure so callers can fall back gracefully.
    """
    try:
        model = _get_model()
    except Exception:
        return None

    with tempfile.TemporaryDirectory() as tmpdir:
        try:
            audio_path = Path(tmpdir) / "voice.silk"
            _download(url, audio_path)

            wav_path = Path(tmpdir) / "voice.wav"
            if not _silk_to_wav(audio_path, wav_path):
                return None

            segments, _info = model.transcribe(
                str(wav_path), beam_size=5, vad_filter=True,
            )
            text = " ".join(s.text.strip() for s in segments).strip()
            return text if text else None

        except Exception:
            return None


def _download(url: str, dest: Path) -> None:
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        )
    }
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=15) as resp:
        dest.write_bytes(resp.read())


def _silk_to_wav(silk: Path, wav: Path) -> bool:
    result = subprocess.run(
        [
            "ffmpeg", "-y",
            "-i", str(silk),
            "-ar", "16000",
            "-ac", "1",
            "-c:a", "pcm_s16le",
            str(wav),
        ],
        capture_output=True, text=True, timeout=30,
    )
    return result.returncode == 0 and wav.exists() and wav.stat().st_size > 0
