"""Dibujo de la letra (título, lado derecho blanco, lado izquierdo amarillo) y MP4 final."""
from __future__ import annotations

import math
import os
import re
import shutil
import subprocess
import tempfile
from functools import lru_cache
from pathlib import Path
from typing import Callable, List, Optional, Sequence, Tuple

from PIL import Image, ImageDraw, ImageFont

from .modelos import Pagina, Verso
from .segmentacion import versos_a_paginas

BLANCO = (255, 255, 255)
AMARILLO = (255, 221, 0)

ANIM_DUR = 0.5  # s que tarda una página en pasar de la derecha a la izquierda
FADE = 0.35  # s de aparición / desaparición
HOLD = 1.5  # s que se queda lo ya cantado en pantalla si no viene nada pronto
TITULO_MIN = 3.5  # s mínimos con el título solo
TITULO_MAX = 8.0
VISTA_PREVIA = 2.0  # s que se ve la primera página (blanca) antes de cantarse
FADE_TITULO = 0.6

_FUENTES_CANDIDATAS = [
    r"C:\Windows\Fonts\arialbd.ttf",
    r"C:\Windows\Fonts\segoeuib.ttf",
    r"C:\Windows\Fonts\calibrib.ttf",
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
    "/Library/Fonts/Arial Bold.ttf",
    "/System/Library/Fonts/Helvetica.ttc",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    "/usr/share/fonts/TTF/DejaVuSans-Bold.ttf",
]


# --------------------------------------------------------------------------- ffmpeg
def buscar_ffmpeg() -> str:
    ruta = shutil.which("ffmpeg")
    if ruta:
        return ruta
    try:
        import imageio_ffmpeg

        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception as e:
        raise RuntimeError(
            "No se encontró ffmpeg. Instálalo (https://ffmpeg.org) o ejecuta: pip install imageio-ffmpeg"
        ) from e


def duracion_audio(audio: Path, ffmpeg: Optional[str] = None) -> float:
    ffmpeg = ffmpeg or buscar_ffmpeg()
    r = subprocess.run(
        [ffmpeg, "-hide_banner", "-i", str(audio)],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    m = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", r.stderr)
    if not m:
        raise RuntimeError(f"No se pudo leer la duración de {audio}: {r.stderr.strip()[-300:]}")
    return int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3))


# --------------------------------------------------------------------------- texto
def _buscar_fuente(ruta: Optional[str]) -> Optional[str]:
    if ruta:
        if not Path(ruta).is_file():
            raise FileNotFoundError(f"No existe la fuente: {ruta}")
        return str(ruta)
    return next((c for c in _FUENTES_CANDIDATAS if os.path.isfile(c)), None)


@lru_cache(maxsize=128)
def _fuente(ruta: Optional[str], tam: int):
    if ruta:
        return ImageFont.truetype(ruta, tam)
    try:
        return ImageFont.load_default(tam)  # Pillow >= 10.1
    except TypeError:
        return ImageFont.load_default()


def _lineas_codicioso(palabras: Sequence[str], fuente, ancho: float) -> List[str]:
    lineas, actual = [], ""
    for p in palabras:
        prueba = f"{actual} {p}" if actual else p
        if actual and fuente.getlength(prueba) > ancho:
            lineas.append(actual)
            actual = p
        else:
            actual = prueba
    if actual:
        lineas.append(actual)
    return lineas


def _envolver(texto: str, fuente, ancho_max: float) -> List[str]:
    """Parte el texto en las líneas necesarias y las equilibra (sin 'huérfanas' cortas)."""
    palabras = texto.split()
    base = _lineas_codicioso(palabras, fuente, ancho_max)
    n = len(base)
    lo = max(fuente.getlength(p) for p in palabras) if palabras else 0
    if n <= 1 or lo >= ancho_max:
        return base
    hi = ancho_max
    for _ in range(14):
        medio = (lo + hi) / 2
        if len(_lineas_codicioso(palabras, fuente, medio)) <= n:
            hi = medio
        else:
            lo = medio
    return _lineas_codicioso(palabras, fuente, hi)


def _componer_bloque(
    textos: Sequence[str], ruta_fuente: Optional[str],
    ancho_max: float, alto_max: float, tam_max: int, tam_min: int,
) -> Image.Image:
    """Dibuja uno o varios versos centrados en una máscara 'L' (255 = tinta).

    Usa el tamaño de letra más grande (hasta `tam_max`) en que todo cabe.
    """
    tam = tam_max
    while True:
        fuente = _fuente(ruta_fuente, tam)
        por_verso = [_envolver(t, fuente, ancho_max) for t in textos]
        alto_linea, hueco = int(tam * 1.22), int(tam * 0.45)
        alto = sum(len(ls) for ls in por_verso) * alto_linea + hueco * (len(por_verso) - 1)
        ancho = max(fuente.getlength(l) for ls in por_verso for l in ls)
        if (alto <= alto_max and ancho <= ancho_max) or tam <= tam_min:
            break
        tam = max(tam_min, tam - max(2, tam // 16))
    margen = tam // 2
    mascara = Image.new("L", (int(math.ceil(ancho)) + 2 * margen, alto + 2 * margen), 0)
    d = ImageDraw.Draw(mascara)
    y = margen
    for ls in por_verso:
        for linea in ls:
            d.text(((mascara.width - fuente.getlength(linea)) / 2, y), linea, font=fuente, fill=255)
            y += alto_linea
        y += hueco
    return mascara


# --------------------------------------------------------------------------- escena
def _suave(x: float) -> float:
    x = min(1.0, max(0.0, x))
    return x * x * (3 - 2 * x)


def _mezcla(a: Tuple[int, int, int], b: Tuple[int, int, int], t: float) -> Tuple[int, int, int]:
    return tuple(int(round(a[i] + (b[i] - a[i]) * t)) for i in range(3))


class Escena:
    """Qué se ve (y dónde) en cada instante, y cómo dibujarlo."""

    def __init__(
        self, titulo: str, paginas: List[Pagina], *, ancho: int, alto: int,
        fuente: Optional[str], fondo: Tuple[int, int, int], lead_in: float,
    ):
        self.ancho, self.alto, self.fondo = ancho, alto, fondo
        ruta = _buscar_fuente(fuente)
        self.cx_izq, self.cx_der = ancho * 0.25, ancho * 0.75
        self.desplazamiento = ancho * 0.02

        self.bloque_titulo = _componer_bloque(
            [titulo], ruta, ancho * 0.85, alto * 0.6, int(alto * 0.14), int(alto * 0.05)
        )
        self.bloques = [
            _componer_bloque(
                [v.texto for v in p.versos], ruta,
                ancho / 2 * 0.90, alto * 0.80, int(alto * 0.072), int(alto * 0.036),
            )
            for p in paginas
        ]

        n = len(paginas)
        ini = [p.inicio + lead_in for p in paginas]
        fin = [p.fin + lead_in for p in paginas]
        # Con cantos seguidos y rápidos el desplazamiento se acorta para no solaparse.
        self.dur = [
            ANIM_DUR if k == 0 else min(ANIM_DUR, max(0.15, 0.7 * (ini[k] - ini[k - 1])))
            for k in range(n)
        ]
        # La página empieza a moverse un poco antes de cantarse y llega ya amarilla.
        self.t_in = [ini[k] - 0.6 * self.dur[k] for k in range(n)]
        self.titulo_fin = min(max(ini[0] - VISTA_PREVIA, TITULO_MIN), TITULO_MAX)
        # La siguiente página aparece a la derecha cuando la actual empieza a cantarse.
        self.aparece = [self.titulo_fin + 0.5] + [ini[k - 1] for k in range(1, n)]
        self.sale = [
            max(
                min(fin[k] + HOLD, self.t_in[k + 1]) if k + 1 < n else fin[k] + HOLD,
                ini[k] + 0.3,
            )
            for k in range(n)
        ]

    # -- estado -----------------------------------------------------------------
    def _estado_pagina(self, k: int, t: float):
        if t < self.aparece[k] or t >= self.sale[k] + FADE:
            return None
        entrada = _suave((t - self.aparece[k]) / FADE)
        avance = _suave((t - self.t_in[k]) / self.dur[k])
        salida = _suave((t - self.sale[k]) / FADE)
        alpha = entrada * (1 - salida)
        if alpha < 0.004:
            return None
        cx = self.cx_izq * avance + self.cx_der * (1 - avance)
        cx += self.desplazamiento * (1 - entrada) - self.desplazamiento * salida
        w, h = self.bloques[k].size
        return (
            k, int(round(cx - w / 2)), int(round((self.alto - h) / 2)),
            _mezcla(BLANCO, AMARILLO, avance), round(alpha, 3),
        )

    def operaciones(self, t: float) -> tuple:
        """Lista (hashable) de lo que se dibuja en el instante `t`."""
        ops = []
        if t < self.titulo_fin + FADE_TITULO:
            w, h = self.bloque_titulo.size
            alpha = round(1 - _suave((t - self.titulo_fin) / FADE_TITULO), 3)
            ops.append((-1, (self.ancho - w) // 2, (self.alto - h) // 2, BLANCO, alpha))
        for k in range(len(self.bloques)):
            estado = self._estado_pagina(k, t)
            if estado:
                ops.append(estado)
        return tuple(ops)

    def dibujar(self, ops: tuple) -> Image.Image:
        img = Image.new("RGB", (self.ancho, self.alto), self.fondo)
        for k, x, y, color, alpha in ops:
            mascara = self.bloque_titulo if k == -1 else self.bloques[k]
            if alpha < 0.999:
                mascara = mascara.point([int(v * alpha) for v in range(256)])
            img.paste(color, (x, y), mascara)
        return img

    def fotograma(self, t: float) -> Image.Image:
        return self.dibujar(self.operaciones(t))


# --------------------------------------------------------------------------- video
def renderizar_video(
    audio: Path, salida: Path, titulo: str, versos: List[Verso], *,
    ancho: int = 1920, alto: int = 1080, fps: int = 30,
    fuente: Optional[str] = None, fondo: Tuple[int, int, int] = (0, 0, 0),
    progreso: Callable[[str], None] = print,
) -> Path:
    """Crea el MP4: la letra animada con el audio original de la canción."""
    paginas = versos_a_paginas(versos)
    if not paginas:
        raise ValueError(
            "No hay letra que mostrar. Revisa el audio (prueba --separar-voz o un modelo "
            "mayor) o entrega la letra con --letra."
        )
    ancho, alto = ancho - ancho % 2, alto - alto % 2  # H.264 exige medidas pares
    ffmpeg = buscar_ffmpeg()
    duracion = duracion_audio(audio, ffmpeg)

    # Si la voz entra casi al inicio, se antepone un silencio para que el título se vea.
    lead_in = max(0.0, TITULO_MIN + VISTA_PREVIA - paginas[0].inicio)
    escena = Escena(
        titulo, paginas, ancho=ancho, alto=alto, fuente=fuente, fondo=fondo, lead_in=lead_in
    )
    total = int(math.ceil((lead_in + duracion) * fps))

    comando = [
        ffmpeg, "-y", "-loglevel", "error",
        "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{ancho}x{alto}", "-r", str(fps), "-i", "-",
        "-i", str(audio),
    ]
    if lead_in > 0:
        comando += ["-af", f"adelay={int(round(lead_in * 1000))}:all=1"]
    comando += [
        "-map", "0:v:0", "-map", "1:a:0",
        "-c:v", "libx264", "-preset", "medium", "-crf", "18", "-pix_fmt", "yuv420p", "-r", str(fps),
        "-c:a", "aac", "-b:a", "192k", "-shortest", "-movflags", "+faststart", str(salida),
    ]

    progreso(f"Generando video {ancho}x{alto} a {fps} fps ({len(paginas)} páginas de letra)...")
    salida = Path(salida)
    with tempfile.TemporaryFile() as errores:
        proceso = subprocess.Popen(comando, stdin=subprocess.PIPE, stderr=errores)
        try:
            clave_previa, bytes_previos, ultimo_aviso = None, b"", -1
            for i in range(total):
                ops = escena.operaciones(i / fps)
                if ops != clave_previa:  # los fotogramas quietos se reutilizan
                    bytes_previos = escena.dibujar(ops).tobytes()
                    clave_previa = ops
                proceso.stdin.write(bytes_previos)
                aviso = 100 * i // total // 10 * 10
                if aviso != ultimo_aviso:
                    ultimo_aviso = aviso
                    progreso(f"  video {aviso} %")
            proceso.stdin.close()
            proceso.wait()
        except BrokenPipeError:
            proceso.wait()
        except BaseException:
            proceso.kill()
            raise
        if proceso.returncode != 0:
            errores.seek(0)
            detalle = errores.read().decode("utf-8", errors="replace").strip()[-600:]
            salida.unlink(missing_ok=True)
            raise RuntimeError(f"ffmpeg falló (código {proceso.returncode}): {detalle}")
    progreso(f"Listo: {salida}")
    return salida
