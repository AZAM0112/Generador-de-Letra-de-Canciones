import types
import unittest
from unittest import mock

import numpy as np

from generador_letras import refinar
from generador_letras.modelos import Verso

SR = 16000

try:
    from faster_whisper.feature_extractor import FeatureExtractor
except ImportError:  # pragma: no cover
    FeatureExtractor = None


class _Tokenizer:
    """Tokenizer mínimo: un "token" por palabra, como hace Whisper con las palabras con espacio."""

    def encode(self, texto):
        return texto.split()


class _ModeloFalso:
    """Imita la parte de faster_whisper.WhisperModel que usa la segunda pasada.

    El audio de prueba lleva en cada muestra su propio índice, así el modelo sabe qué tramo
    recibió y puede devolver los tiempos "verdaderos" relativos a ese tramo.
    """

    def __init__(self, verdad, prob=0.9, falla=False, partir=False):
        self.verdad = verdad  # texto del verso -> segundo real en que empieza
        self.prob, self.falla, self.partir = prob, falla, partir
        self.feature_extractor = FeatureExtractor() if FeatureExtractor else None
        self.tramos = []

    def encode(self, segmento):
        assert segmento.shape[-1] == 3000, "debe llegar recortado/rellenado a 30 s"
        return self._inicio

    def find_alignment(self, tokenizer, tokens, codificado, cuadros):
        if self.falla:
            raise RuntimeError("fallo simulado")
        assert cuadros <= 3000
        palabras = []
        for texto, ini in self.verdad.items():
            if " ".join(texto.split()) in " ".join(tokens[0]):
                for i, w in enumerate(texto.split()):
                    t = ini + 0.3 * i - codificado
                    if self.partir and w.startswith("¿"):  # el tokenizer real puede separar signos
                        palabras.append(dict(word=" ¿", start=t, end=t, probability=self.prob))
                        w = w[1:]
                    palabras.append(dict(word=" " + w, start=t, end=t + 0.25, probability=self.prob))
        palabras.sort(key=lambda p: p["start"])
        return [palabras]


def _envolver_extractor(modelo):
    real = modelo.feature_extractor

    def extraer(trozo):
        modelo._inicio = float(trozo[0]) / SR
        modelo.tramos.append((float(trozo[0]) / SR, len(trozo) / SR))
        return real(trozo.astype(np.float32) * 0)

    modelo.feature_extractor = types.SimpleNamespace(__call__=extraer, nb_max_frames=real.nb_max_frames)
    modelo.feature_extractor = _Llamable(extraer, real.nb_max_frames)
    return modelo


class _Llamable:
    def __init__(self, f, nb):
        self.f, self.nb_max_frames = f, nb

    def __call__(self, x):
        return self.f(x)


def _audio(segundos):
    return np.arange(int(segundos * SR), dtype=np.float64)


@unittest.skipIf(FeatureExtractor is None, "faster-whisper no instalado")
class SegundaPasada(unittest.TestCase):
    def setUp(self):
        p = mock.patch.object(refinar, "_tokenizer", return_value=_Tokenizer())
        p.start()
        self.addCleanup(p.stop)

    def correr(self, versos, verdad, **kw):
        modelo = _envolver_extractor(_ModeloFalso(verdad, **kw))
        mensajes = []
        n = refinar.refinar_versos(_audio(60), versos, modelo, progreso=mensajes.append)
        return n, mensajes, modelo

    def test_corrige_un_verso_que_no_se_habia_escuchado(self):
        versos = [Verso("Tu amor me sostiene", 5.0, 7.0), Verso("en la tormenta", 9.0, 10.0),
                  Verso("Jesús", 14.0, 15.0)]
        versos[1].confianza, versos[1].revisar = 0.0, refinar._MOTIVO_ESTIMADO
        verdad = {"Tu amor me sostiene": 5.1, "en la tormenta": 7.6, "Jesús": 14.05}
        n, _, _ = self.correr(versos, verdad)
        self.assertAlmostEqual(versos[1].inicio, 7.6, places=2)
        self.assertEqual(versos[1].revisar, "")  # ya no es un tiempo estimado
        self.assertGreaterEqual(versos[1].confianza, 0.8)
        self.assertAlmostEqual(versos[0].inicio, 5.1, places=2)  # pequeño ajuste fino
        self.assertEqual(n, 3)

    def test_no_salta_lejos_un_verso_que_ya_se_escuchaba_bien(self):
        versos = [Verso("Tu amor me sostiene", 5.0, 7.0)]
        n, _, _ = self.correr(versos, {"Tu amor me sostiene": 7.5})
        self.assertEqual((versos[0].inicio, n), (5.0, 0))

    def test_probabilidad_muy_baja_no_se_acepta(self):
        versos = [Verso("Tu amor", 5.0, 6.0)]
        versos[0].confianza = 0.0
        self.correr(versos, {"Tu amor": 8.0}, prob=0.05)
        self.assertEqual(versos[0].inicio, 5.0)

    def test_si_la_alineacion_falla_se_conservan_los_tiempos(self):
        versos = [Verso("Tu amor", 5.0, 6.0)]
        _, mensajes, _ = self.correr(versos, {"Tu amor": 5.2}, falla=True)
        self.assertEqual(versos[0].inicio, 5.0)
        self.assertTrue(any("se conservan" in m for m in mensajes))

    def test_signos_separados_por_el_tokenizer_no_rompen_el_reparto(self):
        versos = [Verso("¿Quién como tú?", 5.0, 6.0)]
        versos[0].confianza = 0.0
        self.correr(versos, {"¿Quién como tú?": 5.4}, partir=True)
        self.assertAlmostEqual(versos[0].inicio, 5.4, places=2)

    def test_tramos_de_hasta_30_segundos_con_margen(self):
        versos = [Verso(f"verso numero {i}", 2.0 + 4 * i, 4.0 + 4 * i) for i in range(12)]
        verdad = {v.texto: v.inicio for v in versos}
        _, _, modelo = self.correr(versos, verdad)
        self.assertGreater(len(modelo.tramos), 1)
        self.assertTrue(all(duracion <= 30.0 for _, duracion in modelo.tramos))
        self.assertAlmostEqual(modelo.tramos[0][0], 0.0)  # 2 s de margen antes del primero

    def test_sin_modelo_no_hace_nada(self):
        versos = [Verso("Tu amor", 5.0, 6.0)]
        self.assertEqual(refinar.refinar_versos(_audio(10), versos, None, progreso=lambda m: None), 0)


class RepartoDePalabras(unittest.TestCase):
    def test_reparte_por_texto_aunque_cambie_la_division(self):
        palabras = [dict(word=w) for w in (" Tu", " amor", " ¿", "Quién", " como", " tú?")]
        grupos = refinar._repartir_palabras(palabras, ["Tu amor", "¿Quién como tú?"])
        self.assertEqual([len(g) for g in grupos], [2, 4])

    def test_texto_distinto_devuelve_none(self):
        self.assertIsNone(refinar._repartir_palabras([dict(word=" hola")], ["adiós"]))


if __name__ == "__main__":
    unittest.main()
