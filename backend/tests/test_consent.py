"""The standard consent text states every point SECURITY_AND_ACCESS.md § 8.2 requires (TCK-1408)."""

from app.platform.consent import standard_consent


def test_standard_consent_covers_every_point() -> None:
    text = standard_consent("VIDEO_AUDIO", 30).lower()
    must_say = {
        "1 camera, microphone and screen used": "your camera, microphone and screen",
        "1 screen pictures saved": "a picture of it is saved",
        "2 analysed on the device, nothing recorded": "nothing is recorded",
        "3 still images only when suspicious": "only when something possibly suspicious",
        "4 who sees them": "only the teacher who owns this exam",
        "4 not other students or the admin": "not other students, and not the college's admin",
        "5 kept for the retention, then deleted": "30 days after the exam closes, then deleted",
        "6 nothing decided automatically": "nothing is decided automatically",
        "7 declining": "if you decline",
    }
    missing = [point for point, words in must_say.items() if words not in text]
    assert not missing, missing


def test_camera_only_mode_doesnt_mention_the_microphone() -> None:
    text = standard_consent("VIDEO", 14)
    assert "your camera and screen" in text
    assert "microphone" not in text and "sound" not in text and "14 days" in text


def test_without_screen_sharing_the_screen_isnt_mentioned() -> None:
    text = standard_consent("VIDEO_AUDIO", 30, screen=False)
    assert "your camera and microphone" in text and "screen" not in text
