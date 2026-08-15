from pathlib import Path
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

directory = Path("../playlist2/pli")

unique_artists = set()

for path in directory.iterdir():
    if not path.is_file():
        continue
    filename = path.name
    if not filename.startswith("스텔 ") or path.suffix.lower() != ".opus":
        continue

    without_prefix = filename.removeprefix("스텔 ")
    artist_name = without_prefix.split(" ", 1)[0].split("-", 1)[0].strip()
    if artist_name:
        unique_artists.add(artist_name)

for artist in sorted(unique_artists):
    print(artist)
