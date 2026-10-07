# Generador de Letra de Canciones

Genera un video MP4 con la letra animada de una canción cristiana a partir de su audio
(título grande al inicio; a la derecha en blanco lo que viene, a la izquierda en amarillo lo que se canta).

```python
from generador_letras import generar_video_letra
generar_video_letra("cancion.mp3", titulo="Mi canción", letra="letra.txt", separar_voz=True)
```

```bash
pip install -r generador_letras/requirements.txt
python -m generador_letras cancion.mp3 --letra letra.txt
```

Documentación completa, guía para mejorar la precisión y formato del JSON: [generador_letras/README.md](generador_letras/README.md).
