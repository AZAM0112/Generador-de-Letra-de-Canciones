import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from generador_letras import generar_video_letra, titulo_desde_nombre
from generador_letras.modelos import Palabra, Verso, cargar_json, guardar_json
from generador_letras.render import Escena, duracion_audio
from generador_letras.segmentacion import versos_a_paginas

HAY_FFMPEG = shutil.which("ffmpeg") is not None

VERSOS = [
    Verso("Tu amor me sostiene", 6.0, 8.0),
    Verso("Tu paz me guarda", 8.5, 10.0),
    Verso("Jesús", 14.0, 15.0),
]


def escena(lead_in=0.0, ancho=640, alto=360):
    return Escena(
        "Mi canción", versos_a_paginas(VERSOS), ancho=ancho, alto=alto,
        fuente=None, fondo=(0, 0, 0), lead_in=lead_in,
    )


def maximos(img, mitad):
    """(R, G, B) máximos de la mitad 'izq'/'der' del fotograma, o None si está vacía."""
    w, h = img.size
    caja = (0, 0, w // 2, h) if mitad == "izq" else (w // 2, 0, w, h)
    zona = img.crop(caja)
    return None if zona.getbbox() is None else tuple(b for _, b in zona.getextrema())


class EscenaVisual(unittest.TestCase):
    def test_titulo_grande_y_centrado_al_inicio(self):
        img = escena().fotograma(0.5)
        x0, y0, x1, y1 = img.getbbox()
        self.assertLess(abs((x0 + x1) / 2 - img.width / 2), 5)
        self.assertLess(abs((y0 + y1) / 2 - img.height / 2), 10)
        self.assertGreater(x1 - x0, img.width * 0.3)  # grande

    def test_antes_de_cantar_lo_que_viene_esta_a_la_derecha_en_blanco(self):
        img = escena().fotograma(5.0)  # título ya salió; primera página en vista previa
        self.assertIsNone(maximos(img, "izq"))
        self.assertEqual(maximos(img, "der"), (255, 255, 255))

    def test_al_cantar_pasa_a_la_izquierda_en_amarillo_y_aparece_lo_siguiente(self):
        img = escena().fotograma(7.0)
        r, g, b = maximos(img, "izq")
        self.assertGreater(r, 250)
        self.assertGreater(g, 200)
        self.assertLess(b, 10)  # amarillo
        self.assertEqual(maximos(img, "der"), (255, 255, 255))  # "Jesús" esperando

    def test_una_palabra_se_muestra_sola(self):
        img = escena().fotograma(14.5)
        self.assertEqual(len(versos_a_paginas(VERSOS)[-1].versos), 1)
        self.assertIsNotNone(maximos(img, "izq"))
        self.assertIsNone(maximos(img, "der"))  # no se agregan más versos

    def test_durante_el_desplazamiento_esta_en_el_centro_con_color_intermedio(self):
        e = escena()
        t = e.t_in[0] + e.dur[0] / 2
        (k, x, _, color, alpha) = [o for o in e.operaciones(t) if o[0] == 0][0]
        centro = x + e.bloques[0].width / 2
        self.assertLess(abs(centro - e.ancho / 2), 30)
        self.assertTrue(0 < color[2] < 255)  # entre blanco y amarillo

    def test_lo_cantado_se_va_si_no_viene_nada_pronto(self):
        img = escena().fotograma(12.5)  # >1.5 s después de acabar la 2ª página, antes de "Jesús"
        self.assertIsNone(maximos(img, "izq"))
        self.assertEqual(maximos(img, "der"), (255, 255, 255))

    def test_fotogramas_quietos_tienen_la_misma_clave(self):
        e = escena()
        self.assertEqual(e.operaciones(7.0), e.operaciones(7.2))


class Titulo(unittest.TestCase):
    def test_titulo_desde_nombre_de_archivo(self):
        self.assertEqual(titulo_desde_nombre("/x/01_cuan_grande_es_dios.mp3"), "Cuan Grande Es Dios")
        self.assertEqual(titulo_desde_nombre("Tu Fidelidad.wav"), "Tu Fidelidad")


class Json(unittest.TestCase):
    def test_ida_y_vuelta(self):
        with tempfile.TemporaryDirectory() as tmp:
            ruta = Path(tmp) / "l.json"
            guardar_json(ruta, "Jesús", [Verso("Hola", 1, 2, True), Verso("Mundo", 3, 4)])
            titulo, versos = cargar_json(ruta)
        self.assertEqual(titulo, "Jesús")
        self.assertEqual([(v.texto, v.pagina_nueva) for v in versos], [("Hola", True), ("Mundo", False)])

    def test_json_invalido(self):
        with tempfile.TemporaryDirectory() as tmp:
            ruta = Path(tmp) / "l.json"
            ruta.write_text(json.dumps({"versos": [{"inicio": 5, "fin": 1, "texto": "x"}]}))
            with self.assertRaises(ValueError):
                cargar_json(ruta)


@unittest.skipUnless(HAY_FFMPEG, "ffmpeg no instalado")
class VideoMp4(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.dir = Path(cls.tmp.name)
        cls.audio = cls.dir / "mi_cancion.wav"
        subprocess.run(
            ["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "sine=frequency=300:duration=12",
             str(cls.audio)], check=True,
        )

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_genera_mp4_con_audio_y_lead_in_si_la_voz_entra_pronto(self):
        guardar_json(self.dir / "l.json", "Mi canción", [Verso("Tu amor me sostiene", 1.0, 3.0)])
        salida = generar_video_letra(
            self.audio, desde_json=self.dir / "l.json", salida=self.dir / "v.mp4",
            resolucion=(320, 180), fps=10, progreso=lambda m: None,
        )
        self.assertEqual(salida, self.dir / "v.mp4")
        # La voz entraba a 1 s: se antepone un silencio para que el título se vea (12 s + 4.5 s).
        self.assertAlmostEqual(duracion_audio(salida), 12 + 4.5, delta=0.3)
        info = subprocess.run(["ffmpeg", "-hide_banner", "-i", str(salida)], capture_output=True, text=True).stderr
        self.assertIn("Video: h264", info)
        self.assertIn("Audio: aac", info)
        self.assertIn("320x180", info)

    def test_sin_letra_da_error_claro(self):
        guardar_json(self.dir / "vacio.json", "x", [])
        with self.assertRaisesRegex(ValueError, "No hay letra"):
            generar_video_letra(
                self.audio, desde_json=self.dir / "vacio.json", salida=self.dir / "n.mp4",
                resolucion=(320, 180), fps=10, progreso=lambda m: None,
            )

    def test_flujo_completo_con_letra_del_usuario_y_transcripcion_simulada(self):
        detectadas = [
            Palabra("tu", 1.0, 1.3), Palabra("amor", 1.3, 1.8), Palabra("me", 1.8, 2.0),
            Palabra("sostiene", 2.0, 3.5, corte=True), Palabra("jesus", 6.0, 7.0, corte=True),
        ]
        letra = self.dir / "letra.txt"
        letra.write_text("Tu amor me sostiene\n\nJesús\n", encoding="utf-8")
        with mock.patch(
            "generador_letras.transcripcion.transcribir_audio_cancion", return_value=detectadas
        ):
            salida = generar_video_letra(
                self.audio, "Tu amor", self.dir / "f.mp4", letra=letra,
                resolucion=(320, 180), fps=10, progreso=lambda m: None,
            )
        self.assertTrue(salida.exists())
        titulo, versos = cargar_json(self.dir / "f.letra.json")
        self.assertEqual(titulo, "Tu amor")
        self.assertEqual([v.texto for v in versos], ["Tu amor me sostiene", "Jesús"])
        self.assertAlmostEqual(versos[1].inicio, 6.0)

    def test_solo_json_no_crea_video(self):
        detectadas = [Palabra("Tu", 1, 2), Palabra("amor.", 2, 3, corte=True)]
        with mock.patch(
            "generador_letras.transcripcion.transcribir_audio_cancion", return_value=detectadas
        ):
            ruta = generar_video_letra(
                self.audio, salida=self.dir / "s.mp4", solo_json=True, progreso=lambda m: None
            )
        self.assertEqual(ruta, self.dir / "s.letra.json")
        self.assertFalse((self.dir / "s.mp4").exists())
        self.assertEqual(cargar_json(ruta)[0], "Mi Cancion")

    def test_audio_inexistente(self):
        with self.assertRaises(FileNotFoundError):
            generar_video_letra(self.dir / "no_existe.mp3")


if __name__ == "__main__":
    unittest.main()
