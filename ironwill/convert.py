"""Convert the playing file to another format with the bundled FFmpeg (File > Convert).

Each preset is (label, extension, ffmpeg arguments between input and output). The source is only read; the result
goes to a new file next to it (or wherever the user picks).
"""

PRESETS = {
    "mp4": ("MP4 for phones, TVs and Roku (H.264 + AAC)", ".mp4",
            ["-map", "0:v:0", "-map", "0:a:0?", "-c:v", "libx264", "-preset", "medium", "-crf", "20",
             "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart"]),
    "smaller": ("Smaller file (H.265, about half the size)", ".mp4",
                ["-map", "0:v:0", "-map", "0:a:0?", "-c:v", "libx265", "-preset", "medium", "-crf", "26",
                 "-tag:v", "hvc1", "-c:a", "aac", "-b:a", "160k", "-movflags", "+faststart"]),
    "remux_mp4": ("Change to MP4 without re-encoding (instant, no quality loss)", ".mp4",
                  ["-map", "0:v", "-map", "0:a?", "-c", "copy", "-movflags", "+faststart"]),
    "remux_mkv": ("Change to MKV without re-encoding (keeps every track and subtitle)", ".mkv",
                  ["-map", "0", "-c", "copy"]),
    "mp3": ("Audio only: MP3", ".mp3", ["-vn", "-c:a", "libmp3lame", "-q:a", "2"]),
    "m4a": ("Audio only: M4A (AAC)", ".m4a", ["-vn", "-c:a", "aac", "-b:a", "192k"]),
    "flac": ("Audio only: FLAC (lossless)", ".flac", ["-vn", "-c:a", "flac"]),
}


def ffmpeg_args(src, dest, preset):
    """Full argument list for FFmpeg; -progress lets the player show a percentage."""
    _label, _ext, middle = PRESETS[preset]
    return ["-y", "-hide_banner", "-v", "error", "-progress", "pipe:1", "-nostats", "-i", str(src), *middle,
            str(dest)]


def parse_progress(chunk, duration):
    """Percent done from FFmpeg's -progress output (out_time_us=... lines), or None if there's nothing new."""
    pct = None
    for line in chunk.splitlines():
        if line.startswith(("out_time_us=", "out_time_ms=")) and duration:
            try:
                us = int(line.split("=", 1)[1])
            except ValueError:
                continue
            pct = max(0, min(100, int(us / 1_000_000 / duration * 100)))
    return pct
