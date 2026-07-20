FROM node AS build
WORKDIR /app/
COPY ./app/package.json .
COPY ./app/package-lock.json .
RUN npm install
COPY ./app/ .
ENV GENERATE_SOURCEMAP=false
RUN npm run build

FROM debian:stable-slim
RUN apt-get update && DEBIAN_FRONTEND="noninteractive" apt-get install -yqq \
    build-essential \
    python3 \
    python3-dev \
    python3-flask \
    python3-psycopg2 \
    pulseaudio \
    tigervnc-standalone-server \
    matchbox-window-manager \
    firefox-esr \
    socat \
    gstreamer1.0-tools \
    gstreamer1.0-plugins-base \
    gstreamer1.0-plugins-good \
    gstreamer1.0-plugins-bad \
    runit && rm -rf /var/lib/apt/lists/*
RUN echo "load-module module-simple-protocol-tcp listen=127.0.0.1 format=s16le channels=2 rate=48000 record=true playback=false" > /etc/pulse/default.pa.d/simple-protocol.pa

# Install NERDS Firefox extension for ChatGPT prompt logging - updated to .xpi to avoid firefox not installing extension. still need to sign
COPY ./firefox-extension/chatgpt-prompt-logger.xpi /opt/chatgpt-prompt-logger.xpi
COPY ./firefox-policies/policies.json /usr/lib/firefox-esr/distribution/policies.json

RUN useradd -m --shell=/usr/bin/nologin user
WORKDIR /home/user

# Setup EMSDK. emcc finds its bundled node via /emsdk/.emscripten, so no
# node paths need to be hardcoded here. EM_CACHE points at a directory the
# unprivileged user can write to, since /emsdk is root-owned.
COPY --from=emscripten/emsdk /emsdk /emsdk
ENV EMSDK=/emsdk \
    EM_CACHE=/home/user/.emscripten_cache \
    PATH="/emsdk:/emsdk/upstream/emscripten:/emsdk/upstream/bin:${PATH}"

#ADD https://deb.nodesource.com/setup_16.x /home/user/
#RUN bash setup_16.x && apt-get install -y nodejs

#ADD https://dl.google.com/linux/direct/google-chrome-stable_current_amd64.deb /home/user
#RUN apt install -y ./google-chrome-stable_current_amd64.deb

#ADD https://github.com/novnc/noVNC/archive/refs/tags/v1.3.0.tar.gz /home/user/
USER user
ADD --chown=user:user https://github.com/novnc/websockify/archive/refs/tags/v0.10.0.tar.gz ./websockify.tar.gz
RUN tar -xf websockify.tar.gz \
    && rm websockify.tar.gz
RUN cd websockify-0.10.0 && make
#RUN tar -xf v1.3.0.tar.gz && chown -R user:user /home/user && mkdir app
#COPY --chown=user:user ./app/package.json ./app/
#RUN chown user:user app/
#RUN cd app && npm install

COPY --chown=user:user ./audio-proxy.sh .
COPY ./token.cfg /etc/websockify/token.cfg

COPY --chown=user:user ./testing ./testing
# Starting code for the three coding tasks, served by /api/tasks
COPY --chown=user:user ./read.c ./write.c ./fix.c ./tasks/
COPY --chown=user:user ./services ./services

# Warm the emscripten cache (system libs for the exact flags /api/compile
# uses) so the first user-triggered compile doesn't take minutes.
RUN emcc -I testing tasks/read.c testing/test_username.c -o /tmp/warmup.js \
    -std=c11 -fsanitize=undefined -fsanitize-minimal-runtime \
    -sSINGLE_FILE=1 -sEXIT_RUNTIME=1 -sSAFE_HEAP=1 -sASSERTIONS=1 \
    -sENVIRONMENT=web \
    "-sINCOMING_MODULE_JS_API=print,printErr,onExit,onAbort" \
    && rm /tmp/warmup.js
#COPY --chown=user:user ./app/ ./app/
#WORKDIR /home/user/app
COPY --chown=user:user ./firefox.py .
COPY --chown=user:user ./instance-api.py .
COPY ./config.py .
COPY --from=build --chown=user:user /app/build /home/user/www
#RUN cd /home/user/app && \
#    npm run build && \
#    mkdir /home/user/www && \
#    cp -vr /home/user/app/build/* /home/user/www/

CMD ["/usr/bin/runsvdir", "/home/user/services"]
#CMD ["/bin/sh",
#    "Xvfb :1 -screen -o 1280x720x16",
#    "x11vnc -display :1.0 &",
#    "DISPLAY=:1.0 firefox &"]

#Xvfb :1 -screen 0 800x600x16
#x11vnc -display :1.0
#DISPLAY=:1.0 google-chrome-stable
