"""Procesa de una vez todas las canciones de una carpeta.

Convención (todo junto en la carpeta, por defecto `canciones/`):

    Mi canción.mp3                  el audio (obligatorio)
    Mi canción.txt                  la letra completa (recomendado)
    Mi canción_letra.letra.json     lo crea el programa; si lo corriges, se usa en vez de transcribir
    Mi canción_letra.mp4            el video resultante

Para cada audio:
  * si ya existe su MP4, se salta (a menos que uses --forzar);
  * si existe el JSON, se usa (no se vuelve a transcribir);
  * si no, se transcribe usando `<nombre>.txt` como letra si existe.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import List, Optional

from . import generar_video_letra
from .alineacion import normalizar

EXTENSIONES_AUDIO = {".mp3", ".wav", ".m4a", ".flac", ".ogg", ".aac"}


def procesar_carpeta(
    carpeta,
    *,
    forzar: bool = False,
    modelo: Optional[str] = None,
    separar_voz: bool = False,
    solo_json: bool = False,
    cancion: Optional[str] = None,
    progreso=print,
) -> List[str]:
    """Procesa cada audio de la carpeta. Devuelve la lista de canciones que fallaron."""
    carpeta = Path(carpeta)
    if not carpeta.is_dir():
        raise FileNotFoundError(f"No existe la carpeta: {carpeta}")
    audios = sorted(p for p in carpeta.iterdir() if p.suffix.lower() in EXTENSIONES_AUDIO)
    if cancion:
        buscado = normalizar(cancion)
        audios = [a for a in audios if buscado in normalizar(a.stem)]
        if not audios:
            progreso(f"No hay ningún audio cuyo nombre contenga '{cancion}' en {carpeta}.")
            return [cancion]
    if not audios:
        progreso(f"No hay audios ({', '.join(sorted(EXTENSIONES_AUDIO))}) en {carpeta}.")
        return []

    fallidas: List[str] = []
    for audio in audios:
        mp4 = audio.with_name(audio.stem + "_letra.mp4")
        ruta_json = audio.with_name(audio.stem + "_letra.letra.json")
        txt = audio.with_suffix(".txt")
        if mp4.exists() and not forzar and not solo_json:
            progreso(f"[omitida] {audio.name}: ya tiene video (usa --forzar para rehacerlo).")
            continue
        progreso(f"=== {audio.name} ===")
        try:
            if ruta_json.exists():
                progreso(f"Usando la letra revisada: {ruta_json.name}")
                generar_video_letra(audio, desde_json=ruta_json, solo_json=solo_json, progreso=progreso)
            else:
                if not txt.exists():
                    progreso(f"AVISO: no hay {txt.name}; la letra se tomará solo del reconocimiento de voz.")
                generar_video_letra(
                    audio, letra=txt if txt.exists() else None, modelo=modelo,
                    separar_voz=separar_voz, solo_json=solo_json, progreso=progreso,
                )
        except Exception as e:  # una canción con problemas no detiene a las demás
            progreso(f"ERROR en {audio.name}: {e}")
            fallidas.append(audio.name)
    return fallidas


def main(argv=None) -> int:
    p = argparse.ArgumentParser(
        prog="generar", description="Genera los videos de todas las canciones de una carpeta."
    )
    p.add_argument("carpeta", nargs="?", default="canciones", help="carpeta con los audios (por defecto: canciones)")
    p.add_argument("--cancion", help="procesa solo la canción cuyo nombre contenga este texto (sin importar tildes ni mayúsculas)")
    p.add_argument("--forzar", action="store_true", help="rehace los videos aunque ya existan")
    p.add_argument("--modelo", help="modelo Whisper: small, medium, large-v3...")
    p.add_argument("--separar-voz", action="store_true", help="aísla la voz con Demucs")
    p.add_argument("--solo-json", action="store_true", help="solo crea los JSON de letra para revisarlos")
    a = p.parse_args(argv)
    try:
        fallidas = procesar_carpeta(
            a.carpeta, forzar=a.forzar, modelo=a.modelo, separar_voz=a.separar_voz, solo_json=a.solo_json, cancion=a.cancion
        )
    except FileNotFoundError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
    if fallidas:
        print(f"Con errores: {', '.join(fallidas)}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
