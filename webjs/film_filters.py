"""Shared FFmpeg color look presets used by Film Studio export and thumbnails."""
from __future__ import annotations

TONES = {
    "neutral": [],
    "warm": ["colorbalance=rs=.045:gs=.009:bs=-.032"],
    "cool": ["colorbalance=rs=-.025:gs=.004:bs=.048"],
}

PRESETS = {
    "natural": {"gamma": 1.02, "brightness": 0, "contrast": 1.04,
                "saturation": 1.06, "tone": "neutral"},
    "vibrant": {"gamma": 1.07, "brightness": .025, "contrast": 1.11,
                "saturation": 1.23, "tone": "neutral"},
    "ultra": {"gamma": 1.10, "brightness": .040, "contrast": 1.17,
              "saturation": 1.28, "tone": "neutral"},
    # Reference clip look: stronger contrast, warm skin tones, saturated color.
    # Actual FFmpeg filters, not fake HDR/4K.
    "reference": {"gamma": 1.055, "brightness": .015, "contrast": 1.18,
                  "saturation": 1.24, "tone": "warm"},
    "bright": {"gamma": 1.12, "brightness": .052, "contrast": 1.06,
               "saturation": 1.10, "tone": "neutral"},
    "cinema": {"gamma": 1.04, "brightness": .003, "contrast": 1.15,
               "saturation": 1.09, "tone": "warm"},
    "warm": {"gamma": 1.05, "brightness": .018, "contrast": 1.08,
             "saturation": 1.15, "tone": "warm"},
    "cool": {"gamma": 1.03, "brightness": .015, "contrast": 1.10,
             "saturation": 1.13, "tone": "cool"},
}


def color_filters(job: dict, ai_enabled: bool = False, preview: bool = False) -> list[str]:
    if not bool(job.get("enhance", True)):
        return []
    def bounded(key, default, minimum, maximum):
        return min(maximum, max(minimum, float(job.get(key, default))))
    gamma = bounded("gamma", 1.05, .85, 1.20)
    saturation = bounded("saturation", 1.10, .75, 1.30)
    brightness = bounded("brightness", .02, -.05, .12)
    contrast = bounded("contrast", 1.06, .80, 1.30)
    tone = str(job.get("color_tone") or "neutral").lower()
    if tone not in TONES:
        raise ValueError("Unknown color tone: " + tone)
    filters = [(
        f"eq=brightness={brightness:.3f}:gamma={gamma:.3f}:"
        f"contrast={contrast:.3f}:saturation={saturation:.3f}"
    )]
    filters += TONES[tone]
    filters.append("unsharp=5:5:0.22" if preview else
                   "unsharp=5:5:0.32:5:5:0.0" if ai_enabled else
                   "unsharp=5:5:0.42:5:5:0.0")
    return filters
