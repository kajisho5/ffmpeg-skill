"""Where a drawn layer landed in the frame it was drawn on (#547): measured, not computed.

The run's own filter graph is rendered twice, over a black and over a white frame of the written
size, at the instants the layer is on screen. A pixel the layer does not touch keeps the two
renders' background values; one it touches (text, a box, an image, its outline, any opacity above
a few percent) does not. The box is the bounding rectangle of those pixels, over every instant.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence, Tuple

from _common.decision import cfr_filter
from _common.emit import note
from _common.runner import require_tool, run_analysis

SLACK = 8  # a pixel within this many levels of the background is not the layer's (about 3 % opacity)


def bbox(diff: bytes, W: int, H: int) -> "Optional[Tuple[int, int, int, int]]":
    """(x, y, width, height) of the nonzero bytes of a W x H frame, None when all are zero. A row's
    leading zero bytes are the columns before its first set pixel, its trailing ones those after
    the last (one integer per row, no per-pixel loop)."""
    left, right, top, bottom = W, -1, None, 0
    for r in range(H):
        d = int.from_bytes(diff[r * W:(r + 1) * W], "big")
        if d:
            left, right = min(left, W - (d.bit_length() + 7) // 8), max(right, W - 1 - ((d & -d).bit_length() - 1) // 8)
            top, bottom = (r if top is None else top), r
    return None if top is None else (left, top, right - left + 1, bottom - top + 1)


def sample_cues(cues: Sequence[Tuple[float, float, str]], duration: Optional[float], cap: int = 12) -> List[float]:
    """The middle of each cue that has text and starts inside the video; above `cap` cues, `cap`
    of them spread through the list and always the longest text (the one most likely to run off)."""
    seen = [(s, e, t) for s, e, t in cues if t.strip() and (not duration or s < duration)]
    pick = {i * (len(seen) - 1) // (cap - 1) for i in range(cap)} if len(seen) > cap else set(range(len(seen)))
    pick |= {max(range(len(seen)), key=lambda i: len(seen[i][2]))} if seen else set()
    return [min((seen[i][0] + seen[i][1]) / 2, (duration or 1e9) - 0.001) for i in sorted(pick)]


def _render(rest: List[str], colour: str, W: int, H: int, pix: Optional[str], times: List[float]) -> "Optional[bytes]":
    """len(times) frames of `colour`, the k-th at times[k] on the clock a layer's enable and fade
    read (-copyts keeps it), through `rest` (the run's inputs and graph), as 8-bit grey."""
    when = "".join(f"if(eq(N,{k}),{t:.6f}," for k, t in enumerate(times)) + "0" + ")" * len(times)
    src = f"color=c={colour}:s={W}x{H}:r=1:d={len(times)}" + (f",format={pix}" if pix else "") + f",settb=AVTB,setpts='({when})/TB'"
    proc = run_analysis([require_tool("ffmpeg"), "-hide_banner", "-loglevel", "error", "-nostdin", "-filter_threads", "1",
                         "-copyts", "-f", "lavfi", "-i", src] + rest, check=False, text=False)
    return proc.stdout if proc.returncode == 0 and len(proc.stdout or b"") == len(times) * W * H else None


def measure_placement(cmd: List[str], meta: Dict[str, Any], out_video: Dict[str, Any], times: Sequence[float]) -> Dict[str, Any]:
    """The box of what `cmd` (the command that wrote the file) drew, at `times` seconds on the main
    picture's clock: {measured, x, y, width, height, frame_width, frame_height, touches_edge
    [left|right|top|bottom], samples}, or {measured: false, reason}. One filter thread, as fit.py's
    picture is (#543): the two renders are compared byte for byte."""
    W, H, times = int(out_video.get("width") or 0), int(out_video.get("height") or 0), sorted({round(t, 6) for t in times})
    graph_at = next((k for k, a in enumerate(cmd) if a in ("-filter_complex", "-vf")), 0)
    box, reason = None, "no frame size, instant or filter graph to measure"
    if W and H and times and graph_at and "-i" in cmd:
        first, last = cmd.index("-i"), max(k for k in range(graph_at) if cmd[k] == "-i")
        graph, conform = cmd[graph_at + 1], cfr_filter(meta)
        if conform:  # the main picture is a few frames at chosen instants: there is no rate to conform to
            graph = graph.replace(f"[0:v]{conform}[cfrin];", "").replace("[cfrin]", "[0:v]").replace(f",{conform}", "").replace(f"{conform},", "")
        if cmd[graph_at] == "-filter_complex":
            graph, mapped = f"{graph};{cmd[cmd.index('-map', graph_at) + 1]}format=gray[mgray]", "[mgray]"
        else:
            graph, mapped = f"{graph},format=gray", "0:v:0"
        # passthrough: the frames sit at chosen instants, not on a grid; a constant-rate output
        # (FFmpeg 7.1's default here) repeated the first sample in place of the second
        rest = cmd[first + 2:last + 2] + [cmd[graph_at], graph, "-map", mapped, "-fps_mode", "passthrough", "-frames:v", str(len(times)), "-f", "rawvideo", "-"]
        dark, light = (_render(rest, c, W, H, (meta.get("video") or {}).get("pix_fmt"), times) for c in ("black", "white"))
        reason = f"ffmpeg did not give {len(times)} frame(s) of {W}x{H} from the filter graph"
        if dark and light:
            # the background is the lowest value over the black render and the highest over the white one
            under, over = (bytes(int(ok(v)) for v in range(256)) for ok in (lambda v: v <= min(dark) + SLACK, lambda v: v >= max(light) - SLACK))
            size, drawn = W * H, 0
            for k in range(len(times)):
                still = int.from_bytes(dark[k * size:(k + 1) * size].translate(under), "big") & int.from_bytes(light[k * size:(k + 1) * size].translate(over), "big")
                drawn |= still ^ int.from_bytes(b"\x01" * size, "big")
            box, reason = bbox(drawn.to_bytes(size, "big"), W, H), "nothing of the layer is in the frame at the sampled instants"
    if box is None:
        note(f"placement: not measured: {reason}")
        return {"measured": False, "reason": reason}
    x, y, w, h = box
    return {"measured": True, "x": x, "y": y, "width": w, "height": h, "frame_width": W, "frame_height": H,
            "touches_edge": [n for n, on in (("left", x == 0), ("right", x + w == W), ("top", y == 0), ("bottom", y + h == H)) if on],
            "samples": len(times)}
