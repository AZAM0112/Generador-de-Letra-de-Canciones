"""Generador de videos de letras para canciones cristianas (ministerio de alabanza).

Uso como función:

    from generador_letras import generar_video_letra
    generar_video_letra("cancion.mp3", titulo="Mi canción")
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Callable, Optional, Tuple, Union

from .modelos import Pagina, Palabra, Verso, cargar_json, guardar_json, pulso_de_json
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
    escala_letra: float = 1.0,
    dispositivo: str = "auto",
    vad: bool = False,
    ajustar_tempo: bool = True,
    bpm: Optional[float] = None,
    segunda_pasada: bool = True,
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
    escala_letra Multiplica el tamaño máximo de la letra (1.0 = grande; 0.8 = más chica). Siempre
                 se ajusta para que quepan los dos versos.
    solo_json    Solo genera el JSON de letra (para revisarlo) y no crea el video.
    ajustar_tempo Detecta el tempo y ajusta el inicio de cada verso al pulso; marca con
                 "revisar" en el JSON los versos dudosos. No se aplica con `desde_json`.
    bpm          Fuerza el tempo (si la detección automática se equivoca).
    segunda_pasada Alinea la letra real palabra por palabra (más preciso, algo más lento).

    Revisión automática (cuando no se usa `desde_json`): reconocimiento -> emparejar con la
    letra -> segunda pasada -> consistencia entre coros -> ajuste al pulso -> informe. Los
    versos dudosos quedan con "revisar" en el JSON y se genera `<audio>_revisar.html`.

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
        tempo_bpm, pulso_inicio = pulso_de_json(desde_json)
        _pagina_revision(audio, Path(desde_json), titulo, versos, tempo_bpm, pulso_inicio, progreso)
    else:
        from . import transcripcion as tr
        from .alineacion import alinear_letra, palabras_clave_para_prompt
        from .coros import armonizar_repeticiones
        from .render import buscar_ffmpeg, duracion_audio

        titulo = titulo or titulo_desde_nombre(audio)
        texto_letra = Path(letra).read_text(encoding="utf-8-sig") if letra else None
        prompt = None
        if texto_letra:
            vocabulario = palabras_clave_para_prompt(texto_letra)
            prompt = f"{tr.PROMPT_BASE} {vocabulario}" if vocabulario else None
        with tr.audio_de_voz(audio, separar_voz, progreso) as voz:
            detectadas = tr.transcribir(
                voz, modelo=modelo, idioma=idioma, dispositivo=dispositivo,
                prompt=prompt, vad=vad, progreso=progreso,
            )
            if texto_letra:
                palabras = alinear_letra(
                    texto_letra, detectadas, duracion_audio(audio, buscar_ffmpeg()), progreso
                )
                versos = palabras_a_versos(palabras, cortar_por_pausa=False)
                if segunda_pasada and tr.modelo_en_memoria() is not None:
                    from .refinar import refinar_versos

                    try:
                        refinar_versos(tr.cargar_audio(voz), versos, tr.modelo_en_memoria(), idioma, progreso)
                    except Exception as e:  # nunca deja peor el resultado de la primera pasada
                        progreso(f"AVISO: no se pudo hacer la segunda pasada ({e}); se usan los tiempos previos.")
            else:
                versos = palabras_a_versos(detectadas)
        armonizar_repeticiones(versos, progreso)
        tempo_bpm = pulso_inicio = None
        if ajustar_tempo:
            from .tempo import analizar_y_ajustar

            pulso = analizar_y_ajustar(audio, versos, bpm=bpm, progreso=progreso)
            if pulso is not None:
                tempo_bpm, pulso_inicio = round(pulso.bpm, 2), float(pulso.tiempos[0])
        guardar_json(ruta_json, titulo, versos, tempo_bpm, pulso_inicio)
        _informe(versos, ruta_json, progreso)
        _pagina_revision(audio, ruta_json, titulo, versos, tempo_bpm, pulso_inicio, progreso)
        if solo_json:
            return ruta_json

    from .render import renderizar_video

    return renderizar_video(
        audio, salida, titulo, versos, ancho=resolucion[0], alto=resolucion[1],
        fps=fps, fuente=fuente, fondo=fondo, escala_letra=escala_letra,
        tempo_bpm=tempo_bpm, progreso=progreso,
    )


def _informe(versos, ruta_json: Path, progreso: Callable[[str], None]) -> None:
    progreso(f"Letra y tiempos guardados en {ruta_json}")
    avisos = [v for v in versos if v.revisar]
    if not avisos:
        progreso(f"Revisión automática: los {len(versos)} versos pasaron todas las comprobaciones.")
        return
    progreso(
        f"Revisión automática: {len(avisos)} de {len(versos)} versos con aviso "
        f"(campo \"revisar\" en {ruta_json.name}):"
    )
    for v in avisos:
        progreso(f"  {v.inicio:7.2f} s  {v.texto[:45]!r}: {v.revisar}")


def _pagina_revision(audio, ruta_json, titulo, versos, tempo_bpm, pulso_inicio, progreso) -> None:
    from .revision import generar_pagina_revision

    try:
        ruta = generar_pagina_revision(audio, ruta_json, titulo, versos, tempo_bpm, pulso_inicio)
    except OSError as e:
        progreso(f"AVISO: no se pudo crear la página de revisión ({e}).")
        return
    if any(v.revisar for v in versos):
        progreso(f"Para revisar escuchando, abre: {ruta.name}")
