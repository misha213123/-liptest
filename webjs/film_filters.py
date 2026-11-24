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


def _percent(job: dict, key: str, default: int = 0) -> float:
    """Return a safe, finite 0..100 slider value (no arbitrary FFmpeg flags)."""
    import math
    try:
        value = float(job.get(key, default))
    except (ValueError, TypeError) as exc:
        raise ValueError(f"Некорректный параметр улучшения: {key}") from exc
    if not math.isfinite(value):
        raise ValueError(f"Некорректный параметр улучшения: {key}")
    return min(100.0, max(0.0, value))


def restoration_filters(job: dict, preview: bool = False) -> tuple[list[str], list[str]]:
    """Return pre-color and post-color restoration filters.

    These are REAL FFmpeg filters, not Topaz proprietary models:
    deblock = compressed block-artifact reduction
    hqdn3d = spatial/temporal denoise
    unsharp (3x3) = local microdetail/clarity
    unsharp (5x5) = edge sharpening
    noise = intentional grain to reduce plasticky appearance.
    """
    pre, post = [], []
    artifacts = _percent(job, "artifact_reduction")
    denoise = _percent(job, "denoise")
    detail = _percent(job, "microdetail")
    sharpen = _percent(job, "sharpen", 36)
    grain = _percent(job, "film_grain")

    if artifacts > 0:
        alpha = .018 + .075 * artifacts / 100
        beta = .009 + .055 * artifacts / 100
        gamma = .009 + .045 * artifacts / 100
        delta = .008 + .045 * artifacts / 100
        pre.append(
            "deblock=filter=strong:block=8:"
            f"alpha={alpha:.3f}:beta={beta:.3f}:"
            f"gamma={gamma:.3f}:delta={delta:.3f}"
        )
    if denoise > 0:
        # Mild maximum strength so faces do not turn into plastic.
        level = denoise / 100
        pre.append(
            f"hqdn3d={.5 + 4.5 * level:.2f}:"
            f"{.4 + 3.2 * level:.2f}:"
            f"{.8 + 5 * level:.2f}:"
            f"{.6 + 4 * level:.2f}"
        )
    if detail > 0:
        post.append(f"unsharp=3:3:{(.60 * detail / 100):.3f}:3:3:0")
    if sharpen > 0:
        # Modest defaults; avoid aggressive halos on subtitles and faces.
        post.append(f"unsharp=5:5:{(.90 * sharpen / 100):.3f}:5:5:0")
    if grain > 0:
        post.append(f"noise=alls={.5 + 6.5 * grain / 100:.2f}:allf=t+u")
    return pre, post


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
    before, after = restoration_filters(job, preview=preview)
    filters = before + [(
        f"eq=brightness={brightness:.3f}:gamma={gamma:.3f}:"
        f"contrast={contrast:.3f}:saturation={saturation:.3f}"
    )]
    filters += TONES[tone]
    filters += after
    return filters
