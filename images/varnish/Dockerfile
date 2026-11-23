FROM varnish:9.1.0-2@sha256:f97e894d90bccc585e5847e766696b7785c98046c29f76007f06d2e2c3228a4e

COPY LICENSE /usr/share/licenses/georest/LICENSE
COPY images/varnish/default.vcl /etc/varnish/georest.vcl
COPY images/varnish/entrypoint.sh /georest-varnish.sh
ENTRYPOINT ["/bin/sh", "/georest-varnish.sh"]
