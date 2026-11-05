"""Segunda pasada: alineación forzada de la LETRA REAL contra el audio, palabra por palabra.

La primera pasada empareja la letra con lo que Whisper creyó oír; las palabras que no oyó
se reparten el tiempo "a ojo". Aquí, en cambio, se le entrega a Whisper el texto correcto
de cada tramo (≤ 30 s) y se le pide solo *cuándo* suena cada palabra (la misma técnica que
usa para sus tiempos por palabra: atención cruzada + DTW). No requiere instalar nada más.

Protecciones: un verso que ya se había escuchado bien solo se mueve un poco; uno con
probabilidad muy baja no se acepta; y ante cualquier error se conservan los tiempos previos.
"""
from __future__ import annotations

from typing import Callable, List, Optional, Sequence, Tuple

import numpy as np

from .alineacion import normalizar
from .modelos import Verso

SR = 16000
VENTANA_MAX = 28.0  # Whisper procesa 30 s; se deja holgura
MARGEN = 2.0  # segundos de audio extra antes y después de cada tramo
MOVIMIENTO_MAX_CONFIABLE = 1.0  # cuánto puede moverse un verso que ya se había escuchado bien
PROB_MINIMA = 0.15  # debajo, la letra probablemente no suena en ese tramo
PROB_BUENA = 0.4

_MOTIVO_ESTIMADO = "no se reconoció en el audio: tiempo estimado"


def _tokenizer(modelo, idioma: str):
    from faster_whisper.tokenizer import Tokenizer

    return Tokenizer(modelo.hf_tokenizer, modelo.model.is_multilingual, task="transcribe", language=idioma)


def _tramos(versos: Sequence[Verso], duracion: float) -> List[Tuple[float, float, List[int]]]:
    """Agrupa versos consecutivos en tramos de audio de hasta VENTANA_MAX segundos."""
    tramos, actual, inicio = [], [], 0.0
    for i, v in enumerate(versos):
        if actual and v.fin + MARGEN - inicio > VENTANA_MAX:
            tramos.append((inicio, actual))
            actual = []
        if not actual:
            inicio = max(0.0, v.inicio - MARGEN)
        actual.append(i)
    if actual:
        tramos.append((inicio, actual))
    return [
        (ini, min(duracion, ini + 30.0, max(versos[i].fin for i in idx) + MARGEN), idx)
        for ini, idx in tramos
    ]


def _repartir_palabras(palabras: List[dict], textos: Sequence[str]) -> Optional[List[List[dict]]]:
    """Asigna las palabras alineadas a cada verso comparando el texto (sin espacios ni tildes)."""
    grupos, k = [], 0
    for texto in textos:
        objetivo, acumulado, grupo = normalizar(texto), "", []
        while k < len(palabras) and len(acumulado) < len(objetivo):
            acumulado += normalizar(palabras[k]["word"])
            grupo.append(palabras[k])
            k += 1
        if acumulado != objetivo or not grupo:
            return None
        grupos.append(grupo)
    return grupos if k == len(palabras) else None


def _alinear_tramo(modelo, tokenizer, audio: np.ndarray, ini: float, fin: float, textos: Sequence[str]):
    from faster_whisper.audio import pad_or_trim

    trozo = audio[int(ini * SR):int(fin * SR)]
    caracteristicas = modelo.feature_extractor(trozo)
    cuadros = min(caracteristicas.shape[-1] - 1, modelo.feature_extractor.nb_max_frames)
    codificado = modelo.encode(pad_or_trim(caracteristicas[:, :cuadros]))
    tokens = tokenizer.encode("".join(" " + t.strip() for t in textos))
    resultado = modelo.find_alignment(tokenizer, [tokens], codificado, cuadros)
    return resultado[0] if resultado else []


def refinar_versos(
    audio: np.ndarray,
    versos: List[Verso],
    modelo,
    idioma: str = "es",
    progreso: Callable[[str], None] = print,
) -> int:
    """Ajusta inicio y fin de cada verso con la alineación forzada. Devuelve cuántos cambió."""
    if modelo is None or not versos:
        return 0
    tokenizer = _tokenizer(modelo, idioma)
    duracion = len(audio) / SR
    tramos = _tramos(versos, duracion)
    progreso(f"Segunda pasada: alineando la letra real palabra por palabra ({len(tramos)} tramos)...")
    previos = [(v.inicio, v.fin) for v in versos]
    cambiados = 0
    for n, (ini, fin, indices) in enumerate(tramos, start=1):
        textos = [versos[i].texto for i in indices]
        try:
            palabras = _alinear_tramo(modelo, tokenizer, audio, ini, fin, textos)
        except Exception as e:  # nunca empeorar: se conservan los tiempos de la primera pasada
            progreso(f"  tramo {n}: no se pudo alinear ({e}); se conservan sus tiempos.")
            continue
        grupos = _repartir_palabras(palabras, textos)
        if grupos is None:
            progreso(f"  tramo {n}: las palabras no coincidieron con la letra; se conservan sus tiempos.")
            continue
        for i, grupo in zip(indices, grupos):
            v = versos[i]
            nuevo_ini = ini + float(grupo[0]["start"])
            nuevo_fin = max(ini + float(grupo[-1]["end"]), nuevo_ini + 0.3)
            prob = float(np.mean([w["probability"] for w in grupo]))
            if prob < PROB_MINIMA:
                continue
            if v.confianza >= 0.75 and abs(nuevo_ini - v.inicio) > MOVIMIENTO_MAX_CONFIABLE:
                continue  # ya se había escuchado bien: un salto grande sería un error de la alineación
            if abs(nuevo_ini - v.inicio) > 0.02 or abs(nuevo_fin - v.fin) > 0.02:
                cambiados += 1
            v.inicio, v.fin = round(nuevo_ini, 3), round(nuevo_fin, 3)
            if prob >= PROB_BUENA:
                v.confianza = max(v.confianza, 0.8)
                if v.revisar == _MOTIVO_ESTIMADO:
                    v.revisar = ""
            else:
                v.confianza = max(v.confianza, 0.6)

    # Si algo quedó fuera de orden, ese verso vuelve a su tiempo anterior.
    for i in range(1, len(versos)):
        if versos[i].inicio <= versos[i - 1].inicio:
            versos[i].inicio, versos[i].fin = previos[i]
            if versos[i].inicio <= versos[i - 1].inicio:
                versos[i - 1].inicio, versos[i - 1].fin = previos[i - 1]
    progreso(f"  {cambiados} versos con tiempos más precisos.")
    return cambiados
