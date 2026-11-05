"""Tempo (BPM) y pulso de la canción, y ajuste de los versos a ese pulso.

Solo usa numpy (ya viene con faster-whisper): no hay que instalar nada más.

1. Envolvente de ataques: cuánto "golpe" nuevo hay en cada instante (flujo espectral).
   (con un ruido de fondo inaudible y un leve suavizado para no confundir sonidos estáticos)
2. Tempo: la autocorrelación de esa envolvente tiene picos en el periodo del pulso.
3. Pulso: programación dinámica (Ellis, 2007) que elige golpes fuertes separados ~1 periodo.
4. Ajuste: cada verso se mueve a la subdivisión del pulso más cercana (medio tiempo por
   defecto, porque muchos versos entran en el "y" del compás). Si cae justo entre dos,
   no se toca y se marca para revisar.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable, List, Optional

import numpy as np

from .modelos import Verso

SR = 16000
HOP = 256
NFFT = 1024
FPS = SR / HOP  # cuadros de envolvente por segundo (62.5)

BPM_MIN, BPM_MAX = 40.0, 200.0
BPM_CENTRAL = 100.0  # preferencia suave cuando hay ambigüedad doble/mitad
CLARIDAD_MINIMA = 0.15  # periodicidad mínima (0-1); debajo, el pulso no es fiable
DITHER_DB = 40.0  # ruido de fondo inaudible: evita pulsos falsos en sonidos totalmente estáticos
N_BANDAS = 40  # bandas de frecuencia logarítmicas: el bombo grave pesa igual que la caja
SUBDIVISION = 2  # 2 = se ajusta a medios tiempos
ZONA_DUDOSA = 0.4  # fracción de la subdivisión: más lejos que esto => "entre dos pulsos"


@dataclass
class Pulso:
    bpm: float
    tiempos: np.ndarray  # segundos de cada pulso
    claridad: float  # qué tan periódicos son los golpes (0 = nada, 1 = metrónomo)
    constante: bool  # el tempo no cambia en toda la canción

    @property
    def fiable(self) -> bool:
        return self.claridad >= CLARIDAD_MINIMA and len(self.tiempos) >= 8


def _bandas() -> np.ndarray:
    """Matriz (bins FFT x bandas) de filtros triangulares espaciados logarítmicamente."""
    frecuencias = np.fft.rfftfreq(NFFT, 1 / SR)
    bordes = np.geomspace(30.0, 7500.0, N_BANDAS + 2)
    m = np.zeros((len(frecuencias), N_BANDAS), dtype=np.float32)
    for b in range(N_BANDAS):
        izq, centro, der = bordes[b], bordes[b + 1], bordes[b + 2]
        subida = (frecuencias - izq) / (centro - izq)
        bajada = (der - frecuencias) / (der - centro)
        m[:, b] = np.maximum(0, np.minimum(subida, bajada))
    vacias = m.sum(axis=0) == 0  # bandas graves más angostas que un bin: usar el bin más cercano
    for b in np.flatnonzero(vacias):
        m[int(np.argmin(np.abs(frecuencias - bordes[b + 1]))), b] = 1.0
    return m / m.sum(axis=0, keepdims=True)


def envolvente_ataques(y: np.ndarray) -> np.ndarray:
    """Flujo espectral por bandas, comprimido, sin la tendencia lenta y normalizado."""
    if len(y) < NFFT * 4:
        return np.zeros(0, dtype=np.float32)
    rms = float(np.sqrt(np.mean(np.square(y, dtype=np.float64)))) + 1e-12
    ruido = np.random.default_rng(0).standard_normal(len(y)).astype(np.float32)
    y = y.astype(np.float32) + ruido * np.float32(rms * 10 ** (-DITHER_DB / 20))
    cuadros = np.lib.stride_tricks.sliding_window_view(y, NFFT)[::HOP]
    ventana = np.hanning(NFFT).astype(np.float32)
    flujo = np.empty(len(cuadros), dtype=np.float32)
    bandas = _bandas()
    previo = None
    for ini in range(0, len(cuadros), 2048):  # por bloques para no usar mucha memoria
        espectro = np.abs(np.fft.rfft(cuadros[ini:ini + 2048] * ventana, axis=1)).astype(np.float32)
        mag = np.log1p(1000.0 * (espectro @ bandas))
        antes = mag[:1] if previo is None else previo[None, :]
        flujo[ini:ini + len(mag)] = np.maximum(np.diff(mag, axis=0, prepend=antes), 0).mean(axis=1)
        previo = mag[-1]
    ancho = int(FPS) | 1
    tendencia = np.convolve(flujo, np.ones(ancho) / ancho, mode="same")
    env = np.maximum(flujo - tendencia, 0)
    sigma = 2  # suavizado ~30 ms: quita patrones más rápidos que cualquier pulso musical
    w = np.arange(-4 * sigma, 4 * sigma + 1)
    g = np.exp(-0.5 * (w / sigma) ** 2)
    env = np.convolve(env, g / g.sum(), mode="same")
    return env / (env.std() + 1e-9)


def _autocorrelacion(env: np.ndarray) -> np.ndarray:
    """Autocorrelación normalizada (1 en el desfase 0)."""
    n = len(env)
    x = env - env.mean()
    ac = np.fft.irfft(np.abs(np.fft.rfft(x, 2 * n)) ** 2)[:n]
    return ac / (ac[0] + 1e-12)


def periodicidad(env: np.ndarray, bpm: float) -> float:
    """Autocorrelación en el periodo del pulso: ~0 sin ritmo, alta con batería marcada."""
    ac = _autocorrelacion(env)
    lag = 60.0 * FPS / bpm
    i = int(round(lag))
    if i + 2 >= len(ac):
        return 0.0
    return float(max(0.0, ac[max(1, i - 1):i + 2].max()))


def estimar_bpm(env: np.ndarray) -> Optional[float]:
    n = len(env)
    if n < FPS * 4:
        return None
    ac = _autocorrelacion(env)
    lags = np.arange(1, n)
    bpm = 60.0 * FPS / lags
    validos = (bpm >= BPM_MIN) & (bpm <= BPM_MAX)
    preferencia = np.exp(-0.5 * np.log2(bpm / BPM_CENTRAL) ** 2)
    puntaje = np.where(validos, ac[1:] * preferencia, -np.inf)
    i = int(np.argmax(puntaje))
    lag = float(lags[i])
    if 0 < i < len(puntaje) - 1 and np.isfinite(puntaje[i - 1]) and np.isfinite(puntaje[i + 1]):
        a, b, c = ac[i], ac[i + 1], ac[i + 2]  # ac[lag-1], ac[lag], ac[lag+1]
        den = a - 2 * b + c
        if den < 0:
            lag += 0.5 * (a - c) / den
    return 60.0 * FPS / lag


def seguir_pulso(env: np.ndarray, bpm: float, rigidez: float = 100.0) -> np.ndarray:
    """Índices de cuadro de cada pulso (programación dinámica)."""
    periodo = 60.0 * FPS / bpm
    w = np.arange(-int(periodo), int(periodo) + 1)
    local = np.convolve(env, np.exp(-0.5 * (w * 32.0 / periodo) ** 2), mode="same")
    n = len(local)
    ventana = np.arange(-int(round(2 * periodo)), -int(round(periodo / 2)) + 1)
    costo = -rigidez * np.log(-ventana / periodo) ** 2
    acumulado = np.zeros(n)
    anterior = np.full(n, -1)
    umbral = 0.01 * local.max()
    empezado = False  # hasta el primer golpe claro no se encadenan pulsos
    for i in range(n):
        z = i + ventana
        ok = z >= 0
        if not ok.any() or (not empezado and local[i] < umbral):
            acumulado[i] = local[i]
            continue
        empezado = True
        candidatos = acumulado[z[ok]] + costo[ok]
        j = int(np.argmax(candidatos))
        acumulado[i] = local[i] + candidatos[j]
        anterior[i] = z[ok][j]
    maximos = np.flatnonzero(
        (acumulado[1:-1] > acumulado[:-2]) & (acumulado[1:-1] >= acumulado[2:])
    ) + 1
    if len(maximos) == 0:
        return np.zeros(0, dtype=int)
    corte = 0.5 * np.median(acumulado[maximos])
    i = int(maximos[acumulado[maximos] > corte][-1])
    pulsos = []
    while i >= 0:
        pulsos.append(i)
        i = anterior[i]
    return np.array(pulsos[::-1], dtype=int)


def detectar_pulso(y: np.ndarray, bpm: Optional[float] = None) -> Optional[Pulso]:
    """Pulso de una señal mono a 16 kHz. `bpm` fuerza el tempo si la detección se equivoca."""
    env = envolvente_ataques(y)
    bpm = bpm or estimar_bpm(env)
    if not bpm:
        return None
    cuadros = seguir_pulso(env, bpm)
    if len(cuadros) < 2:
        return None
    t = cuadros / FPS + NFFT / (2 * SR)  # el cuadro empieza antes: se toma su centro
    # Tempo constante: se ajusta una rejilla regular (más estable que los golpes sueltos).
    periodo = 60.0 / bpm
    k = np.round((t - t[0]) / periodo)
    pendiente, origen = np.polyfit(k, t, 1)
    constante = float(np.median(np.abs(t - (origen + k * pendiente)))) < 0.04
    if constante:
        k_total = np.arange(int(np.ceil(-origen / pendiente)), int(len(env) / FPS / pendiente) + 1)
        tiempos = origen + k_total * pendiente
        bpm = 60.0 / pendiente
    else:
        tiempos = t
    claridad = periodicidad(env, bpm)
    return Pulso(bpm=float(bpm), tiempos=tiempos, claridad=claridad, constante=constante)


def _rejilla(tiempos: np.ndarray, subdivision: int) -> np.ndarray:
    if subdivision <= 1 or len(tiempos) < 2:
        return tiempos
    partes = [tiempos[:-1] + (tiempos[1:] - tiempos[:-1]) * f / subdivision for f in range(subdivision)]
    return np.sort(np.concatenate(partes + [tiempos[-1:]]))


def _agregar_motivo(v: Verso, motivo: str) -> None:
    v.revisar = f"{v.revisar}; {motivo}" if v.revisar else motivo


def ajustar_versos(
    versos: List[Verso], pulso: Pulso, subdivision: int = SUBDIVISION,
    progreso: Callable[[str], None] = print,
) -> int:
    """Mueve el inicio de cada verso a la subdivisión más cercana. Devuelve cuántos movió."""
    rejilla = _rejilla(pulso.tiempos, subdivision)
    if len(rejilla) < 2 or not versos:
        return 0
    paso = 60.0 / pulso.bpm / subdivision

    def cercano(t: float) -> float:
        i = int(np.clip(np.searchsorted(rejilla, t), 1, len(rejilla) - 1))
        return float(rejilla[i] if rejilla[i] - t < t - rejilla[i - 1] else rejilla[i - 1])

    # Whisper suele marcar todo un poco antes o después: se estima ese desfase general.
    desfases = np.array([cercano(v.inicio) - v.inicio for v in versos])
    sesgo = float(np.median(desfases)) if len(versos) >= 5 else 0.0
    if abs(sesgo) >= 0.03:
        progreso(f"  desfase general del reconocimiento: {sesgo:+.2f} s (corregido)")

    movidos, anterior = 0, -1.0
    for v in versos:
        objetivo = round(cercano(v.inicio + sesgo), 3)
        distancia = objetivo - (v.inicio + sesgo)
        if abs(distancia) > ZONA_DUDOSA * paso:
            _agregar_motivo(v, "entre dos pulsos: revisa el inicio")
        elif objetivo <= anterior:
            _agregar_motivo(v, "choca con el verso anterior al ajustar al pulso")
        else:
            if abs(objetivo - v.inicio) > 1e-3:
                movidos += 1
            duracion = v.fin - v.inicio
            v.inicio = objetivo
            v.fin = round(max(v.inicio + duracion, v.inicio + 0.3), 3)
        anterior = v.inicio
    return movidos


def analizar_y_ajustar(
    audio: Path, versos: List[Verso], *, bpm: Optional[float] = None,
    progreso: Callable[[str], None] = print,
) -> Optional[Pulso]:
    """Detecta el tempo del audio y ajusta los versos. Devuelve el pulso (o None si no fue fiable)."""
    from .transcripcion import cargar_audio

    progreso("Analizando el tempo de la canción...")
    pulso = detectar_pulso(cargar_audio(audio), bpm=bpm)
    if pulso is None:
        progreso("  no se pudo detectar el tempo; los tiempos quedan como estaban.")
        return None
    tipo = "constante" if pulso.constante else "variable"
    progreso(f"  tempo: {pulso.bpm:.1f} BPM ({tipo}, claridad del pulso {pulso.claridad:.1f})")
    if not pulso.fiable and not bpm:
        progreso(
            "  el pulso no es claro (poca percusión): no se ajustan los tiempos. "
            "Si conoces el tempo, pásalo con --bpm."
        )
        return None
    movidos = ajustar_versos(versos, pulso, progreso=progreso)
    dudosos = [v for v in versos if v.revisar]
    progreso(f"  {movidos} versos ajustados al pulso; {len(dudosos)} marcados para revisar.")
    for v in dudosos[:10]:
        progreso(f"    {v.inicio:7.2f} s  {v.texto[:40]!r}: {v.revisar}")
    return pulso
