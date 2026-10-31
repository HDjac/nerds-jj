#!/bin/sh
set -eu

secret_file=/run/secrets/pilot1_ai_gateway_token
template_file=/etc/nginx/nerds-nginx.conf.template
config_file=/etc/nginx/nginx.conf
marker=__PILOT1_AI_GATEWAY_TOKEN__

if [ ! -r "$secret_file" ]; then
    echo "NERDs AI gateway secret unavailable" >&2
    exit 1
fi

token=$(cat "$secret_file")

case "$token" in
    *[!0123456789abcdef]*|'')
        echo "Invalid NERDs AI gateway secret" >&2
        exit 1
        ;;
esac

if [ "${#token}" -ne 64 ]; then
    echo "Invalid gateway secret length" >&2
    exit 1
fi

if ! grep -Fq "$marker" "$template_file"; then
    echo "AI gateway configuration placeholder missing" >&2
    exit 1
fi

umask 077
temporary=$(mktemp /etc/nginx/.nerds-nginx.XXXXXX)
trap 'rm -f "$temporary"' EXIT

sed "s/$marker/$token/g" "$template_file" > "$temporary"
chmod 600 "$temporary"
mv "$temporary" "$config_file"

unset token

echo "NERDs AI gateway authentication configured"
