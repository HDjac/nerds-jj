FROM php:8.5.12-fpm-bookworm

WORKDIR /var/www/


# We have to do this to install PHP extensions
# Install docker-php-extension-installer
ADD https://github.com/mlocati/docker-php-extension-installer/releases/latest/download/install-php-extensions /usr/local/bin/

RUN chmod +x /usr/local/bin/install-php-extensions && sync && \
    install-php-extensions gd


RUN install-php-extensions pgsql pdo_pgsql redis @composer zip

RUN composer require google/recaptcha "~1.1" &&\
    composer require aws/aws-sdk-php &&\
    composer install


RUN mkdir /var/www/devob/
COPY app/ /var/www/devob/
RUN mkdir /var/www/webpageConf
COPY webpageConf/ /var/www/webpageConf/

# Remove the legacy database administration interface.
RUN rm -f /var/www/devob/adminer.php

# Production-safe PHP configuration.
RUN printf '%s\n' \
    'expose_php=Off' \
    'display_errors=Off' \
    'display_startup_errors=Off' \
    'log_errors=On' \
    'error_reporting=E_ALL' \
    'error_log=/proc/self/fd/2' \
    > /usr/local/etc/php/conf.d/99-nerds-security.ini
