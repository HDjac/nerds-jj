FROM node AS build
ARG REACT_APP_NERDS_CLIPBOARD_INGEST=0
ARG REACT_APP_NERDS_CLIPBOARD_TEXT=0
ARG REACT_APP_NERDS_SPLIT_WORKSPACE=0
ENV REACT_APP_NERDS_CLIPBOARD_INGEST=${REACT_APP_NERDS_CLIPBOARD_INGEST}
ENV REACT_APP_NERDS_CLIPBOARD_TEXT=${REACT_APP_NERDS_CLIPBOARD_TEXT}
ENV REACT_APP_NERDS_SPLIT_WORKSPACE=${REACT_APP_NERDS_SPLIT_WORKSPACE}
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
    clang \
    libclang-rt-dev \
    xterm \
    xfonts-base \
    unzip \
    wmctrl \
    x11-utils \
    python3 \
    python3-dev \
    python3-flask \
    python3-psycopg2 \
    pulseaudio \
    tigervnc-standalone-server \
    matchbox-window-manager \
    openbox \
    firefox-esr \
    socat \
    gstreamer1.0-tools \
    gstreamer1.0-plugins-base \
    gstreamer1.0-plugins-good \
    gstreamer1.0-plugins-bad \
    runit && rm -rf /var/lib/apt/lists/*
RUN echo "load-module module-simple-protocol-tcp listen=127.0.0.1 format=s16le channels=2 rate=48000 record=true playback=false" > /etc/pulse/default.pa.d/simple-protocol.pa

# Repackage the installed Firefox extension from the maintained source.
# Do not copy the older binary XPI: otherwise Web-only search interception
# would silently be missing from fresh participant images.
COPY ./firefox-extension/chatgpt-prompt-logger/ /opt/nerds-firefox-extension/
RUN python3 -c "import pathlib,zipfile; d=pathlib.Path('/opt/nerds-firefox-extension'); n=['manifest.json','background.js','browser-events.js','content.js','google-web-only.js']; z=zipfile.ZipFile('/opt/chatgpt-prompt-logger.xpi','w',compression=zipfile.ZIP_DEFLATED); [z.write(d/x,arcname=x) for x in n]; z.close()"
COPY ./firefox-policies/policies.json /usr/lib/firefox-esr/distribution/policies.json

RUN useradd -m --shell=/usr/bin/nologin user
# Prevent participants from minimizing/maximizing the two research desktop
# windows; the NERDs split/CLI-only/Firefox-only controls handle layout.
# Keep close available for ordinary Firefox dialog windows.
RUN install -d -o user -g user /home/user/.config/openbox \
    && sed 's#<titleLayout>NLIMC</titleLayout>#<titleLayout>NLC</titleLayout>#' \
       /etc/xdg/openbox/rc.xml > /home/user/.config/openbox/rc.xml \
    && sed -i 's#</applications>#  <application class="XTerm"><decor>no</decor></application>\n  <application class="firefox-esr"><decor>no</decor></application>\\n</applications>#' /home/user/.config/openbox/rc.xml \
    && chown user:user /home/user/.config/openbox/rc.xml
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

# Store both original fuzzing tasks in protected storage.
# Participant processes must not access unreleased task materials.
USER root

COPY ./fuzzing/ /opt/nerds/task-bundles/

RUN chown -R root:root /opt/nerds/task-bundles \
    && chmod -R go-rwx /opt/nerds/task-bundles \
    && install -d -o user -g user -m 0755 /home/user/fuzz-study

# All normal NERDs services continue as the unprivileged user.
USER user

COPY --chown=user:user ./services ./services
# runsv executes the run files directly; copying from a checkout can strip the
# executable bit even when their shebangs are valid.
USER root
RUN find /home/user/services -mindepth 2 -maxdepth 2 -type f -name run \
        -exec chmod 0755 {} + \
    && test -x /home/user/services/xterm/run
USER user

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
COPY --chown=user:user ./pilot1_task_descriptions.py .
COPY --chown=user:user ./workspace_layout.py .
COPY --chown=user:user ./browser_observation.py .
COPY --chown=user:user ./clipboard_observation.py .
COPY --chown=user:user ./browser_extension_origin.py .
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
