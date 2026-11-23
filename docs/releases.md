# Build and release container images

For a local checkout, use `make up LEVEL=1` or the equivalent `docker compose up -d --build --wait`. Compose builds the GeoREST image from the checkout.

When a version is published, set `GEOREST_VERSION` to its exact tag and `GEOREST_REGISTRY` to its GHCR namespace. For the selected level, use `make pull LEVEL=1` or `docker compose pull` followed by `docker compose up -d --no-build --wait` with the same `-f` flags.

The GitHub workflow builds the custom pygeoapi and Varnish images for `linux/amd64` and `linux/arm64`. A manual run checks the build. A maintainer-pushed `v*` tag publishes both images. The images carry this repository's MIT license in `/usr/share/licenses/georest/LICENSE` and retain the upstream image notices. [GitHub container publishing documentation](https://docs.github.com/en/actions/tutorials/publish-packages/publish-docker-images)

To reproduce the build check locally from the repository root, run the following commands.

```sh
docker buildx build --platform linux/amd64,linux/arm64 --output type=cacheonly -f images/pygeoapi/Dockerfile .
docker buildx build --platform linux/amd64,linux/arm64 --output type=cacheonly -f images/varnish/Dockerfile .
```

The bundled PostGIS fixture uses an amd64 image. On ARM hosts it needs Docker's amd64 emulation. An external PostGIS installation can run natively on its own host.
