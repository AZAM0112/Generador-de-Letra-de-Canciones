import json
import shutil
import subprocess
import tempfile
import unittest
import wave
from pathlib import Path

import numpy as np

from generador_letras.alineacion import alinear_letra
from generador_letras.modelos import Palabra, Verso, cargar_json, guardar_json
from generador_letras.segmentacion import palabras_a_versos
from generador_letras.tempo import Pulso, ajustar_versos, analizar_y_ajustar, detectar_pulso

SR = 16000


def pista(bpm, dur=30.0, fase=0.4, semilla=0):
    """Batería sintética: bombo y caja alternados, hi-hat a contratiempo, acorde y ruido."""
    rng = np.random.default_rng(semilla)
    n = int(dur * SR)
    y = np.zeros(n, np.float32)
    t = np.arange(int(0.25 * SR)) / SR
    bombo = np.sin(2 * np.pi * (55 + 60 * np.exp(-t * 30)) * t) * np.exp(-t * 12)
    caja = rng.standard_normal(len(t)) * np.exp(-t * 25) * 0.6
    hat = rng.standard_normal(len(t)) * np.exp(-t * 80) * 0.15
    periodo, pulsos, k = 60.0 / bpm, [], 0
    while fase + (k + 0.5) * periodo < dur - 0.3:
        b = fase + k * periodo
        pulsos.append(b)
        i, j = int(b * SR), int((b + periodo / 2) * SR)
        y[i:i + len(t)] += bombo if k % 2 == 0 else caja
        y[j:j + len(t)] += hat
        k += 1
    tt = np.arange(n) / SR
    y += 0.15 * (np.sin(2 * np.pi * 220 * tt) + np.sin(2 * np.pi * 330 * tt))
    y += 0.05 * rng.standard_normal(n)
    return (y / np.abs(y).max()).astype(np.float32), np.array(pulsos)


def rejilla(bpm, origen=0.0, dur=60.0):
    periodo = 60.0 / bpm
    return Pulso(bpm=bpm, tiempos=origen + np.arange(0, dur, periodo), claridad=0.6, constante=True)


class DeteccionDelPulso(unittest.TestCase):
    def test_bpm_y_fase_correctos(self):
        for bpm in (72, 96, 120):
            y, reales = pista(bpm, semilla=bpm)
            p = detectar_pulso(y)
            self.assertAlmostEqual(p.bpm, bpm, delta=1.0, msg=f"{bpm} BPM")
            self.assertTrue(p.fiable)
            distancia = np.abs(reales[:, None] - p.tiempos[None, :]).min(axis=1)
            self.assertLess(np.median(distancia), 0.03)

    def test_sin_ritmo_no_es_fiable(self):
        rng = np.random.default_rng(3)
        tt = np.arange(30 * SR) / SR
        y = (0.3 * np.sin(2 * np.pi * 220 * tt) + 0.05 * rng.standard_normal(len(tt))).astype(np.float32)
        self.assertFalse(detectar_pulso(y).fiable)

    def test_bpm_forzado(self):
        y, _ = pista(90, semilla=1)
        self.assertAlmostEqual(detectar_pulso(y, bpm=45).bpm, 45, delta=1.0)


class AjusteDeVersos(unittest.TestCase):
    def test_lleva_cada_verso_al_tiempo_o_contratiempo_mas_cercano(self):
        pulso = rejilla(75)  # periodo 0.8 s, medio tiempo 0.4 s
        versos = [Verso("a", 2.43, 4), Verso("b", 5.97, 7), Verso("c", 8.39, 9), Verso("d", 12.05, 13)]
        movidos = ajustar_versos(versos, pulso, progreso=lambda m: None)
        self.assertEqual([v.inicio for v in versos], [2.4, 6.0, 8.4, 12.0])
        self.assertEqual(movidos, 4)
        self.assertTrue(all(not v.revisar for v in versos))

    def test_conserva_la_duracion(self):
        versos = [Verso("a", 2.43, 5.43)]
        ajustar_versos(versos, rejilla(75), progreso=lambda m: None)
        self.assertAlmostEqual(versos[0].fin - versos[0].inicio, 3.0, places=3)

    def test_entre_dos_pulsos_no_se_toca_y_se_marca(self):
        versos = [Verso("a", 2.6, 4)]  # justo a mitad entre 2.4 y 2.8
        ajustar_versos(versos, rejilla(75), progreso=lambda m: None)
        self.assertEqual(versos[0].inicio, 2.6)
        self.assertIn("entre dos pulsos", versos[0].revisar)

    def test_corrige_el_desfase_general_de_whisper(self):
        # Todos llegan 0.15 s tarde: sin corregir el sesgo, varios irían al pulso equivocado.
        reales = [2.4, 4.0, 6.0, 8.4, 10.0, 12.4]
        versos = [Verso(str(i), r + 0.15, r + 1) for i, r in enumerate(reales)]
        mensajes = []
        ajustar_versos(versos, rejilla(75), progreso=mensajes.append)
        self.assertEqual([v.inicio for v in versos], reales)
        self.assertTrue(any("desfase general" in m for m in mensajes))

    def test_dos_versos_al_mismo_pulso_marca_el_segundo(self):
        versos = [Verso("a", 2.38, 2.5), Verso("b", 2.42, 3)]
        ajustar_versos(versos, rejilla(75), progreso=lambda m: None)
        self.assertEqual(versos[0].inicio, 2.4)
        self.assertEqual(versos[1].inicio, 2.42)
        self.assertIn("choca", versos[1].revisar)


@unittest.skipUnless(shutil.which("ffmpeg"), "ffmpeg no instalado")
class AnalisisDesdeAudio(unittest.TestCase):
    def wav(self, y):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        ruta = Path(tmp.name) / "c.wav"
        with wave.open(str(ruta), "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(SR)
            w.writeframes((y * 32000).astype(np.int16).tobytes())
        return ruta

    def test_ajusta_versos_de_una_cancion_con_bateria(self):
        y, reales = pista(80, semilla=7)
        versos = [Verso(str(i), round(reales[k] + 0.1, 2), reales[k] + 2) for i, k in enumerate((3, 7, 11, 15, 19))]
        pulso = analizar_y_ajustar(self.wav(y), versos, progreso=lambda m: None)
        self.assertAlmostEqual(pulso.bpm, 80, delta=1.0)
        for v, k in zip(versos, (3, 7, 11, 15, 19)):
            self.assertAlmostEqual(v.inicio, reales[k], delta=0.04)

    def test_sin_ritmo_deja_los_tiempos_como_estaban(self):
        tt = np.arange(20 * SR) / SR
        y = (0.3 * np.sin(2 * np.pi * 220 * tt)).astype(np.float32)
        versos = [Verso("a", 2.43, 4)]
        self.assertIsNone(analizar_y_ajustar(self.wav(y), versos, progreso=lambda m: None))
        self.assertEqual(versos[0].inicio, 2.43)


class MarcasParaRevisar(unittest.TestCase):
    def test_versos_no_reconocidos_quedan_marcados(self):
        detectadas = [Palabra("Tu", 1, 1.3), Palabra("amor", 1.3, 1.8), Palabra("Jesús", 9, 10)]
        palabras = alinear_letra("Tu amor\nme sostiene hoy\nJesús", detectadas, progreso=lambda m: None)
        versos = palabras_a_versos(palabras, cortar_por_pausa=False)
        self.assertEqual([bool(v.revisar) for v in versos], [False, True, False])
        self.assertIn("estimado", versos[1].revisar)

    def test_json_guarda_tempo_y_marcas_y_se_puede_volver_a_cargar(self):
        with tempfile.TemporaryDirectory() as tmp:
            ruta = Path(tmp) / "l.json"
            guardar_json(ruta, "T", [Verso("a", 1, 2, revisar="entre dos pulsos")], tempo_bpm=74.0)
            datos = json.loads(ruta.read_text(encoding="utf-8"))
            self.assertEqual(datos["tempo_bpm"], 74.0)
            self.assertEqual(datos["versos"][0]["revisar"], "entre dos pulsos")
            self.assertEqual(cargar_json(ruta)[1][0].texto, "a")


if __name__ == "__main__":
    unittest.main()
