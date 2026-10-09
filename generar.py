"""Atajo: `py -3.12 generar.py` procesa todas las canciones de la carpeta `canciones/`."""
import sys

from generador_letras.lote import main

if __name__ == "__main__":
    sys.exit(main())
