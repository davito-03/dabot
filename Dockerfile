# Usamos una imagen de Python ligera para ahorrar recursos en el VPS
FROM python:3.11-slim

# Directorio de trabajo dentro del contenedor
WORKDIR /app

# Copiamos el archivo de requisitos (según tu captura se llama 'requirements')
COPY requirements.txt .

# ffmpeg + opus: voz/música. Si el VPS no lo aguanta, el cog avisa y no rompe el bot.
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg libopus0 \
    && rm -rf /var/lib/apt/lists/*

# Instalamos las librerías necesarias
RUN pip install --no-cache-dir -r requirements.txt

# Copiamos todo el contenido de tu carpeta /opt/dabot/ al contenedor
COPY . .

# Hacemos ejecutable el script de arranque
RUN chmod +x start.sh

# Comando para arrancar el bot y la API simultáneamente
CMD ["./start.sh"]
