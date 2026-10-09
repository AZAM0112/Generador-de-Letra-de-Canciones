import tempfile
import unittest
from pathlib import Path
from unittest import mock

from generador_letras import lote


class Lote(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.addCleanup(self.tmp.cleanup)
        for nombre in ("A.mp3", "A.txt", "B.mp3", "C.mp3", "C_letra.letra.json", "D.mp3", "D_letra.mp4", "nota.pdf"):
            (self.dir / nombre).write_bytes(b"x")

    def correr(self, **kw):
        with mock.patch.object(lote, "generar_video_letra") as g:
            fallidas = lote.procesar_carpeta(self.dir, progreso=lambda m: None, **kw)
        return g, fallidas

    def test_elige_letra_json_o_nada_y_salta_los_ya_hechos(self):
        g, fallidas = self.correr()
        self.assertEqual(fallidas, [])
        llamadas = {c.args[0].name: c.kwargs for c in g.call_args_list}
        self.assertEqual(set(llamadas), {"A.mp3", "B.mp3", "C.mp3"})  # D ya tenía video
        self.assertEqual(llamadas["A.mp3"]["letra"], self.dir / "A.txt")
        self.assertIsNone(llamadas["B.mp3"]["letra"])
        self.assertEqual(llamadas["C.mp3"]["desde_json"], self.dir / "C_letra.letra.json")

    def test_forzar_rehace_tambien_los_existentes(self):
        g, _ = self.correr(forzar=True)
        self.assertIn("D.mp3", [c.args[0].name for c in g.call_args_list])

    def test_un_error_no_detiene_a_las_demas(self):
        with mock.patch.object(lote, "generar_video_letra", side_effect=[RuntimeError("x"), None, None]):
            fallidas = lote.procesar_carpeta(self.dir, progreso=lambda m: None)
        self.assertEqual(fallidas, ["A.mp3"])

    def test_carpeta_inexistente(self):
        with self.assertRaises(FileNotFoundError):
            lote.procesar_carpeta(self.dir / "no", progreso=lambda m: None)


if __name__ == "__main__":
    unittest.main()
