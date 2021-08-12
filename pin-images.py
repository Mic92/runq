#!/usr/bin/env python

import json
import sys
import subprocess


def main() -> None:
    if len(sys.argv) < 3:
        print(f"USAGE: {sys.argv[0]} IMAGE_NAMES IMAGE_JSON")
        sys.exit(1)

    images = {}
    with open(sys.argv[1], "r") as in_fd:
        for img in in_fd:
            img = img.rstrip()
            if img.startswith("#"):
                continue
            subprocess.run(["docker", "pull", img], check=True)
            meta_raw = subprocess.run(
                ["docker", "inspect", img], check=True, stdout=subprocess.PIPE
            )
            meta = json.loads(meta_raw.stdout)
            img_id = meta[0]["RepoDigests"][0]
            images[img] = img_id
    with open(sys.argv[2], "w") as out_fd:
        json.dump(images, out_fd, indent=4, sort_keys=True)


if __name__ == "__main__":
    main()
