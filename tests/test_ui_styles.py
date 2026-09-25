"""Tests for Streamlit UI styles and theme invariants."""

from __future__ import annotations

from student_agent.ui.styles import get_custom_css


def test_custom_css_rules() -> None:
    css = get_custom_css()

    # 1. 50 border radius
    assert "border-radius: 50px" in css

    # 2. No sidebar, no header, no navitem, no logo
    assert 'data-testid="stSidebar"' in css
    assert 'data-testid="stHeader"' in css
    assert "display: none" in css

    # 3. Light theme only
    assert "#FFFFFF" in css or "#ffffff" in css.lower()
    assert "background-color" in css

    # 4. Chatbox fixed in bottom with bottom padding
    assert "stChatInput" in css
    assert "padding-bottom" in css

    # 5. Compact and small text
    assert "font-size" in css
    assert "12px" in css or "13px" in css
