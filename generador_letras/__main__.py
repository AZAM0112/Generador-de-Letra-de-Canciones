"""Línea de comandos:  python -m generador_letras cancion.mp3"""
from __future__ import annotations

import argparse
import sys

from . import generar_video_letra


def _resolucion(texto: str):
    try:
        ancho, alto = texto.lower().split("x")
        return int(ancho), int(alto)
    except ValueError:
        raise argparse.ArgumentTypeError("usa el formato ANCHOxALTO, por ejemplo 1920x1080")


def _color(texto: str):
    h = texto.lstrip("#")
    try:
        if len(h) != 6:
            raise ValueError
        return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))
    except ValueError:
        raise argparse.ArgumentTypeError("usa un color hexadecimal, por ejemplo #000000")


def main(argv=None) -> int:
    p = argparse.ArgumentParser(
        prog="generador_letras",
        description="Genera un video MP4 con la letra de una canción a partir de su audio.",
    )
    p.add_argument("audio", help="audio de la canción completa (mp3, wav, m4a, flac...)")
    p.add_argument("-t", "--titulo", help="título grande del inicio (por defecto, el nombre del archivo)")
    p.add_argument("-o", "--salida", help="ruta del MP4 (por defecto <audio>_letra.mp4)")
    p.add_argument("--letra", help="archivo .txt con la letra completa, un verso por línea (mejora mucho la precisión)")
    p.add_argument("--modelo", help="modelo Whisper: tiny, base, small, medium, large-v3 o una ruta local")
    p.add_argument("--idioma", default="es", help="idioma de la canción (por defecto: es)")
    p.add_argument("--separar-voz", action="store_true", help="aísla la voz con Demucs antes de transcribir")
    p.add_argument("--vad", action="store_true", help="filtra con detección de voz (útil si hay mucho silencio)")
    p.add_argument("--dispositivo", choices=["auto", "cpu", "cuda"], default="auto")
    p.add_argument("--solo-json", action="store_true", help="solo genera el JSON de letra para revisarlo")
    p.add_argument("--desde-json", help="usa un JSON de letra ya revisado (no transcribe)")
    p.add_argument("--resolucion", type=_resolucion, default=(1920, 1080), metavar="ANCHOxALTO")
    p.add_argument("--fps", type=int, default=30)
    p.add_argument("--fuente", help="archivo .ttf para el texto (por defecto, una fuente negrita del sistema)")
    p.add_argument("--fondo", type=_color, default=(0, 0, 0), metavar="#RRGGBB", help="color de fondo (por defecto negro)")
    a = p.parse_args(argv)

    try:
        resultado = generar_video_letra(
            a.audio, a.titulo, a.salida, letra=a.letra, modelo=a.modelo, idioma=a.idioma,
            separar_voz=a.separar_voz, desde_json=a.desde_json, solo_json=a.solo_json,
            resolucion=a.resolucion, fps=a.fps, fuente=a.fuente, fondo=a.fondo,
            dispositivo=a.dispositivo, vad=a.vad,
        )
    except (FileNotFoundError, ValueError, RuntimeError) as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
    print(resultado)
    return 0


if __name__ == "__main__":
    sys.exit(main())
