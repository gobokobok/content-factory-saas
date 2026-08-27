FROM python:3.11-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg fonts-open-sans fonts-montserrat fonts-noto \
    && rm -rf /var/lib/apt/lists/*

# Poppins Bold, Titillium Web SemiBold, and Montserrat Bold are bundled in
# assets/fonts/ rather than resolved via fontconfig (see D035, D070, D075).
# Montserrat Bold is also the OST drawtext font (D074) — bundling it (instead
# of relying on the fonts-montserrat apt package still installed above, now
# otherwise unused) means render_worker.py's Python-side text-wrap width
# measurement (D075) reads the exact same font bytes ffmpeg renders with.
COPY assets/fonts/Poppins-Bold.ttf /usr/local/share/fonts/Poppins-Bold.ttf
COPY assets/fonts/TitilliumWeb-SemiBold.ttf /usr/local/share/fonts/TitilliumWeb-SemiBold.ttf
COPY assets/fonts/Montserrat-Bold.ttf /usr/local/share/fonts/Montserrat-Bold.ttf
RUN fc-cache -f /usr/local/share/fonts

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8000

COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh
ENTRYPOINT ["/entrypoint.sh"]
