#!/bin/sh
# HTTPS for a demo without a domain: a self-signed certificate for the hosts in CERT_HOSTS
# (comma-separated names or IPs, e.g. "localhost,127.0.0.1,192.168.1.20"). Made on first start
# and kept in the web-certs volume, so each device accepts it once; made again when the hosts
# change. To use a real certificate, put cert.pem and key.pem in the volume and set CERT_HOSTS=own.
set -e
dir=/etc/nginx/certs
hosts="${CERT_HOSTS:-localhost,127.0.0.1}"
mkdir -p "$dir"
[ "$hosts" = "own" ] && exit 0
if [ -s "$dir/cert.pem" ] && [ -s "$dir/key.pem" ] && [ "$(cat "$dir/hosts" 2>/dev/null)" = "$hosts" ]; then
  exit 0
fi
san=""
for h in $(echo "$hosts" | tr ',' ' '); do
  case "$h" in
    *[!0-9.]*) san="$san,DNS:$h" ;;
    *) san="$san,IP:$h" ;;
  esac
done
openssl req -x509 -newkey rsa:2048 -nodes -days 825 -subj "/CN=Xaminer demo" \
  -addext "subjectAltName=${san#,}" -keyout "$dir/key.pem" -out "$dir/cert.pem" 2>/dev/null
echo "$hosts" > "$dir/hosts"
echo "self-signed certificate made for: $hosts"
