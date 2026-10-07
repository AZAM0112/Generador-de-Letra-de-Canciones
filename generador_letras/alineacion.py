"""Alineación de una letra conocida con las palabras que Whisper detectó en el audio.

Whisper rinde mucho mejor sincronizando una letra ya escrita que adivinándola a
partir de una canción con instrumentos. Aquí se usa su transcripción (aunque
tenga errores) solo como "mapa de tiempos": cada palabra de la letra real toma el
tiempo de la palabra detectada que más se le parece, y las que no encuentran
pareja se reparten el tiempo que hay entre sus vecinas.
"""
from __future__ import annotations

import re
import unicodedata
from difflib import SequenceMatcher
from typing import Callable, Dict, List, Optional, Tuple

from .modelos import Palabra

_MARCADOR_SECCION = re.compile(r"^\s*[\[\(].*[\]\)]\s*$")  # [Coro], (Verso 1), ...
_PUNTAJE_GAP = -0.8
_SIMILITUD_MINIMA = 0.7
_DURACION_PALABRA_ESTIMADA = 0.35


def normalizar(texto: str) -> str:
    """Minúsculas, sin tildes ni puntuación: 'Jesús,' -> 'jesus'."""
    s = unicodedata.normalize("NFD", texto.lower())
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    return "".join(c for c in s if c.isalnum())


def leer_letra(texto: str) -> List[Palabra]:
    """Convierte la letra escrita por el usuario en palabras (sin tiempos todavía).

    Cada línea de texto es un verso; una línea en blanco o un marcador como
    `[Coro]` abre una estrofa nueva (página nueva en pantalla).
    """
    palabras: List[Palabra] = []
    nueva = False
    for linea in texto.splitlines():
        if not linea.strip() or _MARCADOR_SECCION.match(linea):
            nueva = bool(palabras)
            continue
        tokens = [t for t in linea.split() if normalizar(t)]
        for i, token in enumerate(tokens):
            palabras.append(
                Palabra(token, 0.0, 0.0, corte=i == len(tokens) - 1, pagina_nueva=nueva and i == 0)
            )
        if tokens:
            nueva = False
    return palabras


def palabras_clave_para_prompt(texto_letra: str, max_chars: int = 400) -> str:
    """Vocabulario único de la letra (sin su orden) para orientar a Whisper."""
    vistas, salida, largo = set(), [], 0
    for token in texto_letra.split():
        limpia = token.strip(",.;:¡!¿?()[]\"'")
        clave = normalizar(limpia)
        if len(clave) < 4 or clave in vistas:
            continue
        vistas.add(clave)
        salida.append(limpia)
        largo += len(limpia) + 2
        if largo >= max_chars:
            break
    return ", ".join(salida)


def _puntaje(cache: Dict[Tuple[str, str], float], x: str, y: str) -> float:
    if x == y:
        return 2.0
    clave = (x, y)
    if clave not in cache:
        r = SequenceMatcher(None, x, y).ratio() if x and y else 0.0
        cache[clave] = 2.0 * r if r >= _SIMILITUD_MINIMA else -1.0
    return cache[clave]


def _emparejar(a: List[str], b: List[str]) -> List[Tuple[int, int]]:
    """Needleman-Wunsch: pares (i, j) de palabras parecidas en el mismo orden."""
    n, m = len(a), len(b)
    cache: Dict[Tuple[str, str], float] = {}
    S = [[0.0] * (m + 1) for _ in range(n + 1)]
    for i in range(1, n + 1):
        S[i][0] = i * _PUNTAJE_GAP
    for j in range(1, m + 1):
        S[0][j] = j * _PUNTAJE_GAP
    for i in range(1, n + 1):
        ai, fila, previa = a[i - 1], S[i], S[i - 1]
        for j in range(1, m + 1):
            fila[j] = max(
                previa[j - 1] + _puntaje(cache, ai, b[j - 1]),
                previa[j] + _PUNTAJE_GAP,
                fila[j - 1] + _PUNTAJE_GAP,
            )
    pares: List[Tuple[int, int]] = []
    i, j = n, m
    while i > 0 and j > 0:
        s = _puntaje(cache, a[i - 1], b[j - 1])
        if abs(S[i][j] - (S[i - 1][j - 1] + s)) < 1e-9:
            if s > 0:
                pares.append((i - 1, j - 1))
            i, j = i - 1, j - 1
        elif abs(S[i][j] - (S[i - 1][j] + _PUNTAJE_GAP)) < 1e-9:
            i -= 1
        else:
            j -= 1
    pares.reverse()
    return pares


def alinear_letra(
    texto_letra: str,
    detectadas: List[Palabra],
    duracion_audio: Optional[float] = None,
    progreso: Callable[[str], None] = print,
) -> List[Palabra]:
    """Devuelve las palabras de `texto_letra` con tiempos tomados del audio."""
    letra = leer_letra(texto_letra)
    if not letra:
        raise ValueError("El archivo de letra está vacío.")
    if not detectadas:
        raise ValueError(
            "No se detectó voz en el audio, así que no hay con qué sincronizar la letra. "
            "Prueba con --separar-voz o un modelo más grande."
        )

    pares = _emparejar(
        [normalizar(p.texto) for p in letra], [normalizar(p.texto) for p in detectadas]
    )
    if not pares:
        raise ValueError("Ninguna palabra de la letra coincide con lo detectado en el audio.")
    progreso(
        f"Letra sincronizada: {len(pares)} de {len(letra)} palabras encontradas en el audio "
        f"({100 * len(pares) // len(letra)} %)."
    )
    if len(pares) < 0.5 * len(letra):
        progreso(
            "AVISO: menos de la mitad de la letra se reconoció en el audio; revisa los tiempos "
            "(prueba --separar-voz o un modelo más grande, y que la letra sea la completa)."
        )

    tiempos: List[Optional[Tuple[float, float]]] = [None] * len(letra)
    for i, j in pares:
        tiempos[i] = (detectadas[j].inicio, detectadas[j].fin)

    i = 0
    while i < len(letra):
        if tiempos[i] is not None:
            i += 1
            continue
        j = i
        while j < len(letra) and tiempos[j] is None:
            j += 1
        cantidad = j - i
        t0 = tiempos[i - 1][1] if i > 0 else None
        t1 = tiempos[j][0] if j < len(letra) else None
        if t0 is None:
            t0 = max(0.0, t1 - cantidad * _DURACION_PALABRA_ESTIMADA)
        if t1 is None:
            t1 = t0 + cantidad * _DURACION_PALABRA_ESTIMADA
            if duracion_audio:
                t1 = max(t0, min(t1, duracion_audio))
        t1 = max(t0, t1)
        pesos = [len(normalizar(letra[k].texto)) + 2 for k in range(i, j)]
        paso = (t1 - t0) / sum(pesos)
        t = t0
        for k, peso in zip(range(i, j), pesos):
            tiempos[k] = (t, t + peso * paso)
            t += peso * paso
        i = j

    anterior = 0.0
    for palabra, (ini, fin) in zip(letra, tiempos):
        palabra.inicio = max(ini, anterior)
        palabra.fin = max(fin, palabra.inicio)
        anterior = palabra.inicio
    return letra
