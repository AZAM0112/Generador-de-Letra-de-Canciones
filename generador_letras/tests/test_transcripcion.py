import inspect
import sys
import types
import unittest
from pathlib import Path
from unittest import mock

from generador_letras import transcripcion

try:  # firma real de la librería, para comprobar que no pasamos parámetros inexistentes
    from faster_whisper import WhisperModel as _ModeloReal

    _PARAMETROS_REALES = set(inspect.signature(_ModeloReal.transcribe).parameters)
except ImportError:  # pragma: no cover
    _PARAMETROS_REALES = None


def _seg(texto, ini, fin, palabras):
    ws = [types.SimpleNamespace(word=w, start=a, end=b) for w, a, b in palabras]
    return types.SimpleNamespace(text=texto, start=ini, end=fin, words=ws)


class _ModeloFalso:
    llamadas = []

    def __init__(self, nombre, device="cpu", compute_type="default", **kw):
        _ModeloFalso.llamadas.append(("init", nombre, device, compute_type))

    def transcribe(self, audio, **opciones):
        _ModeloFalso.llamadas.append(("transcribe", audio, opciones))
        segmentos = [
            _seg(" Tu amor me sostiene", 1.0, 4.0,
                 [(" Tu", 1.0, 1.3), (" amor", 1.3, 1.8), (" me", 1.8, 2.0), (" sostiene", 2.0, 3.5)]),
            _seg(" Subtítulos realizados por la comunidad de Amara.org", 5.0, 8.0,
                 [(" Subtítulos", 5.0, 6.0)]),
            _seg(" Jesús", 9.0, 10.0, [(" Jesús", 9.0, 10.0)]),
            _seg(" ", 11.0, 12.0, []),
        ]
        return iter(segmentos), types.SimpleNamespace(duration=12.0)


class Transcribir(unittest.TestCase):
    def setUp(self):
        _ModeloFalso.llamadas = []
        falso = types.ModuleType("faster_whisper")
        falso.WhisperModel = _ModeloFalso
        parche = mock.patch.dict(sys.modules, {"faster_whisper": falso})
        parche.start()
        self.addCleanup(parche.stop)
        mock.patch.object(transcripcion, "hay_gpu", return_value=False).start()
        mock.patch.object(transcripcion, "cargar_audio", return_value="audio-simulado").start()
        self.addCleanup(mock.patch.stopall)

    def test_devuelve_palabras_con_tiempos_y_filtra_alucinaciones(self):
        ps = transcripcion.transcribir(Path("x.mp3"), progreso=lambda m: None)
        self.assertEqual([p.texto for p in ps], ["Tu", "amor", "me", "sostiene", "Jesús"])
        self.assertEqual([(p.inicio, p.fin) for p in ps][:2], [(1.0, 1.3), (1.3, 1.8)])
        # Cada segmento cierra un verso.
        self.assertEqual([p.corte for p in ps], [False, False, False, True, True])

    def test_usa_cpu_int8_y_modelo_medium_por_defecto(self):
        transcripcion.transcribir(Path("x.mp3"), progreso=lambda m: None)
        self.assertEqual(_ModeloFalso.llamadas[0], ("init", "medium", "cpu", "int8"))

    def test_gpu_usa_large_v3_float16(self):
        with mock.patch.object(transcripcion, "hay_gpu", return_value=True):
            transcripcion.transcribir(Path("x.mp3"), progreso=lambda m: None)
        self.assertEqual(_ModeloFalso.llamadas[0], ("init", "large-v3", "cuda", "float16"))

    def test_opciones_para_cantos(self):
        transcripcion.transcribir(Path("x.mp3"), idioma="es", prompt="Aleluya", progreso=lambda m: None)
        opciones = _ModeloFalso.llamadas[1][2]
        self.assertTrue(opciones["word_timestamps"])
        self.assertFalse(opciones["condition_on_previous_text"])
        self.assertEqual((opciones["language"], opciones["initial_prompt"]), ("es", "Aleluya"))

    @unittest.skipIf(_PARAMETROS_REALES is None, "faster-whisper no instalado")
    def test_los_parametros_existen_en_faster_whisper_real(self):
        transcripcion.transcribir(Path("x.mp3"), progreso=lambda m: None)
        opciones = _ModeloFalso.llamadas[1][2]
        # El parche solo añade hallucination_silence_threshold si el modelo lo declara; el
        # modelo falso no lo declara, así que se comprueba el resto contra la firma real.
        self.assertEqual(set(opciones) - _PARAMETROS_REALES, set())
        self.assertIn("hallucination_silence_threshold", _PARAMETROS_REALES)

    def test_alucinaciones(self):
        self.assertTrue(transcripcion._es_alucinacion(" Subtítulos realizados por la comunidad de Amara.org"))
        self.assertTrue(transcripcion._es_alucinacion("¡Suscríbete!"))
        self.assertFalse(transcripcion._es_alucinacion("Tu amor me sostiene"))

    def test_sin_faster_whisper_el_error_es_claro(self):
        with mock.patch.dict(sys.modules, {"faster_whisper": None}):
            with self.assertRaisesRegex(RuntimeError, "faster-whisper"):
                transcripcion.transcribir(Path("x.mp3"), progreso=lambda m: None)


class SepararVoz(unittest.TestCase):
    def test_si_demucs_falla_se_usa_el_audio_original(self):
        mensajes = []
        fallo = types.SimpleNamespace(returncode=1, stderr="No module named demucs", stdout="")
        with mock.patch.object(transcripcion.subprocess, "run", return_value=fallo):
            voz = transcripcion.separar_voz(Path("c.mp3"), Path("/tmp"), mensajes.append)
        self.assertIsNone(voz)
        self.assertTrue(any("AVISO" in m for m in mensajes))


if __name__ == "__main__":
    unittest.main()


class CargarAudio(unittest.TestCase):
    @unittest.skipUnless(__import__("shutil").which("ffmpeg"), "ffmpeg no instalado")
    def test_decodifica_a_16khz_mono(self):
        import subprocess, tempfile
        with tempfile.TemporaryDirectory() as tmp:
            wav = Path(tmp) / "a.wav"
            subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i",
                            "sine=frequency=300:duration=2", str(wav)], check=True)
            datos = transcripcion.cargar_audio(wav)
        self.assertEqual(datos.dtype.name, "float32")
        self.assertAlmostEqual(len(datos) / 16000, 2.0, delta=0.05)

    def test_archivo_inexistente(self):
        with self.assertRaises(RuntimeError):
            transcripcion.cargar_audio(Path("no_existe.mp3"))
