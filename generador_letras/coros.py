"""Consistencia entre repeticiones (coros): lo que se repite se canta igual cada vez.

Si dos versos seguidos A→B aparecen varias veces en la canción, la distancia entre el inicio
de A y el de B debe ser casi la misma en cada repetición (misma melodía, mismo tempo). Con las
repeticiones bien escuchadas se calcula esa distancia "de consenso" y se usa para:
  * corregir versos que no se escucharon (confianza baja) a partir de su vecino bien escuchado;
  * marcar para revisar los que se escucharon pero no coinciden con el resto.
"""
from __future__ import annotations

from collections import defaultdict
from typing import Callable, Dict, List, Optional, Tuple

import numpy as np

from .alineacion import normalizar
from .modelos import Verso

TOLERANCIA = 0.35  # s de diferencia aceptable entre repeticiones
CONFIABLE = 0.75  # confianza para que una repetición cuente en el consenso
ANCLA = 0.6  # confianza mínima del vecino que sirve de referencia para corregir
MOVIBLE = 0.5  # solo se mueven versos con menos confianza que esto (casi no se escucharon)
CONFIANZA_DERIVADA = 0.6

_MOTIVO = "no coincide con las otras repeticiones de esta parte"


def _consenso(distancias: List[float]) -> Optional[Tuple[float, int]]:
    """Distancia con más apoyo (dentro de la tolerancia) y cuántas repeticiones la apoyan."""
    mejor = None
    for d in distancias:
        apoyo = [x for x in distancias if abs(x - d) <= TOLERANCIA]
        if mejor is None or len(apoyo) > mejor[1]:
            mejor = (float(np.median(apoyo)), len(apoyo))
    return mejor


def _cabe(versos: List[Verso], i: int, inicio: float) -> bool:
    """El verso i puede empezar en `inicio` sin desordenarse respecto a sus vecinos."""
    antes = versos[i - 1].inicio if i > 0 else -1.0
    despues = versos[i + 1].inicio if i + 1 < len(versos) else float("inf")
    return antes < inicio < despues and inicio >= 0


def _mover(v: Verso, inicio: float) -> None:
    duracion = v.fin - v.inicio
    v.inicio = round(inicio, 3)
    v.fin = round(inicio + max(duracion, 0.3), 3)
    v.confianza = CONFIANZA_DERIVADA
    v.revisar = ""


def armonizar_repeticiones(versos: List[Verso], progreso: Callable[[str], None] = print) -> int:
    """Corrige con las repeticiones bien escuchadas. Devuelve cuántos versos movió."""
    claves = [normalizar(v.texto) for v in versos]
    movidos = 0
    for _ in range(5):  # cada corrección puede servir de referencia para la siguiente
        cambios = 0
        pares: Dict[Tuple[str, str], List[int]] = defaultdict(list)
        for k in range(len(versos) - 1):
            pares[(claves[k], claves[k + 1])].append(k)
        for ocurrencias in pares.values():
            if len(ocurrencias) < 2:
                continue
            fiables = [
                versos[k + 1].inicio - versos[k].inicio
                for k in ocurrencias
                if min(versos[k].confianza, versos[k + 1].confianza) >= CONFIABLE
            ]
            consenso = _consenso(fiables) if fiables else None
            if consenso is None:
                continue
            distancia, apoyo = consenso
            for k in ocurrencias:
                a, b = versos[k], versos[k + 1]
                if abs((b.inicio - a.inicio) - distancia) <= TOLERANCIA:
                    continue
                if b.confianza < MOVIBLE and a.confianza >= ANCLA and _cabe(versos, k + 1, a.inicio + distancia):
                    _mover(b, a.inicio + distancia)
                    cambios += 1
                elif a.confianza < MOVIBLE and b.confianza >= ANCLA and _cabe(versos, k, b.inicio - distancia):
                    _mover(a, b.inicio - distancia)
                    cambios += 1
                elif apoyo >= 2 and min(a.confianza, b.confianza) >= CONFIABLE and _MOTIVO not in b.revisar:
                    b.revisar = f"{b.revisar}; {_MOTIVO}" if b.revisar else _MOTIVO
        movidos += cambios
        if not cambios:
            break
    if movidos:
        progreso(f"Coros: {movidos} versos corregidos usando las otras repeticiones.")
    return movidos
