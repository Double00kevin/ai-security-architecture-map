# Decoded video frames, audit 2026-09-28 (F13, F14)

Frames decoded with ffmpeg from the final MP4s, not from the renderer's in-memory images:

    ffmpeg -ss 19.9 -i <video>.mp4 -frames:v 1 <name>-layer06.png   # last frame of the layer 06 scene
    ffmpeg -ss 40.6 -i <video>.mp4 -frames:v 1 <name>-outro.png     # last frame of the outro

- `before-*`: from the committed `maps/v2026.09.27.1/map.mp4` and `map-vertical.mp4` (renderer at bd0fe5f).
  The outro footer "map v2026.09.27.1 · verified … · trust until 2026-10-27" runs to the right edge of the
  1080 px frame.
- `after-*`: the same `maps/v2026.09.27.1/map.json` rendered with this branch's renderer
  (`python render/render_video.py maps/v2026.09.27.1/map.json [--vertical] -o <scratch>`). The footer is
  measured and shrunk to fit inside the 40 px safe margin. The re-rendered MP4s were not committed:
  published versions are never rewritten.
- `v2026.09.28-*`: decoded from the committed `maps/v2026.09.28/map.mp4` and `map-vertical.mp4`, the first
  version built from reviewed evidence (`ffmpeg -sseof -0.3 ...` for the outro, `-ss 19.9` for layer 06).
  Footer: "map v2026.09.28 · oldest review 2026-09-28 · review due 2026-10-28", inside the margin.
