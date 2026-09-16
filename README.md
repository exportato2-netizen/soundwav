# SoundCloud → WAV

Herramienta local para Windows que descarga playlists o pistas públicas de SoundCloud usando `yt-dlp` y convierte cada pista a WAV PCM mediante FFmpeg incluido por `imageio-ffmpeg`.

## Características

- Descarga playlists completas o pistas individuales.
- Selecciona el mejor audio disponible que SoundCloud entregue a `yt-dlp`.
- Conversión a WAV PCM de 24 o 16 bits.
- Mantiene el orden de la playlist y crea carpetas por playlist.
- Historial para evitar descargar dos veces lo ya completado.
- Opción para volver a descargar todo.
- Reintentos ante errores temporales.
- Cancelación de descargas desde la interfaz.
- Registro persistente de actividad.
- Interfaz web local en `127.0.0.1` con selección automática de puerto.
- Instalación automática de Python compatible cuando sea necesaria.
- No requiere instalar FFmpeg manualmente.

## Uso rápido

1. Descarga o clona este repositorio.
2. En Windows 10 u 11, ejecuta `launcher.bat`.
3. El lanzador comprobará Python y preparará automáticamente el entorno local `.venv`.
4. Se abrirá la interfaz en el navegador.
5. Pega una URL pública de SoundCloud y pulsa **Descargar playlist**.

Los archivos se guardan por defecto en:

```text
%USERPROFILE%\Music\SoundCloud_WAV
```

El registro persistente se guarda en:

```text
%USERPROFILE%\Music\SoundCloud_WAV\actividad.log
```

## Actualizar componentes

Ejecuta `ACTUALIZAR.bat`. Las dependencias no se actualizan en cada inicio normal para reducir tiempos de arranque y evitar introducir una versión recién publicada inesperadamente.

## Requisitos

- Windows 10 u 11.
- Conexión a Internet para la instalación inicial y las descargas.
- Python 3.11 o superior; si no está disponible, `launcher.bat` intenta instalar Python automáticamente.

## Calidad de audio

Convertir AAC, Opus o MP3 a WAV evita introducir una nueva compresión con pérdida durante la conversión, pero **no recupera información que ya haya sido eliminada por la compresión de SoundCloud**. WAV de 24 bits no transforma una fuente comprimida en un máster real de 24 bits.

La aplicación solicita a `yt-dlp` el mejor audio disponible y convierte después el archivo recibido a WAV PCM.

## Archivos principales

- `app.py`: aplicación e interfaz local.
- `launcher.bat`: instalación/preparación automática y arranque.
- `ACTUALIZAR.bat`: actualización manual de dependencias.
- `requirements.txt`: dependencias de Python.
- `LEEME_PRIMERO.txt`: instrucciones rápidas para Windows.

## Uso responsable

Utiliza esta herramienta únicamente con contenido propio, con autorización del titular o cuando la legislación aplicable permita la descarga. El programa no está diseñado para evadir DRM, cuentas privadas ni controles de acceso.
