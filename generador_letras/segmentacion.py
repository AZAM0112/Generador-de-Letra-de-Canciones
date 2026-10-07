"""De palabras con tiempos a versos, y de versos a páginas (lo que se ve en pantalla)."""
from __future__ import annotations

from typing import List

from .modelos import Pagina, Palabra, Verso

PAUSA_VERSO = 0.8  # segundos de silencio entre palabras que separan dos versos
PAUSA_ESTROFA = 3.0  # silencio entre versos que obliga a empezar una página nueva
MAX_PALABRAS_VERSO = 8
MAX_CHARS_VERSO = 40
MAX_VERSOS_PAGINA = 2  # máximo de versos en "lo que viene" (y en lo que se canta)
DURACION_MINIMA_VERSO = 0.4

_PUNTUACION_FUERTE = ".?!;"
_PUNTUACION_SUAVE = ","


def _termina_con(texto: str, signos: str) -> bool:
    return bool(texto) and texto[-1] in signos


def _excede(palabras: List[Palabra]) -> bool:
    texto = " ".join(p.texto for p in palabras)
    return len(palabras) > MAX_PALABRAS_VERSO or len(texto) > MAX_CHARS_VERSO


def _dividir(palabras: List[Palabra]) -> List[List[Palabra]]:
    """Parte un tramo demasiado largo por su pausa más grande (cerca de la mitad)."""
    n = len(palabras)
    if n < 2 or not _excede(palabras):
        return [palabras]
    minimo = 2 if n >= 4 else 1  # evita dejar una palabra suelta
    mejor, mejor_puntaje = minimo, float("-inf")
    for i in range(minimo, n - minimo + 1):
        hueco = palabras[i].inicio - palabras[i - 1].fin
        bonus = 0.3 if _termina_con(palabras[i - 1].texto, _PUNTUACION_SUAVE) else 0.0
        puntaje = hueco + bonus - 0.03 * abs(i - n / 2)
        if puntaje > mejor_puntaje:
            mejor, mejor_puntaje = i, puntaje
    return _dividir(palabras[:mejor]) + _dividir(palabras[mejor:])


def limpiar_texto(texto: str) -> str:
    """Quita puntuación sobrante de los extremos y pone mayúscula inicial."""
    texto = " ".join(texto.split()).strip(" ,.;:…-–—\"'")
    for i, c in enumerate(texto):
        if c.isalpha():
            return texto[:i] + c.upper() + texto[i + 1:]
    return texto


def palabras_a_versos(palabras: List[Palabra], cortar_por_pausa: bool = True) -> List[Verso]:
    """Agrupa palabras en versos.

    Con `cortar_por_pausa=True` (transcripción automática) se corta por silencios,
    puntuación y fin de segmento. Con `False` (letra dada por el usuario) solo se
    respetan las líneas que él escribió (marcadas con `Palabra.corte`).
    """
    tramos: List[List[Palabra]] = []
    actual: List[Palabra] = []
    for p in palabras:
        if actual and (
            p.pagina_nueva or (cortar_por_pausa and p.inicio - actual[-1].fin >= PAUSA_VERSO)
        ):
            tramos.append(actual)
            actual = []
        actual.append(p)
        cierra = p.corte
        if cortar_por_pausa:
            cierra = (
                cierra
                or _termina_con(p.texto, _PUNTUACION_FUERTE)
                or (_termina_con(p.texto, _PUNTUACION_SUAVE) and len(actual) >= 5)
            )
        if cierra:
            tramos.append(actual)
            actual = []
    if actual:
        tramos.append(actual)

    versos: List[Verso] = []
    for tramo in tramos:
        for k, parte in enumerate(_dividir(tramo)):
            texto = limpiar_texto(" ".join(p.texto for p in parte))
            if not texto:
                continue
            inicio = parte[0].inicio
            fin = max(parte[-1].fin, inicio + DURACION_MINIMA_VERSO)
            versos.append(Verso(texto, inicio, fin, pagina_nueva=parte[0].pagina_nueva and k == 0))
    versos.sort(key=lambda v: v.inicio)
    return versos


def versos_a_paginas(versos: List[Verso], max_versos: int = MAX_VERSOS_PAGINA) -> List[Pagina]:
    """Reparte los versos en páginas de hasta `max_versos`.

    Un verso de una sola palabra (el "Jesús" de un coro) va siempre solo en su
    página: no se le agregan más versos. También se abre página nueva al cambiar
    de estrofa (pausa larga o salto de estrofa pedido en la letra).
    """
    paginas: List[Pagina] = []
    actual: List[Verso] = []
    for v in versos:
        if actual:
            separada = (
                len(actual) >= max_versos
                or v.num_palabras == 1
                or actual[-1].num_palabras == 1
                or v.pagina_nueva
                or v.inicio - actual[-1].fin > PAUSA_ESTROFA
            )
            if separada:
                paginas.append(Pagina(actual))
                actual = []
        actual.append(v)
    if actual:
        paginas.append(Pagina(actual))
    return paginas
