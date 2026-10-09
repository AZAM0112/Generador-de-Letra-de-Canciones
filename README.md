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

## Forma rápida: una carpeta y un solo comando

1. Pon en la carpeta `canciones/` el audio y su letra **con el mismo nombre**:
   `Tómalo - Hillsong.mp3` y `Tómalo - Hillsong.txt`.
2. Ejecuta (o en VS Code: **Ctrl+Shift+B**, usa el archivo `.vscode/tasks.json`):
   ```
   py -3.12 generar.py
   ```
3. Se crean junto al audio `..._letra.letra.json` (letra con tiempos) y `..._letra.mp4`.
4. Si corriges el JSON, rehaz el video con `py -3.12 generar.py --forzar`: usa el JSON, no vuelve a transcribir.
   (Para transcribir de nuevo, borra el JSON.)

Para rehacer **una sola** canción: `py -3.12 generar.py --forzar --cancion tomalo` (basta con parte del nombre, sin importar tildes ni mayúsculas).

Las canciones que ya tienen video se omiten; una canción con error no detiene a las demás.

## Con GitHub (sin instalar nada en tu PC)

1. Sube a `canciones/` el audio y la letra (desde la web: **Add file → Upload files**).
2. Ve a la pestaña **Actions → Generar videos de letras → Run workflow** (elige el modelo).
3. Al terminar, descarga el resultado en **Artifacts → videos-de-letras** (MP4 y JSON).
4. Para corregir tiempos: edita el JSON en tu PC, súbelo a `canciones/` y ejecuta el workflow con *forzar* activado.

Notas: usa un repositorio **privado** si subes audios con derechos de autor. En GitHub el
procesamiento es solo con CPU y una canción puede tardar varios minutos (el límite del trabajo es 4 h).
