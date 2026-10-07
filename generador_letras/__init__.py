"""Generador de videos de letras para canciones cristianas (ministerio de alabanza).

Uso como función:

    from generador_letras import generar_video_letra
    generar_video_letra("cancion.mp3", titulo="Mi canción")
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Callable, Optional, Tuple, Union

from .modelos import Pagina, Palabra, Verso, cargar_json, guardar_json
from .segmentacion import palabras_a_versos, versos_a_paginas

__all__ = [
    "generar_video_letra", "titulo_desde_nombre", "Verso", "Pagina", "Palabra",
    "palabras_a_versos", "versos_a_paginas", "cargar_json", "guardar_json",
]


def titulo_desde_nombre(audio: Union[str, Path]) -> str:
    """'01_cuan_grande_es_dios.mp3' -> 'Cuan Grande Es Dios'."""
    nombre = re.sub(r"^\d+[\s._-]+", "", Path(audio).stem)
    nombre = " ".join(nombre.replace("_", " ").split())
    return nombre.title() if nombre == nombre.lower() else nombre


def generar_video_letra(
    audio: Union[str, Path],
    titulo: Optional[str] = None,
    salida: Optional[Union[str, Path]] = None,
    *,
    letra: Optional[Union[str, Path]] = None,
    modelo: Optional[str] = None,
    idioma: str = "es",
    separar_voz: bool = False,
    desde_json: Optional[Union[str, Path]] = None,
    solo_json: bool = False,
    resolucion: Tuple[int, int] = (1920, 1080),
    fps: int = 30,
    fuente: Optional[str] = None,
    fondo: Tuple[int, int, int] = (0, 0, 0),
    dispositivo: str = "auto",
    vad: bool = False,
    progreso: Callable[[str], None] = print,
) -> Path:
    """Convierte el audio completo de una canción en un MP4 con la letra animada.

    Parámetros
    ----------
    audio        Archivo de audio de la canción completa (mp3, wav, m4a, flac...).
    titulo       Título que se muestra grande al inicio (por defecto, el nombre del archivo).
    salida       Ruta del MP4 (por defecto `<audio>_letra.mp4` junto al audio).
    letra        Archivo .txt con la letra completa, un verso por línea. Es la opción que
                 mejor funciona: Whisper solo se usa para sincronizar los tiempos.
    modelo       Modelo Whisper ('tiny', 'small', 'medium', 'large-v3' o ruta local).
    separar_voz  Aísla la voz con Demucs antes de transcribir (mejora mucho con banda).
    desde_json   Usa un JSON de letra ya revisado y se salta la transcripción.
    solo_json    Solo genera el JSON de letra (para revisarlo) y no crea el video.

    Devuelve la ruta del MP4 (o del JSON si `solo_json=True`).
    """
    audio = Path(audio)
    if not audio.is_file():
        raise FileNotFoundError(f"No existe el audio: {audio}")
    salida = Path(salida) if salida else audio.with_name(audio.stem + "_letra.mp4")
    ruta_json = salida.with_suffix(".letra.json")

    if desde_json:
        titulo_json, versos = cargar_json(desde_json)
        titulo = titulo or titulo_json or titulo_desde_nombre(audio)
    else:
        from .alineacion import alinear_letra, palabras_clave_para_prompt
        from .render import buscar_ffmpeg, duracion_audio
        from .transcripcion import PROMPT_BASE, transcribir_audio_cancion

        titulo = titulo or titulo_desde_nombre(audio)
        texto_letra = Path(letra).read_text(encoding="utf-8-sig") if letra else None
        prompt = None
        if texto_letra:
            vocabulario = palabras_clave_para_prompt(texto_letra)
            prompt = f"{PROMPT_BASE} {vocabulario}" if vocabulario else None
        detectadas = transcribir_audio_cancion(
            audio, separar=separar_voz, modelo=modelo, idioma=idioma,
            dispositivo=dispositivo, prompt=prompt, vad=vad, progreso=progreso,
        )
        if texto_letra:
            palabras = alinear_letra(
                texto_letra, detectadas, duracion_audio(audio, buscar_ffmpeg()), progreso
            )
            versos = palabras_a_versos(palabras, cortar_por_pausa=False)
        else:
            versos = palabras_a_versos(detectadas)
        guardar_json(ruta_json, titulo, versos)
        progreso(f"Letra y tiempos guardados en {ruta_json} (puedes corregirlos y usar --desde-json).")
        if solo_json:
            return ruta_json

    from .render import renderizar_video

    return renderizar_video(
        audio, salida, titulo, versos, ancho=resolucion[0], alto=resolucion[1],
        fps=fps, fuente=fuente, fondo=fondo, progreso=progreso,
    )
