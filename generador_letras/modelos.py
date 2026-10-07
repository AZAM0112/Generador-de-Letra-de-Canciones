"""Estructuras de datos compartidas y lectura/escritura del JSON de letra."""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import List, Tuple


@dataclass
class Palabra:
    """Una palabra con su tiempo (en segundos) dentro del audio."""

    texto: str
    inicio: float
    fin: float
    corte: bool = False  # la palabra cierra un verso (fin de segmento o de línea)
    pagina_nueva: bool = False  # la palabra abre una estrofa nueva


@dataclass
class Verso:
    """Una frase que se muestra en una sola unidad (puede ocupar varias líneas visuales)."""

    texto: str
    inicio: float
    fin: float
    pagina_nueva: bool = False

    @property
    def num_palabras(self) -> int:
        return len(self.texto.split())


@dataclass
class Pagina:
    """Grupo de 1 o 2 versos que se muestran juntos y se desplazan a la vez."""

    versos: List[Verso]

    @property
    def inicio(self) -> float:
        return self.versos[0].inicio

    @property
    def fin(self) -> float:
        return max(v.fin for v in self.versos)


def guardar_json(ruta, titulo: str, versos: List[Verso]) -> Path:
    """Guarda la letra con sus tiempos en un JSON que se puede revisar y corregir a mano."""
    registros = []
    for v in versos:
        registro = {"inicio": round(v.inicio, 2), "fin": round(v.fin, 2), "texto": v.texto}
        if v.pagina_nueva:
            registro["nueva_pagina"] = True
        registros.append(registro)
    ruta = Path(ruta)
    ruta.write_text(
        json.dumps({"titulo": titulo, "versos": registros}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return ruta


def cargar_json(ruta) -> Tuple[str, List[Verso]]:
    """Lee un JSON generado por `guardar_json` (o escrito a mano con el mismo formato)."""
    datos = json.loads(Path(ruta).read_text(encoding="utf-8"))
    versos = []
    for i, v in enumerate(datos.get("versos", []), start=1):
        texto = str(v.get("texto", "")).strip()
        if not texto:
            raise ValueError(f"Verso {i} sin texto en {ruta}")
        inicio, fin = float(v["inicio"]), float(v["fin"])
        if fin < inicio:
            raise ValueError(f"Verso {i} ({texto!r}): 'fin' es menor que 'inicio'")
        versos.append(Verso(texto, inicio, fin, bool(v.get("nueva_pagina", False))))
    versos.sort(key=lambda v: v.inicio)
    return str(datos.get("titulo", "")).strip(), versos
