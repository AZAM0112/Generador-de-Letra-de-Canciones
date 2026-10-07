import unittest

from generador_letras.modelos import Palabra, Verso
from generador_letras.segmentacion import (
    limpiar_texto, palabras_a_versos, versos_a_paginas,
)


def hablar(texto, inicio, paso=0.4):
    """Palabras consecutivas de `texto` empezando en `inicio` (sin pausas internas)."""
    palabras = []
    for i, w in enumerate(texto.split()):
        palabras.append(Palabra(w, inicio + i * paso, inicio + i * paso + paso * 0.9))
    return palabras


class PalabrasAVersos(unittest.TestCase):
    def test_una_pausa_separa_versos(self):
        ps = hablar("Tu amor me sostiene", 0) + hablar("Tu paz me guarda", 5)
        versos = palabras_a_versos(ps)
        self.assertEqual([v.texto for v in versos], ["Tu amor me sostiene", "Tu paz me guarda"])
        self.assertAlmostEqual(versos[1].inicio, 5.0)

    def test_puntuacion_fuerte_corta_aunque_no_haya_pausa(self):
        ps = hablar("Eres fiel. Eres bueno", 0)
        self.assertEqual([v.texto for v in palabras_a_versos(ps)], ["Eres fiel", "Eres bueno"])

    def test_tramo_largo_se_divide_en_la_pausa_mas_grande(self):
        ps = hablar("Santo santo santo es el Señor", 0) + hablar("Dios todopoderoso", 3.0, 0.5)
        # Sin pausa >= 0.8 s entre ellas: la pausa de 0.5 s (< PAUSA_VERSO) no corta,
        # pero el tramo supera el máximo y debe dividirse allí.
        ps2 = hablar("Santo santo santo es el Señor", 0) + hablar("Dios todopoderoso hoy", 2.9, 0.3)
        versos = palabras_a_versos(ps2)
        self.assertEqual(versos[0].texto, "Santo santo santo es el Señor")
        self.assertEqual(versos[1].texto, "Dios todopoderoso hoy")
        for v in palabras_a_versos(ps):
            self.assertLessEqual(v.num_palabras, 8)

    def test_no_deja_una_palabra_suelta_al_dividir(self):
        ps = hablar("uno dos tres cuatro cinco seis siete ocho nueve", 0, 0.1)  # 9 palabras
        versos = palabras_a_versos(ps)
        self.assertGreater(len(versos), 1)
        self.assertTrue(all(v.num_palabras >= 2 for v in versos))

    def test_cortar_por_pausa_false_respeta_las_lineas_del_usuario(self):
        ps = hablar("Tu amor me sostiene", 0) + hablar("en la tormenta", 10)
        ps[3].corte = True  # fin de la línea 1
        versos = palabras_a_versos(ps[:3] + [ps[3]] + ps[4:], cortar_por_pausa=False)
        self.assertEqual([v.texto for v in versos], ["Tu amor me sostiene", "En la tormenta"])

    def test_limpiar_texto(self):
        self.assertEqual(limpiar_texto("  jesús, "), "Jesús")
        self.assertEqual(limpiar_texto("¿quién como tú?"), "¿Quién como tú?")
        self.assertEqual(limpiar_texto("¡aleluya!"), "¡Aleluya!")


class VersosAPaginas(unittest.TestCase):
    def v(self, texto, ini, fin, nueva=False):
        return Verso(texto, ini, fin, nueva)

    def test_maximo_dos_versos_por_pagina(self):
        versos = [self.v(f"verso numero {i}", i * 3, i * 3 + 2) for i in range(5)]
        paginas = versos_a_paginas(versos)
        self.assertEqual([len(p.versos) for p in paginas], [2, 2, 1])

    def test_una_palabra_va_sola(self):
        versos = [
            self.v("Tu gloria llena la tierra", 0, 3),
            self.v("Jesús", 4, 5),
            self.v("Jesús", 6, 7),
            self.v("Eres digno de alabanza", 8, 11),
            self.v("Mi alma te bendice", 12, 14),
        ]
        paginas = versos_a_paginas(versos)
        self.assertEqual(
            [[v.texto for v in p.versos] for p in paginas],
            [["Tu gloria llena la tierra"], ["Jesús"], ["Jesús"],
             ["Eres digno de alabanza", "Mi alma te bendice"]],
        )

    def test_pausa_larga_abre_pagina_nueva(self):
        versos = [self.v("primer verso", 0, 2), self.v("segundo verso", 10, 12)]
        self.assertEqual(len(versos_a_paginas(versos)), 2)

    def test_salto_de_estrofa_abre_pagina_nueva(self):
        versos = [self.v("primer verso", 0, 2), self.v("segundo verso", 2.5, 4, nueva=True)]
        self.assertEqual(len(versos_a_paginas(versos)), 2)

    def test_pagina_expone_inicio_y_fin(self):
        pagina = versos_a_paginas([self.v("a b", 1, 2), self.v("c d", 2.5, 4)])[0]
        self.assertEqual((pagina.inicio, pagina.fin), (1, 4))


if __name__ == "__main__":
    unittest.main()
