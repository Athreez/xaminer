"""The standard proctoring consent text (SECURITY_AND_ACCESS.md § 8.2; TCK-1408).

Used for a proctored exam when neither the exam nor the institution has its own wording. It
states, in plain words, every point § 8.2 requires: what is used (the microphone only in
Video + Audio mode), that analysis stays on the device and nothing is recorded, when still
images are kept, who sees them, how long they're kept, that a person decides, and what declining
means. The text frozen into the published exam is the one students accept (its hash is kept).
"""

STANDARD = """\
**This exam is proctored.** Please read this before you start.

- **What is used:** your camera{microphone} for as long as the exam is open.
- **On your device only:** the video{audio} is checked by your browser on this computer. \
Nothing is recorded or streamed.
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


def standard_consent(proctoring_mode: str, retention_days: int) -> str:
    """The standard text for a VIDEO or VIDEO_AUDIO exam, with the institution's retention."""
    audio = proctoring_mode == "VIDEO_AUDIO"
    return STANDARD.format(
        microphone=" and microphone" if audio else "",
        audio=" and sound" if audio else "",
        days=retention_days,
    )
