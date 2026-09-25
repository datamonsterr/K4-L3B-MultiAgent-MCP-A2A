"""CSS styles and theme definitions for Streamlit multiagent chatbot."""

from __future__ import annotations


def get_custom_css() -> str:
    """Return compact, light-themed CSS with 50px border-radius and hidden navigation."""
    return """
    <style>
    /* ==========================================================================
       Day09 Multi-Agent Chatbot Theme (Light Only, Compact, 50 Border-Radius)
       ========================================================================== */

    /* Hide Sidebar, Header, Navitem, Footer, and Logo */
    [data-testid="stSidebar"],
    [data-testid="collapsedControl"],
    [data-testid="stSidebarNav"],
    header,
    [data-testid="stHeader"],
    footer,
    #MainMenu,
    .stDeployButton {
        display: none !important;
    }

    /* Force Light Theme Colors and Clean Background */
    :root {
        --color-bg-base: #FFFFFF;
        --color-bg-card: #F8FAFC;
        --color-bg-hover: #F1F5F9;
        --color-border: #E2E8F0;
        --color-text-main: #0F172A;
        --color-text-muted: #64748B;
        --color-primary: #2563EB;
        --color-success: #16A34A;
        --color-warning: #D97706;
        --color-danger: #DC2626;
        --radius-pill: 50px;
    }

    body, .stApp {
        background-color: #FFFFFF !important;
        color: #0F172A !important;
        font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif !important;
        font-size: 13px !important;
        line-height: 1.4 !important;
    }

    /* Main Container Padding to accommodate fixed bottom chatbox */
    .main .block-container {
        padding-top: 1.2rem !important;
        padding-bottom: 120px !important;
        max-width: 1080px !important;
    }

    /* 50 Border-Radius for Chat Input fixed at bottom */
    [data-testid="stChatInput"] {
        border-radius: 50px !important;
        border: 1px solid #CBD5E1 !important;
        background-color: #FFFFFF !important;
        box-shadow: 0 4px 18px rgba(15, 23, 42, 0.08) !important;
        padding: 4px 8px !important;
        transition: border-color 0.2s, box-shadow 0.2s;
    }

    [data-testid="stChatInput"]:focus-within {
        border-color: #2563EB !important;
        box-shadow: 0 4px 20px rgba(37, 99, 235, 0.16) !important;
    }

    [data-testid="stChatInput"] textarea {
        border-radius: 50px !important;
        font-size: 13px !important;
        color: #0F172A !important;
        padding: 8px 14px !important;
    }

    [data-testid="stChatInput"] button {
        border-radius: 50px !important;
    }

    /* Compact Buttons with 50 border-radius */
    .stButton > button {
        border-radius: 50px !important;
        font-size: 12px !important;
        padding: 4px 14px !important;
        height: auto !important;
        min-height: 30px !important;
        border: 1px solid #E2E8F0 !important;
        background-color: #F8FAFC !important;
        color: #1E293B !important;
        font-weight: 500 !important;
        transition: all 0.15s ease-in-out !important;
    }

    .stButton > button:hover {
        background-color: #EFF6FF !important;
        border-color: #93C5FD !important;
        color: #1D4ED8 !important;
    }

    /* Compact Typography */
    h1, h2, h3, h4 {
        color: #0F172A !important;
        font-weight: 600 !important;
        margin-top: 0.2rem !important;
        margin-bottom: 0.4rem !important;
    }

    p, span, label, div {
        font-size: 13px;
    }

    /* Agent Lane Card & Parallel Layout */
    .agent-lane-card {
        background-color: #F8FAFC;
        border: 1px solid #E2E8F0;
        border-radius: 14px;
        padding: 10px 12px;
        margin-bottom: 8px;
        font-size: 12px;
    }

    .agent-header {
        display: flex;
        align-items: center;
        justify-content: space-between;
        margin-bottom: 6px;
    }

    .agent-badge {
        display: inline-block;
        padding: 2px 8px;
        border-radius: 50px;
        font-size: 11px;
        font-weight: 600;
        background-color: #DBEAFE;
        color: #1E40AF;
    }

    .status-badge {
        display: inline-block;
        padding: 2px 8px;
        border-radius: 50px;
        font-size: 10.5px;
        font-weight: 500;
    }

    .status-badge-success {
        background-color: #DCFCE7;
        color: #15803D;
    }

    .status-badge-warning {
        background-color: #FEF3C7;
        color: #B45309;
    }

    .status-badge-info {
        background-color: #E0E7FF;
        color: #4338CA;
    }

    .tool-chip {
        display: inline-flex;
        align-items: center;
        gap: 4px;
        background-color: #FFFFFF;
        border: 1px solid #CBD5E1;
        border-radius: 50px;
        padding: 2px 7px;
        font-family: monospace;
        font-size: 10.5px;
        color: #334155;
        margin: 2px 2px;
    }

    .evidence-ref {
        display: inline-block;
        font-family: monospace;
        font-size: 10px;
        padding: 1px 6px;
        border-radius: 50px;
        background-color: #FEF9C3;
        color: #854D0E;
        border: 1px solid #FEF08A;
        margin-top: 2px;
    }

    /* Trace Log Box */
    .trace-container {
        background-color: #0F172A;
        color: #F8FAFC;
        border-radius: 12px;
        padding: 10px 12px;
        font-family: monospace;
        font-size: 11px;
        max-height: 280px;
        overflow-y: auto;
        line-height: 1.35;
    }
    </style>
    """
