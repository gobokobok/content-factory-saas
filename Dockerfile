# Pinned to a patch release and its manifest digest (F20) so a rebuild cannot pick up a
# different base image. Bump both together; the digest comes from Docker Hub's tag list.
FROM python:3.11.17-slim-trixie@sha256:e88e9763f943ec1834f992a4b51e0f24500486803e8bc534e5767af9ea65f6ce

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
# Barlow Condensed Bold is the Punch caption face (D084).
COPY assets/fonts/BarlowCondensed-Bold.ttf /usr/local/share/fonts/BarlowCondensed-Bold.ttf
RUN fc-cache -f /usr/local/share/fonts

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8000

COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

# Run as an unprivileged user (F20). The app writes only under /tmp (render working
# folders) and its home directory (model caches), so nothing needs root at run time.
RUN useradd --create-home --uid 10001 app \
    && chown -R app:app /app
USER app

ENTRYPOINT ["/entrypoint.sh"]
