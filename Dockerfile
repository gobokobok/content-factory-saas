FROM python:3.11-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg fonts-open-sans fonts-montserrat fonts-noto \
    && rm -rf /var/lib/apt/lists/*

# Poppins Bold is not available via apt — bundled in assets/fonts/ (see D035)
COPY assets/fonts/Poppins-Bold.ttf /usr/local/share/fonts/Poppins-Bold.ttf
RUN fc-cache -f /usr/local/share/fonts

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8000

COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh
ENTRYPOINT ["/entrypoint.sh"]
