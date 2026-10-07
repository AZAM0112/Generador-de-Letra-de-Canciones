import unittest

from generador_letras.alineacion import (
    alinear_letra, leer_letra, normalizar, palabras_clave_para_prompt,
)
from generador_letras.modelos import Palabra


def hablar(texto, inicio, paso=0.5):
    return [
        Palabra(w, inicio + i * paso, inicio + i * paso + paso * 0.9)
        for i, w in enumerate(texto.split())
    ]


class LeerLetra(unittest.TestCase):
    def test_lineas_estrofas_y_marcadores(self):
        letra = "[Verso 1]\nTu amor me sostiene\nen la tormenta\n\n[Coro]\nJesús\n"
        ps = leer_letra(letra)
        self.assertEqual([p.texto for p in ps], "Tu amor me sostiene en la tormenta Jesús".split())
        # Cierran verso: "sostiene", "tormenta" y "Jesús".
        self.assertEqual([p.corte for p in ps], [False, False, False, True, False, False, True, True])
        self.assertEqual([p.pagina_nueva for p in ps].count(True), 1)  # solo "Jesús" abre estrofa
        self.assertTrue(ps[-1].pagina_nueva)
        self.assertFalse(ps[0].pagina_nueva)

    def test_normalizar(self):
        self.assertEqual(normalizar("¡Jesús,"), "jesus")
        self.assertEqual(normalizar("Señor"), normalizar("senor"))

    def test_prompt_usa_vocabulario_sin_repetir(self):
        texto = "Aleluya aleluya Santo, santo es el Señor Altísimo"
        self.assertEqual(palabras_clave_para_prompt(texto), "Aleluya, Santo, Señor, Altísimo")


class AlinearLetra(unittest.TestCase):
    LETRA = "Tu amor me sostiene\nen la tormenta\nJesús\nTu paz me guarda\ncada día"

    def test_asigna_los_tiempos_del_audio(self):
        det = hablar("Tu amor me sostiene en la tormenta", 10) + hablar("Jesús", 20) \
            + hablar("Tu paz me guarda cada día", 30)
        ps = alinear_letra(self.LETRA, det, progreso=lambda m: None)
        self.assertEqual(len(ps), 14)
        self.assertAlmostEqual(ps[0].inicio, 10.0)  # "Tu"
        self.assertAlmostEqual(ps[7].inicio, 20.0)  # "Jesús"
        self.assertAlmostEqual(ps[8].inicio, 30.0)  # "Tu" (segundo bloque)

    def test_tolera_errores_de_whisper(self):
        # "sostiene" -> "sostiné", "tormenta" omitida, palabra inventada "yo", sin tildes
        det = hablar("Tu amor me sostiné en la", 10) + hablar("yo", 13.2) + hablar("jesus", 20) \
            + hablar("Tu paz me guarda cada dia", 30)
        ps = alinear_letra(self.LETRA, det, progreso=lambda m: None)
        self.assertAlmostEqual(ps[3].inicio, 11.5)  # "sostiene" casó con "sostiné"
        self.assertAlmostEqual(ps[7].inicio, 20.0)  # "Jesús" casó con "jesus"
        self.assertAlmostEqual(ps[13].inicio, 32.5)  # "día" casó con "dia"
        # "tormenta" no se detectó: queda entre "la" y lo siguiente, sin salirse de orden
        self.assertGreater(ps[6].inicio, ps[5].inicio)
        self.assertLessEqual(ps[6].inicio, ps[7].inicio)

    def test_tiempos_siempre_en_orden(self):
        det = hablar("Tu amor", 5) + hablar("Jesús", 40) + hablar("cada día", 50)
        ps = alinear_letra(self.LETRA, det, progreso=lambda m: None)
        inicios = [p.inicio for p in ps]
        self.assertEqual(inicios, sorted(inicios))
        self.assertTrue(all(p.fin >= p.inicio for p in ps))

    def test_coro_repetido_se_alinea_cada_vez(self):
        letra = "Aleluya canto a ti\nJesús\nAleluya canto a ti\nJesús"
        det = hablar("Aleluya canto a ti", 0) + hablar("Jesús", 5) \
            + hablar("Aleluya canto a ti", 20) + hablar("Jesús", 25)
        ps = alinear_letra(letra, det, progreso=lambda m: None)
        self.assertAlmostEqual(ps[5].inicio, 20.0)
        self.assertAlmostEqual(ps[9].inicio, 25.0)

    def test_avisa_si_se_reconoce_menos_de_la_mitad(self):
        mensajes = []
        det = hablar("Jesús", 3) + hablar("cosas que no existen en la letra", 5)
        alinear_letra(self.LETRA, det, progreso=mensajes.append)
        self.assertTrue(any("AVISO" in m for m in mensajes))

    def test_errores_claros(self):
        with self.assertRaises(ValueError):
            alinear_letra("", hablar("hola", 0))
        with self.assertRaises(ValueError):
            alinear_letra(self.LETRA, [])
        with self.assertRaises(ValueError):
            alinear_letra(self.LETRA, hablar("xxxx yyyy zzzz", 0), progreso=lambda m: None)


if __name__ == "__main__":
    unittest.main()
