import unittest

from generador_letras.coros import armonizar_repeticiones
from generador_letras.modelos import Verso


def coro(inicio, distancia=4.0, conf_a=1.0, conf_b=1.0):
    a = Verso("Santo es el Señor", inicio, inicio + 3)
    b = Verso("digno de alabar", inicio + distancia, inicio + distancia + 3)
    a.confianza, b.confianza = conf_a, conf_b
    return [a, b]


class Repeticiones(unittest.TestCase):
    def test_corrige_con_las_otras_repeticiones_un_verso_no_escuchado(self):
        versos = coro(10) + coro(30) + coro(50, distancia=6.5, conf_b=0.0)
        versos[-1].revisar = "no se reconoció en el audio: tiempo estimado"
        n = armonizar_repeticiones(versos, progreso=lambda m: None)
        self.assertEqual(n, 1)
        self.assertAlmostEqual(versos[-1].inicio, 54.0)
        self.assertEqual(versos[-1].revisar, "")
        self.assertAlmostEqual(versos[-1].fin - versos[-1].inicio, 3.0)

    def test_tambien_corrige_hacia_atras(self):
        versos = coro(10) + coro(30) + coro(50, conf_a=0.0)
        versos[4].inicio = 47.0  # el primer verso del 3er coro quedó lejos
        armonizar_repeticiones(versos, progreso=lambda m: None)
        self.assertAlmostEqual(versos[4].inicio, 50.0)

    def test_un_verso_bien_escuchado_que_no_coincide_se_marca_pero_no_se_mueve(self):
        versos = coro(10) + coro(30) + coro(50, distancia=6.0)
        armonizar_repeticiones(versos, progreso=lambda m: None)
        self.assertAlmostEqual(versos[-1].inicio, 56.0)
        self.assertIn("repeticiones", versos[-1].revisar)

    def test_sin_repeticiones_no_cambia_nada(self):
        versos = [Verso("uno dos", 1, 2), Verso("tres cuatro", 3, 4)]
        self.assertEqual(armonizar_repeticiones(versos, progreso=lambda m: None), 0)
        self.assertEqual([v.revisar for v in versos], ["", ""])

    def test_no_desordena_los_versos(self):
        versos = coro(10) + coro(30) + coro(50, conf_b=0.0)
        versos[-1].inicio = 52.0
        versos.append(Verso("puente", 53.5, 54.5))  # moverlo a 54 lo pondría después del puente
        armonizar_repeticiones(versos, progreso=lambda m: None)
        inicios = [v.inicio for v in versos]
        self.assertEqual(inicios, sorted(inicios))
        self.assertEqual(versos[5].inicio, 52.0)

    def test_las_correcciones_se_encadenan(self):
        # Tres versos repetidos; en la 3ª repetición los dos últimos no se escucharon.
        def bloque(t, c2=1.0, c3=1.0):
            vs = [Verso("primera linea", t, t + 2), Verso("segunda linea", t + 3, t + 5),
                  Verso("tercera linea", t + 6, t + 8)]
            vs[1].confianza, vs[2].confianza = c2, c3
            return vs
        versos = bloque(10) + bloque(30) + bloque(50, c2=0.0, c3=0.0)
        versos[7].inicio, versos[8].inicio = 51.0, 59.0
        armonizar_repeticiones(versos, progreso=lambda m: None)
        self.assertAlmostEqual(versos[7].inicio, 53.0)
        self.assertAlmostEqual(versos[8].inicio, 56.0)


if __name__ == "__main__":
    unittest.main()
