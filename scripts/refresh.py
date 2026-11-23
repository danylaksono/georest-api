"""Stage and activate the collection manifest during a short maintenance window."""

import re
import subprocess
import sys


def refresh(compose):
    def run(*args, **options):
        return subprocess.run([*compose, *args], check=True, text=True, **options)

    services = run("config", "--services", stdout=subprocess.PIPE).stdout.splitlines()
    staged = run("run", "--rm", "--no-deps", "configure", "render", "--stage", stdout=subprocess.PIPE)
    snapshot = staged.stdout.strip()
    if not re.fullmatch(r"[a-f0-9]{32}", snapshot):
        raise RuntimeError("could not identify the validated configuration snapshot")

    backends = [name for name in ("pygeoapi", "martin", "varnish") if name in services]
    start = ("up", "-d", "--no-deps", "--wait", "--wait-timeout", "75")
    run("stop", "traefik")
    try:
        run("stop", *backends)
        run("run", "--rm", "--no-deps", "configure", "activate", snapshot)
        run(*start, *backends)
        run(*start, "traefik")
    except subprocess.CalledProcessError:
        print("Refresh failed. Restoring the previous service configuration.", file=sys.stderr)
        run("stop", "traefik", *backends)
        run("run", "--rm", "--no-deps", "configure", "rollback")
        run(*start, *backends)
        run(*start, "traefik")
        raise


if __name__ == "__main__":
    refresh(["docker", "compose", *sys.argv[1:]])
