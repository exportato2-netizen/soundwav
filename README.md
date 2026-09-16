# Soundwav

Herramienta local para Windows que descarga playlists o pistas públicas de SoundCloud con `yt-dlp` y genera archivos WAV PCM limpios.

## Versión 1.3

La salida final ya no depende de ejecutar manualmente un parche externo. `app.py` es la entrada segura y carga el núcleo interno con la capa de limpieza obligatoria. Incluso `_core_app.py` actúa únicamente como cargador protegido: si se ejecuta directamente, redirige a la entrada segura.

Cada pista se procesa así:

1. El archivo fuente se descarga a una carpeta temporal privada bajo `%LOCALAPPDATA%\soundwav\temp`.
2. FFmpeg convierte el primer stream de audio a PCM 16 o 24 bits sin copiar metadatos ni capítulos.
3. La aplicación reconstruye el contenedor RIFF y conserva únicamente los chunks `fmt ` y `data`.
4. Solo después de verificar esa estructura, el WAV limpio se mueve a `%USERPROFILE%\Music\WAV_Descargas`.
5. El archivo fuente y los temporales se eliminan.

El nombre final no contiene el ID del extractor. Ejemplo:

```text
001 - Nombre de la pista.wav
```

## Uso

1. Descarga o clona este repositorio.
2. Ejecuta `launcher.bat` en Windows 10 u 11.
3. Si no hay Python 3.11 o superior, el lanzador intentará instalar Python automáticamente.
4. Pega una URL pública de SoundCloud.
5. Elige WAV PCM 24 o 16 bits y pulsa **Descargar**.

## Privacidad de los WAV

La aplicación elimina del archivo final tags y chunks auxiliares como `LIST/INFO`, `BEXT`, `iXML`, carátulas, capítulos, comentarios, URL, artista/álbum heredados e identificadores del software de conversión. Para PCM generado por esta aplicación, el WAV final se verifica para que contenga solo `fmt ` y `data`.

Esto no modifica el contenido audible de la fuente salvo la conversión necesaria a PCM. No intenta eliminar marcas acústicas o información que forme parte del propio audio.

El historial de descargas y el registro de actividad son datos internos de la aplicación y se guardan fuera de la carpeta de música:

```text
%LOCALAPPDATA%\soundwav
```

## Actualizar componentes

Ejecuta `ACTUALIZAR.bat`. El script siempre llama primero a `launcher.bat --setup-only`, por lo que también repara un entorno `.venv` existente que haya quedado dañado o ligado a un Python incompatible, y después actualiza las dependencias sin abrir la aplicación.

## Requisitos

- Windows 10 u 11.
- Conexión a Internet durante la instalación inicial y las descargas.
- Python 3.11 o superior; `launcher.bat` intenta instalar Python 3.14 automáticamente si hace falta.
- El instalador de respaldo contempla Windows x86, x64 y ARM64.

## Archivos principales

- `app.py`: entrada segura de la aplicación.
- `privacy_patch.py`: conversión, aislamiento temporal y verificación de limpieza.
- `_core_app.py`: cargador interno protegido.
- `_core_app.src`: código del núcleo cargado internamente; no es el punto de entrada de uso normal.
- `launcher.bat`: preparación automática y arranque.
- `ACTUALIZAR.bat`: reparación del entorno y actualización manual de dependencias.
- `requirements.txt`: dependencias de Python.
- `LEEME_PRIMERO.txt`: instrucciones rápidas.

## Uso responsable

Utiliza esta herramienta únicamente con contenido propio, con autorización del titular o cuando la legislación aplicable permita la descarga. No está diseñada para evadir DRM, cuentas privadas ni controles de acceso.
