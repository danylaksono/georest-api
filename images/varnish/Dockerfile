FROM varnish:9.1.0-2

COPY default.vcl /etc/varnish/georest.vcl
COPY entrypoint.sh /georest-varnish.sh
ENTRYPOINT ["/bin/sh", "/georest-varnish.sh"]
