FROM nginx

WORKDIR /var/www/devob/

COPY nginx.conf /etc/nginx/nerds-nginx.conf.template
RUN mkdir static
COPY static/ static/

EXPOSE 80 443

COPY pilot1-ai-gateway-init.sh /docker-entrypoint.d/40-nerds-ai-gateway.sh
RUN chmod 755 /docker-entrypoint.d/40-nerds-ai-gateway.sh

# Public static completion portal; survey handoff disabled for the pilot.
COPY ./study-complete.html /usr/share/nginx/html/nerds-study-complete.html
COPY ./study-complete-config.json /usr/share/nginx/html/nerds-study-complete-config.json
