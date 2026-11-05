"""Prueba de todo el proceso automático (sin el modelo Whisper real, que se simula)."""
import json
import shutil
import tempfile
import unittest
import wave
from pathlib import Path
from unittest import mock

import numpy as np

from generador_letras import generar_video_letra
from generador_letras.modelos import Palabra
from generador_letras.tests.test_tempo import pista

SR = 16000
LETRA = """[Verso]
Eres digno de toda alabanza

[Coro]
Santo es el Señor
digno de alabar

[Coro]
Santo es el Señor
digno de alabar

[Coro]
Santo es el Señor
digno de alabar
"""


@unittest.skipUnless(shutil.which("ffmpeg"), "ffmpeg no instalado")
class ProcesoCompleto(unittest.TestCase):
    def test_coro_no_escuchado_tempo_y_pagina(self):
        y, pulsos = pista(80, dur=45, semilla=21)  # periodo 0.75 s
        reales = {"verso": pulsos[4], "c1": pulsos[12], "c2": pulsos[24], "c3": pulsos[40]}
        distancia = 4 * 0.75  # la 2ª línea del coro entra 4 tiempos después de la 1ª

        def oir(texto, t):  # Whisper oye las palabras ~0.12 s tarde
            return [Palabra(w, t + 0.12 + 0.3 * i, t + 0.12 + 0.3 * i + 0.25) for i, w in enumerate(texto.split())]

        detectadas = oir("eres digno de toda alabanza", reales["verso"])
        for c in ("c1", "c2"):
            detectadas += oir("santo es el señor", reales[c]) + oir("digno de alabar", reales[c] + distancia)
        detectadas += oir("santo es el señor", reales["c3"])  # la última línea no se oyó
        for p in detectadas:
            p.corte = False

        with tempfile.TemporaryDirectory() as tmp:
            carpeta = Path(tmp)
            audio = carpeta / "Santo.wav"
            with wave.open(str(audio), "wb") as w:
                w.setnchannels(1)
                w.setsampwidth(2)
                w.setframerate(SR)
                w.writeframes((y * 32000).astype(np.int16).tobytes())
            (carpeta / "Santo.txt").write_text(LETRA, encoding="utf-8")
            mensajes = []
            with mock.patch("generador_letras.transcripcion.transcribir", return_value=detectadas):
                ruta = generar_video_letra(audio, letra=carpeta / "Santo.txt", solo_json=True,
                                           progreso=mensajes.append)
            datos = json.loads(ruta.read_text(encoding="utf-8"))
            pagina = carpeta / "Santo_revisar.html"
            self.assertTrue(pagina.exists())

        versos = datos["versos"]
        self.assertEqual(len(versos), 7)
        self.assertAlmostEqual(datos["tempo_bpm"], 80, delta=1)
        esperados = [reales["verso"], reales["c1"], reales["c1"] + distancia, reales["c2"],
                     reales["c2"] + distancia, reales["c3"], reales["c3"] + distancia]
        for v, t in zip(versos, esperados):
            self.assertAlmostEqual(v["inicio"], t, delta=0.05, msg=v["texto"])
        # El verso no escuchado se recuperó gracias a los otros coros: ya no queda aviso.
        self.assertNotIn("revisar", versos[-1])
        self.assertTrue(any("Coros: 1 versos corregidos" in m for m in mensajes))
        self.assertTrue(any("pasaron todas las comprobaciones" in m for m in mensajes))


if __name__ == "__main__":
    unittest.main()
