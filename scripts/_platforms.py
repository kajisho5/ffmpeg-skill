#!/usr/bin/env python3
"""One table per delivery destination (internal module, not a tool).

Before 1.14 the same destination was described three times: check.py held the
compliance spec (duration, aspect, codecs, loudness), export.py held the frame and
encoder settings, and nothing at all held the part of the frame the app's own UI
covers. A TikTok export therefore passed every check while its captions sat under
the description bar. This module is the single table the delivery tools read:

    PLATFORMS[name] = {
        "frame":   {"w", "h", "aspect"} or None (audio-only destinations),
        "fps":     the frame rate a delivery is conformed to (None = leave alone),
        "spec":    check.py's compliance row values (max_duration, aspects,
                   min_height, fps_max, codecs, max_bytes, lufs, lufs_tol, tp,
                   sdr_only) -- the keys check.py's SPECS has always had,
        "safe":    the fraction of the frame each edge's UI covers
                   (top/bottom/left/right, 0..1) -- nothing readable goes there,
        "caption": the caption defaults a template uses (size as a fraction of the
                   frame height, position, box, outline, animate),
        "preset":  the export.py preset that writes this destination's file,
        "check":   the check.py platform name a delivery is verified against.
    }

Read by check.py (SPECS), export.py (PRESETS/PLATFORM_OF), render.py (templates),
caption.py and graphics.py (--platform margins) and look.py (--safe).

Safe zones are the app's own overlay, measured from each platform's published
design guidance: TikTok's caption/description block and the like/comment column,
Instagram's Reels UI, the Shorts player. They are deliberately generous -- a
caption 2 % too high is readable, a caption under the share button is not. The
feed destinations (YouTube, X, LinkedIn, Facebook) have no persistent overlay, so
they carry the conventional 5 % title-safe border instead.

ASS note: caption.py's --size and --margin are in the 288-line ASS script grid, so
a fraction of the frame height is that fraction * 288 (ass_units() below); the
burn scales it back to the real frame. graphics.py and look.py work in pixels.
"""
from typing import Any, Dict, List, Optional

ASS_SCRIPT_HEIGHT = 288  # caption.py's --size/--margin reference grid


def ass_units(fraction: float) -> int:
    """A fraction of the frame height as a caption.py --size / --margin value."""
    return int(round(fraction * ASS_SCRIPT_HEIGHT))


# The edges a feed destination reserves: no app chrome, just the conventional title-safe border.
_SAFE_5 = {"top": 0.05, "bottom": 0.05, "left": 0.05, "right": 0.05}
_NO_SAFE = {"top": 0.0, "bottom": 0.0, "left": 0.0, "right": 0.0}

# caption defaults: size is a fraction of the frame height (0.0833 = the 24 that every
# vertical job in this repo has used since 1.2), position/box/outline/animate as the
# caption.py flags of the same name.
_CAP_VERTICAL = {"size": 0.0833, "position": "bottom", "box": False, "outline": 2, "animate": "pop"}
_CAP_WIDE = {"size": 0.0694, "position": "bottom", "box": False, "outline": 2, "animate": "none"}

PLATFORMS: Dict[str, Dict[str, Any]] = {
    "tiktok": {
        "title": "TikTok",
        "frame": {"w": 1080, "h": 1920, "aspect": "9:16"},
        "fps": 30,
        "spec": {"max_duration": 600, "aspects": ["9:16", "1:1"], "min_height": 1080, "fps_max": 60,
                 "codecs": ["h264", "hevc"], "max_bytes": 4 * 1024 ** 3,
                 "lufs": -14, "lufs_tol": 2.0, "tp": -1.0, "sdr_only": True},
        # the description/caption block along the bottom, the like/comment/share column on the
        # right, the status bar and the "Following | For You" tabs at the top
        "safe": {"top": 0.10, "bottom": 0.22, "left": 0.05, "right": 0.14},
        "caption": _CAP_VERTICAL,
        "preset": "tiktok", "check": "tiktok",
    },
    "reels": {
        "title": "Instagram Reels",
        "frame": {"w": 1080, "h": 1920, "aspect": "9:16"},
        "fps": 30,
        "spec": {"max_duration": 90, "aspects": ["9:16", "4:5", "1:1"], "min_height": 1080, "fps_max": 60,
                 "codecs": ["h264", "hevc"], "max_bytes": 4 * 1024 ** 3,
                 "lufs": -14, "lufs_tol": 2.0, "tp": -1.0, "sdr_only": True},
        "safe": {"top": 0.08, "bottom": 0.20, "left": 0.05, "right": 0.12},
        "caption": _CAP_VERTICAL,
        "preset": "reels", "check": "reels",
    },
    "shorts": {
        "title": "YouTube Shorts",
        "frame": {"w": 1080, "h": 1920, "aspect": "9:16"},
        "fps": 30,
        "spec": {"max_duration": 180, "aspects": ["9:16", "1:1"], "min_height": 1080, "fps_max": 60,
                 "codecs": ["h264", "hevc"], "max_bytes": 256 * 1024 ** 3,
                 "lufs": -14, "lufs_tol": 2.0, "tp": -1.0, "sdr_only": False},
        "safe": {"top": 0.06, "bottom": 0.18, "left": 0.05, "right": 0.12},
        "caption": _CAP_VERTICAL,
        "preset": "shorts", "check": "shorts",
    },
    "youtube": {
        "title": "YouTube",
        "frame": {"w": 1920, "h": 1080, "aspect": "16:9"},
        "fps": None,
        "spec": {"max_duration": 12 * 3600, "aspects": ["16:9", "9:16", "1:1", "4:3"], "min_height": 720, "fps_max": 60,
                 "codecs": ["h264", "hevc", "prores", "av1", "vp9"], "max_bytes": 256 * 1024 ** 3,
                 "lufs": -14, "lufs_tol": 2.0, "tp": -1.0, "sdr_only": False},
        "safe": _SAFE_5,
        "caption": _CAP_WIDE,
        "preset": "youtube", "check": "youtube",
    },
    "youtube-hdr": {
        "title": "YouTube (HDR10)",
        "frame": {"w": 1920, "h": 1080, "aspect": "16:9"},
        "fps": None,
        "spec": dict({"max_duration": 12 * 3600, "aspects": ["16:9", "9:16", "1:1", "4:3"], "min_height": 720, "fps_max": 60,
                      "codecs": ["h264", "hevc", "prores", "av1", "vp9"], "max_bytes": 256 * 1024 ** 3,
                      "lufs": -14, "lufs_tol": 2.0, "tp": -1.0, "sdr_only": False}),
        "safe": _SAFE_5,
        "caption": _CAP_WIDE,
        "preset": "youtube-hdr", "check": "youtube",
    },
    "youtube-av1": {
        "title": "YouTube (AV1)",
        "frame": {"w": 1920, "h": 1080, "aspect": "16:9"},
        "fps": None,
        "spec": dict({"max_duration": 12 * 3600, "aspects": ["16:9", "9:16", "1:1", "4:3"], "min_height": 720, "fps_max": 60,
                      "codecs": ["h264", "hevc", "prores", "av1", "vp9"], "max_bytes": 256 * 1024 ** 3,
                      "lufs": -14, "lufs_tol": 2.0, "tp": -1.0, "sdr_only": False}),
        "safe": _SAFE_5,
        "caption": _CAP_WIDE,
        "preset": "youtube-av1", "check": "youtube",
    },
    "x": {
        "title": "X (Twitter)",
        "frame": {"w": 1280, "h": 720, "aspect": "16:9"},
        "fps": 30,
        "spec": {"max_duration": 140, "aspects": ["16:9", "1:1", "9:16"], "min_height": 720, "fps_max": 60,
                 "codecs": ["h264"], "max_bytes": 512 * 1024 ** 2,
                 "lufs": -14, "lufs_tol": 3.0, "tp": -1.0, "sdr_only": True},
        "safe": _SAFE_5,
        "caption": _CAP_WIDE,
        "preset": "x", "check": "x",
    },
    "linkedin": {
        "title": "LinkedIn",
        "frame": {"w": 1080, "h": 1080, "aspect": "1:1"},
        "fps": 30,
        "spec": {"max_duration": 600, "aspects": ["16:9", "1:1", "9:16", "4:5"], "min_height": 720, "fps_max": 60,
                 "codecs": ["h264"], "max_bytes": 5 * 1024 ** 3,
                 "lufs": -14, "lufs_tol": 3.0, "tp": -1.0, "sdr_only": True},
        "safe": _SAFE_5,
        "caption": _CAP_WIDE,
        "preset": "linkedin", "check": "linkedin",
    },
    "facebook": {
        "title": "Facebook",
        "frame": {"w": 1920, "h": 1080, "aspect": "16:9"},
        "fps": 30,
        "spec": {"max_duration": 240 * 60, "aspects": ["16:9", "1:1", "9:16", "4:5"], "min_height": 720, "fps_max": 60,
                 "codecs": ["h264", "hevc"], "max_bytes": 4 * 1024 ** 3,
                 "lufs": -14, "lufs_tol": 3.0, "tp": -1.0, "sdr_only": True},
        "safe": _SAFE_5,
        "caption": _CAP_WIDE,
        "preset": "facebook", "check": "facebook",
    },
    "podcast": {
        "title": "Podcast (audio)",
        "frame": None,
        "fps": None,
        "spec": {"max_duration": None, "aspects": None, "min_height": 0, "fps_max": None,
                 "codecs": None, "max_bytes": None,
                 "lufs": -16, "lufs_tol": 1.0, "tp": -1.0, "sdr_only": False},
        "safe": _NO_SAFE,
        "caption": _CAP_WIDE,
        "preset": None, "check": "podcast",
    },
    # Not destinations an app owns, but compliance targets check.py has always had.
    "broadcast": {
        "title": "Broadcast (EBU R128)",
        "frame": {"w": 1920, "h": 1080, "aspect": "16:9"},
        "fps": None,
        "spec": {"max_duration": None, "aspects": ["16:9"], "min_height": 1080, "fps_max": 60,
                 "codecs": ["prores", "dnxhd", "h264", "hevc", "mpeg2video"], "max_bytes": None,
                 "lufs": -23, "lufs_tol": 1.0, "tp": -1.0, "sdr_only": False},
        "safe": _SAFE_5,
        "caption": _CAP_WIDE,
        "preset": "prores", "check": "broadcast",
    },
    "custom": {
        "title": "Custom",
        "frame": None,
        "fps": None,
        "spec": {"max_duration": None, "aspects": None, "min_height": 0, "fps_max": None,
                 "codecs": None, "max_bytes": None,
                 "lufs": None, "lufs_tol": 2.0, "tp": -1.0, "sdr_only": False},
        "safe": _NO_SAFE,
        "caption": _CAP_WIDE,
        "preset": None, "check": "custom",
    },
}

# The canonical destination names.
PLATFORM_NAMES: List[str] = sorted(PLATFORMS)
# The spellings people actually write for those destinations. resolve() maps them onto the
# canonical name, and every tool's --platform/--safe/--preset accepts both, so
# `--platform youtube-shorts` and `--platform shorts` are the same request everywhere.
ALIASES: Dict[str, str] = {"youtube-shorts": "shorts", "yt-shorts": "shorts", "yt": "youtube",
                           "instagram": "reels", "ig": "reels", "twitter": "x", "fb": "facebook"}
# One vocabulary for the word "platform": check.py, caption.py, graphics.py and look.py all
# offer this list (review 12 found three different ones). It is the compliance targets -- the
# destinations a delivery is checked against -- plus every alias; youtube-hdr and youtube-av1
# are export presets of the youtube target, not separate destinations, so they are not in it.
PLATFORM_CHOICES: List[str] = sorted({n for n in PLATFORMS if PLATFORMS[n]["check"] == n} | set(ALIASES))


def has_frame(name: str) -> bool:
    """True when this destination has a frame, and therefore a safe zone to place text inside."""
    return bool(PLATFORMS.get(resolve(name) or "", {}).get("frame"))


def spec_of(name: str) -> Dict[str, Any]:
    """check.py's compliance row values for a destination."""
    return dict(PLATFORMS[name]["spec"])


def safe_of(name: str) -> Dict[str, float]:
    return dict(PLATFORMS[name]["safe"])


def loudness_of(name: str) -> Dict[str, float]:
    s = PLATFORMS[name]["spec"]
    return {"lufs": s["lufs"], "lufs_tol": s["lufs_tol"], "tp": s["tp"]}


def safe_margins_px(name: str, width: int, height: int) -> Dict[str, int]:
    """The safe zone in pixels for a frame of this size, as whole pixels per edge."""
    s = PLATFORMS[name]["safe"]
    return {"top": int(round(s["top"] * height)), "bottom": int(round(s["bottom"] * height)),
            "left": int(round(s["left"] * width)), "right": int(round(s["right"] * width))}


def caption_defaults(name: str) -> Dict[str, Any]:
    """caption.py flag values for this destination: --size/--margin in ASS units."""
    cap = dict(PLATFORMS[name]["caption"])
    safe = PLATFORMS[name]["safe"]
    edge = safe["top"] if cap["position"].startswith("top") else safe["bottom"]
    cap["size"] = ass_units(cap["size"])
    cap["margin"] = ass_units(edge)
    return cap


def resolve(name: Optional[str]) -> Optional[str]:
    """Accept the spellings people write for a destination ('youtube-shorts', 'ig')."""
    if not name:
        return None
    key = str(name).strip().lower()
    return ALIASES.get(key, key)
