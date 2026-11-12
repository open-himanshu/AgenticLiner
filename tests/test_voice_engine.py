"""
Unit & Integration Tests for Pillar 1 - Section 1: Voice Engine & UI Components.
Verifies static asset serving, template selectors, and speech controller methods.
"""

import pytest
import httpx
from backend.api.main import app

@pytest.mark.anyio
async def test_voice_engine_static_js_served():
    """Verifies that voice_engine.js is served by FastAPI StaticFiles with 200 OK."""
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        res = await client.get("/static/js/voice_engine.js")
        assert res.status_code == 200
        content = res.text
        assert "class WebSpeechVoiceEngine" in content
        assert "initVoiceEngine" in content
        assert "toggleSpeechRecognition" in content
        assert "onSpeechStart" in content
        assert "onSpeechResult" in content
        assert "onSpeechEnd" in content
        assert "onSpeechError" in content
        assert "speakAssistantVoice" in content
        assert "toggleTTS" in content
        assert "setButtonState" in content

@pytest.mark.anyio
async def test_autopilot_template_has_voice_components():
    """Verifies autopilot.html contains all Section 1.1 UI components and voice_engine.js script."""
    with open("frontend/templates/autopilot.html", "r", encoding="utf-8") as f:
        html = f.read()
    
    assert "id=\"btnVoiceInput\"" in html
    assert "id=\"voiceStatusBanner\"" in html
    assert "id=\"toggleVoiceFeedback\"" in html
    assert "id=\"btnStopVoice\"" in html
    assert "voice_engine.js" in html
    assert "new WebSpeechVoiceEngine" in html

@pytest.mark.anyio
async def test_organiser_template_has_voice_components():
    """Verifies organiser.html contains the Quick AI Event Booking Voice card and selectors."""
    with open("frontend/templates/organiser.html", "r", encoding="utf-8") as f:
        html = f.read()

    assert "id=\"btnOrgVoiceInput\"" in html
    assert "id=\"orgVoiceStatusBanner\"" in html
    assert "id=\"toggleOrgVoiceFeedback\"" in html
    assert "voice_engine.js" in html
    assert "new WebSpeechVoiceEngine" in html

@pytest.mark.anyio
async def test_base_template_has_voice_mic_styles():
    """Verifies base.html has the 4 visual state classes and keyframe animations."""
    with open("frontend/templates/base.html", "r", encoding="utf-8") as f:
        html = f.read()

    assert ".voice-mic-btn" in html
    assert ".state-idle" in html
    assert ".state-listening" in html
    assert ".state-processing" in html
    assert ".state-denied" in html
    assert "@keyframes mic-pulse" in html
    assert ".soundwave-bar" in html
