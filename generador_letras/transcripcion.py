"""Audio -> palabras con tiempos, usando Whisper (faster-whisper) y, opcionalmente, Demucs."""
from __future__ import annotations

import inspect
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Callable, List, Optional

from .alineacion import normalizar
from .modelos import Palabra

# Vocabulario cristiano: ayuda a Whisper a escribir bien estas palabras.
PROMPT_BASE = (
    "Alabanza cristiana en español. Jesús, Señor, Dios, Espíritu Santo, Cristo, "
    "aleluya, gloria, Rey de reyes, cruz, gracia, amor, fe, santo."
)

# Frases que Whisper inventa sobre silencios o música (se descartan).
_ALUCINACIONES = (
    "amara org",
    "subtitulos realizados",
    "subtitulado por",
    "suscribete",
    "gracias por ver",
    "no olvides suscribirte",
)


def hay_gpu() -> bool:
    try:
        import ctranslate2

        return ctranslate2.get_cuda_device_count() > 0
    except Exception:
        return False


def _es_alucinacion(texto: str) -> bool:
    limpio = " ".join(
        normalizar(t) for t in texto.replace(".", " ").replace("-", " ").split()
    ).strip()
    return any(frase in limpio for frase in _ALUCINACIONES)


def separar_voz(
    audio: Path, carpeta: Path, progreso: Callable[[str], None] = print
) -> Optional[Path]:
    """Aísla la voz con Demucs. Devuelve la ruta del WAV de voz, o None si no se pudo."""
    progreso("Aislando la voz con Demucs (puede tardar varios minutos)...")
    comando = [
        sys.executable, "-m", "demucs.separate", "-n", "htdemucs", "--two-stems", "vocals",
        "-o", str(carpeta), str(audio),
    ]
    try:
        resultado = subprocess.run(comando, capture_output=True, text=True)
    except OSError as e:
        progreso(f"AVISO: no se pudo ejecutar Demucs ({e}); se usa el audio completo.")
        return None
    voz = carpeta / "htdemucs" / audio.stem / "vocals.wav"
    if resultado.returncode != 0 or not voz.exists():
        detalle = (resultado.stderr or "").strip().splitlines()[-1:] or ["sin detalle"]
        progreso(
            "AVISO: Demucs falló o no está instalado (pip install demucs); "
            f"se usa el audio completo. Detalle: {detalle[0]}"
        )
        return None
    return voz


def transcribir(
    audio: Path,
    *,
    modelo: Optional[str] = None,
    idioma: str = "es",
    dispositivo: str = "auto",
    prompt: Optional[str] = None,
    vad: bool = False,
    progreso: Callable[[str], None] = print,
) -> List[Palabra]:
    """Transcribe `audio` y devuelve cada palabra con su inicio y fin en segundos."""
    try:
        from faster_whisper import WhisperModel
    except ImportError as e:
        raise RuntimeError(
            "Falta faster-whisper. Instálalo con:  pip install -r generador_letras/requirements.txt"
        ) from e

    gpu = hay_gpu() if dispositivo == "auto" else dispositivo == "cuda"
    modelo = modelo or ("large-v3" if gpu else "medium")
    progreso(f"Cargando modelo Whisper '{modelo}' ({'GPU' if gpu else 'CPU'})...")
    try:
        whisper = WhisperModel(
            modelo, device="cuda" if gpu else "cpu", compute_type="float16" if gpu else "int8"
        )
    except Exception as e:
        raise RuntimeError(
            f"No se pudo cargar el modelo Whisper '{modelo}': {e}\n"
            "La primera vez el modelo se descarga de internet (huggingface.co). Si no hay "
            "conexión, descárgalo antes y pasa su carpeta con --modelo RUTA."
        ) from e

    opciones = dict(
        language=idioma,
        word_timestamps=True,
        vad_filter=vad,
        beam_size=5,
        initial_prompt=prompt or PROMPT_BASE,
        # En canciones, usar el texto previo provoca bucles de repetición.
        condition_on_previous_text=False,
    )
    if "hallucination_silence_threshold" in inspect.signature(whisper.transcribe).parameters:
        opciones["hallucination_silence_threshold"] = 2.0

    segmentos, info = whisper.transcribe(str(audio), **opciones)
    progreso("Transcribiendo...")
    palabras: List[Palabra] = []
    ultimo_aviso = -1
    for segmento in segmentos:
        if info.duration:
            avance = int(100 * segmento.end / info.duration) // 10 * 10
            if avance != ultimo_aviso:
                ultimo_aviso = avance
                progreso(f"  transcripción {min(avance, 100)} %")
        if _es_alucinacion(segmento.text):
            continue
        del_segmento = [
            Palabra(w.word.strip(), float(w.start), max(float(w.end), float(w.start)))
            for w in (segmento.words or [])
            if w.word.strip()
        ]
        if del_segmento:
            del_segmento[-1].corte = True
            palabras.extend(del_segmento)
    progreso(f"Palabras detectadas: {len(palabras)}")
    return palabras


def transcribir_audio_cancion(
    audio: Path,
    *,
    separar: bool,
    **opciones,
) -> List[Palabra]:
    """Como `transcribir`, aislando antes la voz si `separar` es True."""
    progreso = opciones.get("progreso", print)
    if not separar:
        return transcribir(audio, **opciones)
    with tempfile.TemporaryDirectory(prefix="letras_demucs_") as tmp:
        voz = separar_voz(audio, Path(tmp), progreso)
        return transcribir(voz or audio, **opciones)
