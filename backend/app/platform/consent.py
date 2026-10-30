"""The standard proctoring consent text (SECURITY_AND_ACCESS.md § 8.2; TCK-1408).

Used for a proctored exam when neither the exam nor the institution has its own wording. It
states, in plain words, every point § 8.2 requires: what is used (the microphone only in
Video + Audio mode; the screen when it's shared, and what that means), that analysis stays on
the device and nothing is recorded, when still images are kept, who sees them, how long they're
kept, that a person decides, and what declining means. The text frozen into the published exam
is the one students accept (its hash is kept).
"""

STANDARD = """\
**This exam is proctored.** Please read this before you start.

- **What is used:** your {devices} for as long as the exam is open.
- **On your device only:** the video{audio} is checked by your browser on this computer. \
Nothing is recorded or streamed.{screen}
- **Still images:** a few still images are saved only when something possibly suspicious is \
noticed (for example, nobody or two people in view).
- **Who can see them:** only the teacher who owns this exam. Not other students, and not the \
college's administrators.
- **How long:** they are kept for {days} days after the exam closes, then deleted automatically.
- **People decide, not software:** nothing is decided automatically. Your teacher reviews every \
event and can dismiss it.
- **If you decline:** you can't take this exam. Contact your teacher to talk about other \
arrangements.

By choosing **I agree**, you accept these terms for this exam only."""


SCREEN = """
- **Your screen:** you share your whole screen with the exam page. A picture of it is saved from \
time to time and whenever you leave the exam page, so your teacher can see what else was open. \
Close other apps, tabs and notes before you start."""


def standard_consent(proctoring_mode: str, retention_days: int, screen: bool = True) -> str:
    """The standard text for a VIDEO or VIDEO_AUDIO exam, with the institution's retention and,
    when the whole screen is shared, what that means."""
    audio = proctoring_mode == "VIDEO_AUDIO"
    devices = ["camera"] + (["microphone"] if audio else []) + (["screen"] if screen else [])
    return STANDARD.format(
        devices=", ".join(devices[:-1]) + " and " + devices[-1] if len(devices) > 1 else "camera",
        audio=" and sound" if audio else "",
        screen=SCREEN if screen else "",
        days=retention_days,
    )
