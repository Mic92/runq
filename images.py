#!/usr/bin/env python

import json
import sys
import subprocess
from pathlib import Path
from typing import Any, Dict, Optional, List
from dataclasses import dataclass, field


@dataclass
class Port:
    num: int
    wget: bool = False


@dataclass
class Mount:
    from_path: str
    to_path: str


@dataclass
class Image:
    name: str
    repo_digest: Optional[str] = None
    test_ports: List[Port] = field(default_factory=list)
    docker_commands: List[str] = field(default_factory=list)
    old_size: Optional[int] = None
    new_size: Optional[int] = None
    envs: List[str] = field(default_factory=list)
    mounts: List[Mount] = field(default_factory=list)
    skip: bool = False
    sidecars: List["Image"] = field(default_factory=list)

    @staticmethod
    def from_json(name: str, value: Dict[str, Any]) -> "Image":
        sidecars = []
        for n, v in value.get("sidecars", {}).items():
            sidecars.append(Image.from_json(n, v))

        i = Image(
            name=name,
            repo_digest=value.get("repo_digest"),
            docker_commands=value.get("docker_commands", []),
            old_size=value.get("old_size"),
            new_size=value.get("new_size"),
            envs=value.get("envs", []),
            mounts=[Mount(**p) for p in value.get("mounts", [])],
            test_ports=[Port(**p) for p in value.get("test_ports", [])],
            skip=value.get("skip", False),
            sidecars=sidecars,
        )

        return i

    def as_json(self) -> Dict[str, Any]:
        mounts = [dict(from_path=p.from_path, to_path=p.to_path) for p in self.mounts]
        test_ports = []
        for p in self.test_ports:
            test_port = dict(num=p.num)
            if p.wget:
                test_port["wget"] = p.wget
            test_ports.append(test_port)

        fields: Dict[str, Any] = dict(
            repo_digest=self.repo_digest,
            test_ports=test_ports,
            envs=self.envs,
            mounts=mounts,
            sidecars=dict((sidecar.name, sidecar.as_json()) for sidecar in self.sidecars),
        )
        if self.skip:
            fields["skip"] = self.skip

        if self.old_size is not None:
            fields["old_size"] = self.old_size

        if self.new_size is not None:
            fields["new_size"] = self.new_size
        return fields


def read_images(path: Path) -> List[Image]:
    with open(path, "r") as in_fd:
        images = []
        for name, value in json.load(in_fd).items():
            images.append(Image.from_json(name, value))
        return images


def write_images(path: Path, images: List[Image]) -> None:
    with open(path, "w") as out_fd:
        json.dump(
            dict((i.name, i.as_json()) for i in images),
            out_fd,
            indent=4,
            sort_keys=True,
        )


def main() -> None:
    if len(sys.argv) < 2:
        print(f"USAGE: {sys.argv[0]} IMAGES_PATH")
        sys.exit(1)
    images_path = Path(sys.argv[1])
    images = read_images(images_path)

    for img in images:
        if not img.repo_digest:
            subprocess.run(["docker", "pull", img.name], check=True)
            meta_raw = subprocess.run(
                ["docker", "inspect", img.name], check=True, stdout=subprocess.PIPE
            )
            meta = json.loads(meta_raw.stdout)
            digest = meta[0]["RepoDigests"][0]
            img.repo_digest = digest
            write_images(images_path, images)


if __name__ == "__main__":
    main()
