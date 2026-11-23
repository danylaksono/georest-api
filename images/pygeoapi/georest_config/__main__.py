"""Command-line entry point for configuration and snapshot management."""

import argparse
import logging
import re
import sys
from pathlib import Path
from uuid import uuid4

from .grants import reconcile
from .manifest import ConfigError, read_manifest
from .render import build_configs, get_settings
from .secure import security_settings

RUNTIME = Path("/runtime")
SERVICES = ("api", "martin", "edge")


def stage(configs):
    snapshot = uuid4().hex
    for service, files in configs.items():
        directory = RUNTIME / service / "snapshots" / snapshot
        directory.mkdir(parents=True)
        for name, content in files.items():
            path = directory / name
            path.write_text(content, encoding="utf-8")
            path.chmod(0o644 if service == "cache" else 0o600)
    return snapshot


def set_link(directory, name, target):
    temporary = directory / f".{name}-{uuid4().hex}"
    temporary.symlink_to(target, target_is_directory=True)
    temporary.replace(directory / name)


def switch(snapshot=None):
    if snapshot is not None and not re.fullmatch(r"[a-f0-9]{32}", snapshot):
        raise ConfigError("invalid snapshot ID")
    targets = {}
    services = (*SERVICES, "cache") if (RUNTIME / "cache").is_dir() else SERVICES
    for service in services:
        directory = RUNTIME / service
        previous = directory / "previous"
        target = Path("snapshots") / snapshot if snapshot else previous.readlink()
        if not (directory / target).is_dir():
            raise ConfigError(f"snapshot is missing for {service}")
        targets[directory] = target
    for directory, target in targets.items():
        current = directory / "current"
        if current.is_symlink() and current.readlink() != target:
            set_link(directory, "previous", current.readlink())
        set_link(directory, "current", target)
        keep = {
            link.readlink().name
            for link in (current, directory / "previous")
            if link.is_symlink()
        }
        for existing in (directory / "snapshots").iterdir():
            if existing.name not in keep:
                for file in existing.iterdir():
                    file.unlink()
                existing.rmdir()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    render = commands.add_parser("render")
    mode = render.add_mutually_exclusive_group()
    mode.add_argument("--check", action="store_true")
    mode.add_argument("--dry-run", action="store_true")
    mode.add_argument("--stage", action="store_true")
    activate = commands.add_parser("activate")
    activate.add_argument("snapshot")
    commands.add_parser("rollback")
    commands.add_parser("grants")
    args = parser.parse_args()
    try:
        if args.command == "render":
            configs = build_configs(dry_run=args.dry_run)
            if args.dry_run:
                for files in configs.values():
                    for name, content in files.items():
                        print(f"---\n# {name}\n{content}", end="")
            elif not args.check:
                snapshot = stage(configs)
                if args.stage:
                    print(snapshot)
                else:
                    switch(snapshot)
        elif args.command == "grants":
            origin, mode, database = get_settings()
            security = security_settings(origin, mode)
            if security is None:
                raise ConfigError("grants requires the Level 3 overlay")
            reconcile(read_manifest(Path("/inputs/collections.yml")), database, security.allow_edits)
            print("GeoREST grants reconciled")
        else:
            switch(getattr(args, "snapshot", None))
    except (ConfigError, OSError) as exc:
        logging.error("%s", exc)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
