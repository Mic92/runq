#!/usr/bin/env python3

import sys
import pandas as pd
from typing import List, DefaultDict
from collections import defaultdict

from images import read_images

def main() -> None:
    if len(sys.argv) < 3:
        print(f"USAGE: {sys.argv[0]} images.json images.tsv", file=sys.stderr)
        sys.exit(1)

    json_path, tsv_path = (sys.argv[1], sys.argv[2])
    images = read_images(json_path)
    stats: DefaultDict[str, List] = defaultdict(list)
    for i in images:
        if not i.old_size or not i.new_size:
            continue
        stats["name"].append(i.name)
        stats["old_size"].append(i.old_size)
        stats["new_size"].append(i.new_size)
    df = pd.DataFrame(stats)
    df.to_csv(tsv_path, index=False, sep="\t")

if __name__ == '__main__':
    main()
