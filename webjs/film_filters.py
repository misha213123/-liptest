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
    # Full-reel cinematic look: saturated but preserves highlights and skin.
    # Designed to pair with FFmpeg's actual 30->60fps minterpolate.
    "smooth_vivid": {"gamma": 1.075, "brightness": .025, "contrast": 1.19,
                     "saturation": 1.29, "tone": "warm"},
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


def manual_cleanup_filters(job: dict) -> tuple[list[str], list[str]]:
    """Independent non-neural cleanup, zero disables each control."""
    grain = _percent(job, "remove_grain") / 100
    blur = _percent(job, "remove_blur") / 100
    pre, post = [], []
    if grain:
        # Strong spatial cleanup with edge-preserving non-local means.
        pre.append(f"nlmeans=s={1 + 9 * grain:.2f}:p=7:r=11")
    if blur:
        # Two bounded spatial scales; no claim of recovering lost detail.
        post.append(f"unsharp=5:5:{1.8 * blur:.3f}:5:5:0")
        post.append(f"unsharp=3:3:{.65 * blur:.3f}:3:3:0")
    return pre, post


def clean_hd_filters(job: dict) -> tuple[list[str], list[str]]:
    """Fast non-neural cleanup: native-resolution denoise, then output sharpening.
    Keep color controls shared by thumbnail and export; never add film grain.
    """
    grain = _percent(job, "remove_grain") / 100
    blur = _percent(job, "remove_blur") / 100
    pre, post = [], []
    if grain:
        # Avoid the extra deblock pass in clean HD; hqdn3d still suppresses noise.
        pre.append(f"hqdn3d={10*grain:.2f}:{8*grain:.2f}:{14*grain:.2f}:{11*grain:.2f}")
    # Disable legacy sharpness and grain defaults: only four visible controls.
    post.extend(color_filters({**job, "clean_hd": False, "remove_grain": 0,
                               "remove_blur": 0, "artifact_reduction": 0,
                               "denoise": 0, "microdetail": 0,
                               "sharpen": 0, "film_grain": 0}))
    if blur:
        post.append(f"unsharp=5:5:{1.35*blur:.3f}:5:5:0")
        post.append(f"unsharp=3:3:{.35*blur:.3f}:3:3:0")
    return pre, post


def color_filters(job: dict, ai_enabled: bool = False, preview: bool = False) -> list[str]:
    if job.get("clean_hd") is True:
        pre, post = clean_hd_filters(job)
        return pre + post
    cleanup_pre, cleanup_post = manual_cleanup_filters(job)
    if not bool(job.get("enhance", True)):
        return cleanup_pre + cleanup_post
    def bounded(key, default, minimum, maximum):
        import math
        try:
            value = float(job.get(key, default))
        except (TypeError, ValueError) as exc:
            raise ValueError(f"Некорректная цветовая настройка: {key}") from exc
        if not math.isfinite(value):
            raise ValueError(f"Некорректная цветовая настройка: {key}")
        return min(maximum, max(minimum, value))
    # User-requested pro range; very high values intentionally cause aggressive
    # grading, so the preview should be checked before final export.
    gamma = bounded("gamma", 1.05, .60, 1.60)
    saturation = bounded("saturation", 1.10, .50, 2.50)
    brightness = bounded("brightness", .02, -.20, .25)
    contrast = bounded("contrast", 1.06, .50, 1.80)
    tone = str(job.get("color_tone") or "neutral").lower()
    if tone not in TONES:
        raise ValueError("Unknown color tone: " + tone)
    before, after = restoration_filters(job, preview=preview)
    if cleanup_pre:
        before = [f for f in before if not f.startswith("hqdn3d=")]
    if cleanup_post:
        after = [f for f in after if not f.startswith("unsharp=")]
    if cleanup_pre:
        after = [f for f in after if not f.startswith("noise=")]
    filters = cleanup_pre + before + [(
        f"eq=brightness={brightness:.3f}:gamma={gamma:.3f}:"
        f"contrast={contrast:.3f}:saturation={saturation:.3f}"
    )]
    filters += TONES[tone]
    filters += cleanup_post + after
    return filters
