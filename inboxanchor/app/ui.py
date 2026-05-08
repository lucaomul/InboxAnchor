from __future__ import annotations

from html import escape
from typing import Iterable, Optional

import streamlit as st


def inject_styles() -> None:
    st.markdown(
        """
        <style>
        :root {
            --ia-ink: #0f172a;
            --ia-subtle: #475569;
            --ia-line: rgba(148, 163, 184, 0.18);
            --ia-blue: #2563eb;
            --ia-blue-deep: #1d4ed8;
            --ia-emerald: #059669;
            --ia-amber: #d97706;
            --ia-rose: #dc2626;
        }
        .stApp {
            background:
              radial-gradient(circle at top right, rgba(37,99,235,0.14), transparent 28%),
              radial-gradient(circle at top left, rgba(14,165,233,0.08), transparent 24%),
              linear-gradient(180deg, #f6f9fc 0%, #edf4ff 100%);
        }
        .block-container {
            max-width: 1280px;
            padding-top: 1.45rem;
            padding-bottom: 2rem;
        }
        div[data-testid="stHorizontalBlock"] {
            align-items: stretch;
            gap: 1rem;
        }
        div[data-testid="column"] {
            min-width: 0;
        }
        div[data-testid="column"] > div {
            min-width: 0;
        }
        .stApp h1,
        .stApp h2,
        .stApp h3,
        .stApp h4,
        .stApp h5,
        .stApp h6 {
            color: #0f172a;
        }
        .stApp p,
        .stApp li,
        .stApp label,
        .stApp div[data-testid="stMarkdownContainer"] p,
        .stApp div[data-testid="stMarkdownContainer"] li,
        .stApp div[data-testid="stCaptionContainer"],
        .stApp small {
            color: #334155 !important;
            word-break: normal !important;
            overflow-wrap: normal !important;
        }
        div[data-testid="stVerticalBlockBorderWrapper"] {
            background: rgba(255,255,255,0.88);
            border: 1px solid rgba(148,163,184,0.18);
            border-radius: 22px;
            box-shadow: 0 14px 34px rgba(15,23,42,0.08);
            color: #0f172a;
            overflow: hidden;
        }
        label[data-testid="stWidgetLabel"] p,
        label[data-testid="stWidgetLabel"] span {
            color: #0f172a !important;
            font-weight: 700;
        }
        div[data-baseweb="select"] > div,
        div[data-baseweb="input"] > div {
            border-radius: 14px;
            min-height: 2.9rem;
            background: rgba(255,255,255,0.98) !important;
            border: 1px solid rgba(148,163,184,0.22) !important;
            box-shadow: inset 0 1px 0 rgba(255,255,255,0.75);
        }
        div[data-baseweb="select"] *,
        div[data-baseweb="input"] *,
        input,
        textarea {
            color: #0f172a !important;
        }
        div[data-baseweb="select"] input,
        div[data-baseweb="select"] span,
        div[data-baseweb="select"] p,
        div[data-baseweb="select"] div {
            color: #0f172a !important;
            white-space: normal !important;
            word-break: normal !important;
            overflow-wrap: normal !important;
        }
        div[data-baseweb="select"] svg,
        div[data-baseweb="input"] svg,
        div[data-baseweb="popover"] svg {
            fill: #475569 !important;
            color: #475569 !important;
        }
        div[data-baseweb="popover"] {
            z-index: 9999 !important;
        }
        div[data-baseweb="popover"] > div {
            background: rgba(255,255,255,0.99) !important;
            color: #0f172a !important;
            border: 1px solid rgba(148,163,184,0.2) !important;
            border-radius: 16px !important;
            box-shadow: 0 18px 42px rgba(15,23,42,0.16) !important;
            overflow: hidden !important;
        }
        ul[role="listbox"],
        div[role="listbox"] {
            background: rgba(255,255,255,0.99) !important;
            padding: 0.35rem !important;
        }
        li[role="option"],
        div[role="option"] {
            color: #0f172a !important;
            background: transparent !important;
            border-radius: 12px !important;
            white-space: normal !important;
            word-break: normal !important;
            overflow-wrap: break-word !important;
            padding-top: 0.6rem !important;
            padding-bottom: 0.6rem !important;
            line-height: 1.35 !important;
        }
        li[role="option"] *,
        div[role="option"] * {
            color: #0f172a !important;
            white-space: normal !important;
            word-break: normal !important;
        }
        li[role="option"]:hover,
        div[role="option"]:hover {
            background: rgba(219,234,254,0.62) !important;
        }
        li[role="option"][aria-selected="true"],
        div[role="option"][aria-selected="true"] {
            background: rgba(219,234,254,0.92) !important;
            color: #1d4ed8 !important;
        }
        li[role="option"][aria-selected="true"] *,
        div[role="option"][aria-selected="true"] * {
            color: #1d4ed8 !important;
        }
        textarea {
            border-radius: 14px !important;
        }
        [data-testid="stSidebar"] {
            display: none;
        }
        div[data-testid="stForm"] {
            background: rgba(248,250,252,0.74);
            border: 1px solid rgba(148,163,184,0.18);
            border-radius: 18px;
            padding: 0.95rem 1rem 0.7rem 1rem;
            overflow: hidden;
        }
        div[data-testid="stRadio"] {
            margin: 0.15rem 0 0.65rem 0;
        }
        div[data-testid="stRadio"] > div {
            gap: 0.65rem;
        }
        div[data-testid="stRadio"] label {
            background: rgba(255,255,255,0.95);
            border: 1px solid rgba(148,163,184,0.2);
            border-radius: 999px;
            padding: 0.45rem 0.85rem;
            min-height: auto !important;
        }
        div[data-testid="stRadio"] label p,
        div[data-testid="stRadio"] label span {
            color: #0f172a !important;
            font-weight: 700;
        }
        div[data-testid="stForm"] [data-testid="stTextInputRootElement"] {
            margin-bottom: 0.25rem;
        }
        div[data-testid="stForm"] .stTextInput {
            margin-bottom: 0.28rem;
        }
        div[data-testid="stForm"] [data-testid="stCaptionContainer"] {
            margin-top: 0.15rem;
            margin-bottom: 0.55rem;
        }
        div[data-testid="stForm"] [data-testid="stFormSubmitButton"] {
            margin-top: 0.1rem;
        }
        input[type="password"] {
            letter-spacing: normal;
        }
        div[data-testid="stExpander"] {
            border-radius: 18px;
            overflow: hidden;
            border: 1px solid rgba(148,163,184,0.16);
            background: rgba(255,255,255,0.82);
        }
        div[data-testid="stTabs"] button {
            border-radius: 999px;
            padding: 0.45rem 0.9rem;
            color: #475569;
            font-weight: 700;
            white-space: nowrap !important;
            word-break: keep-all !important;
            overflow-wrap: normal !important;
            writing-mode: horizontal-tb !important;
            text-orientation: mixed !important;
            min-width: max-content;
        }
        .stApp button,
        .stApp button *,
        .stApp summary,
        .stApp summary *,
        .stApp [role="tab"],
        .stApp [role="tab"] *,
        .stApp [data-baseweb="select"] *,
        .stApp [data-testid="stPopover"] button,
        .stApp [data-testid="stPopover"] button * {
            writing-mode: horizontal-tb !important;
            text-orientation: mixed !important;
            direction: ltr !important;
            unicode-bidi: normal !important;
            word-break: normal !important;
            overflow-wrap: normal !important;
            hyphens: none !important;
        }
        div[data-testid="stTabs"] button p,
        div[data-testid="stTabs"] button span {
            color: inherit !important;
            white-space: nowrap !important;
            word-break: keep-all !important;
            writing-mode: horizontal-tb !important;
            display: inline-block !important;
            max-width: none !important;
        }
        div[data-testid="stTabs"] [role="tablist"] {
            gap: 0.45rem;
            overflow-x: auto;
            flex-wrap: nowrap;
            padding-bottom: 0.1rem;
        }
        div[data-testid="stTabs"] > div:first-child {
            margin-bottom: 0.3rem;
        }
        div[data-testid="stTabs"] button[aria-selected="true"] {
            background: rgba(37,99,235,0.12);
            color: #1d4ed8;
        }
        div[data-testid="stExpander"] summary,
        div[data-testid="stExpander"] summary * {
            color: #0f172a !important;
            white-space: normal !important;
            word-break: normal !important;
            overflow-wrap: break-word !important;
        }
        div[data-testid="stPopover"] * {
            color: #0f172a !important;
        }
        .ia-hero {
            background: linear-gradient(135deg, #0f172a 0%, #1e3a8a 70%, #2563eb 100%);
            color: white;
            padding: 1.55rem 1.65rem 1.4rem 1.65rem;
            border-radius: 26px;
            box-shadow: 0 22px 46px rgba(15, 23, 42, 0.18);
            margin-bottom: 0.8rem;
            position: relative;
            overflow: hidden;
        }
        .ia-hero::after {
            content: "";
            position: absolute;
            inset: auto -80px -110px auto;
            width: 240px;
            height: 240px;
            border-radius: 999px;
            background: rgba(255,255,255,0.11);
            filter: blur(2px);
        }
        .ia-hero h1,
        .ia-hero p,
        .ia-hero span,
        .ia-hero div,
        .ia-hero small,
        .ia-stick-stage *,
        .ia-stick-stage p,
        .ia-stick-stage span,
        .ia-stick-stage div {
            color: inherit !important;
        }
        .ia-card {
            background: rgba(255,255,255,0.9);
            backdrop-filter: blur(10px);
            border: 1px solid var(--ia-line);
            border-radius: 22px;
            padding: 1rem 1.1rem 1.1rem 1.1rem;
            box-shadow: 0 14px 34px rgba(15, 23, 42, 0.08);
            margin-bottom: 0.65rem;
        }
        .ia-section-note {
            color: #64748b;
            font-size: 0.88rem;
            line-height: 1.5;
            margin: -0.05rem 0 0.45rem 0;
        }
        .ia-chip {
            display: inline-flex;
            align-items: center;
            padding: 0.26rem 0.58rem;
            border-radius: 999px;
            margin: 0 0.35rem 0.35rem 0;
            background: #dbeafe;
            color: #1e3a8a;
            font-size: 0.77rem;
            font-weight: 600;
            white-space: nowrap;
            word-break: keep-all;
        }
        .ia-chip-dark {
            background: rgba(255,255,255,0.14);
            color: rgba(255,255,255,0.92);
            border: 1px solid rgba(255,255,255,0.18);
        }
        .ia-workspace-bar {
            background: rgba(255,255,255,0.92);
            border: 1px solid rgba(148,163,184,0.2);
            border-radius: 24px;
            padding: 1rem 1.1rem 0.95rem 1.1rem;
            box-shadow: 0 18px 42px rgba(15,23,42,0.08);
            margin-bottom: 1rem;
        }
        .ia-workspace-head {
            display: flex;
            align-items: center;
            justify-content: space-between;
            gap: 1rem;
            margin-bottom: 0.7rem;
        }
        .ia-workspace-title {
            font-size: 0.82rem;
            letter-spacing: 0.18em;
            text-transform: uppercase;
            color: #64748b;
            font-weight: 800;
        }
        .ia-workspace-copy {
            color: #475569;
            font-size: 0.93rem;
            line-height: 1.45;
            max-width: 720px;
        }
        .ia-workspace-grid {
            display: grid;
            grid-template-columns: 1.35fr 0.95fr;
            gap: 0.9rem;
            align-items: stretch;
        }
        .ia-control-card {
            background: linear-gradient(180deg, rgba(248,250,252,0.96), rgba(255,255,255,0.98));
            border: 1px solid rgba(148,163,184,0.16);
            border-radius: 20px;
            padding: 0.95rem 1rem;
        }
        .ia-control-title {
            font-size: 0.75rem;
            letter-spacing: 0.16em;
            text-transform: uppercase;
            color: #64748b;
            font-weight: 800;
            margin-bottom: 0.2rem;
        }
        .ia-control-copy {
            color: #475569;
            font-size: 0.88rem;
            line-height: 1.46;
            margin-bottom: 0.75rem;
        }
        .ia-stick-stage {
            position: relative;
            overflow: hidden;
            min-height: 250px;
            background:
              radial-gradient(circle at top right, rgba(37,99,235,0.14), transparent 24%),
              linear-gradient(180deg, #0f172a 0%, #13223f 100%);
            border-radius: 22px;
            border: 1px solid rgba(255,255,255,0.08);
            padding: 1rem 1rem 1.05rem 1rem;
            color: white;
            display: flex;
            flex-direction: column;
            justify-content: space-between;
            gap: 0.8rem;
        }
        .ia-stick-stage::after {
            content: "";
            position: absolute;
            left: 28px;
            right: 28px;
            bottom: 70px;
            height: 2px;
            background: linear-gradient(90deg, transparent, rgba(255,255,255,0.24), transparent);
        }
        .ia-stick-stage-top {
            position: relative;
            z-index: 2;
            max-width: 100%;
        }
        .ia-stick-headline {
            font-size: 0.8rem;
            letter-spacing: 0.16em;
            text-transform: uppercase;
            color: rgba(255,255,255,0.74);
            margin-bottom: 0.2rem;
            font-weight: 800;
        }
        .ia-stick-copy {
            color: rgba(226,232,240,0.9);
            font-size: 0.87rem;
            line-height: 1.46;
            max-width: 100%;
        }
        .ia-stick-row {
            position: relative;
            z-index: 2;
            display: grid;
            grid-template-columns: repeat(3, minmax(90px, 1fr));
            gap: 0.35rem;
            align-items: end;
            padding: 0 0.15rem;
        }
        .ia-stick-operator {
            width: 100%;
            min-height: 142px;
            position: relative;
            display: flex;
            flex-direction: column;
            align-items: center;
            justify-content: end;
            gap: 0.18rem;
            transform-origin: bottom center;
            animation: ia-float 3.4s ease-in-out infinite;
        }
        .ia-stick-operator:nth-child(2) { animation-delay: 0.3s; }
        .ia-stick-operator:nth-child(3) { animation-delay: 0.6s; }
        .ia-stick-figure {
            position: relative;
            width: 86px;
            height: 108px;
        }
        .ia-stick-figure svg {
            width: 86px;
            height: 108px;
        }
        .ia-stick-operator .label {
            font-size: 0.67rem;
            letter-spacing: 0.1em;
            text-transform: uppercase;
            color: rgba(248,250,252,0.92);
            white-space: nowrap;
            font-weight: 800;
        }
        .ia-stick-role {
            font-size: 0.64rem;
            color: rgba(191,219,254,0.92);
            letter-spacing: 0.08em;
            text-transform: uppercase;
            white-space: nowrap;
        }
        .ia-stick-operator .bubble {
            position: static;
            border-radius: 999px;
            background: rgba(255,255,255,0.08);
            border: 1px solid rgba(255,255,255,0.12);
            color: rgba(255,255,255,0.88);
            padding: 0.16rem 0.44rem;
            font-size: 0.64rem;
            white-space: nowrap;
            margin-bottom: 0.12rem;
        }
        .ia-stick-operator.safe .bubble { background: rgba(16,185,129,0.16); }
        .ia-stick-operator.review .bubble { background: rgba(245,158,11,0.16); }
        .ia-stick-operator.blocked .bubble { background: rgba(239,68,68,0.18); }
        .ia-stick-arm-scan {
            transform-origin: 42px 42px;
            animation: ia-scan-arm 1.8s ease-in-out infinite alternate;
        }
        .ia-stick-arm-sort {
            transform-origin: 52px 48px;
            animation: ia-sort-arm 1.6s ease-in-out infinite alternate;
        }
        .ia-stick-arm-guard {
            transform-origin: 54px 48px;
            animation: ia-guard-arm 1.5s ease-in-out infinite alternate;
        }
        .ia-stick-prop {
            position: absolute;
            pointer-events: none;
        }
        .ia-prop-magnifier {
            left: 2px;
            top: 34px;
            width: 19px;
            height: 19px;
            border: 2px solid rgba(191,219,254,0.92);
            border-radius: 999px;
            animation: ia-scan-glass 1.8s ease-in-out infinite alternate;
        }
        .ia-prop-magnifier::after {
            content: "";
            position: absolute;
            width: 11px;
            height: 2px;
            background: rgba(191,219,254,0.92);
            right: -7px;
            bottom: -1px;
            transform: rotate(40deg);
            border-radius: 999px;
        }
        .ia-prop-envelope {
            left: 58px;
            top: 38px;
            width: 18px;
            height: 12px;
            border: 1.8px solid rgba(226,232,240,0.88);
            border-radius: 3px;
            animation: ia-envelope-bob 1.5s ease-in-out infinite alternate;
        }
        .ia-prop-envelope::before {
            content: "";
            position: absolute;
            left: 1px;
            right: 1px;
            top: 2px;
            height: 1.8px;
            background: rgba(226,232,240,0.88);
            transform: skewY(-24deg);
        }
        .ia-prop-envelope.second {
            left: 50px;
            top: 48px;
            transform: scale(0.9);
            opacity: 0.72;
            animation-delay: 0.24s;
        }
        .ia-prop-shield {
            right: 2px;
            top: 34px;
            width: 20px;
            height: 24px;
            background: rgba(191,219,254,0.18);
            border: 2px solid rgba(191,219,254,0.9);
            clip-path: polygon(50% 0%, 96% 20%, 88% 74%, 50% 100%, 12% 74%, 4% 20%);
            animation: ia-shield-pulse 1.6s ease-in-out infinite;
        }
        .ia-prop-shield::after {
            content: "";
            position: absolute;
            left: 7px;
            top: 6px;
            width: 6px;
            height: 10px;
            border-right: 2px solid rgba(255,255,255,0.9);
            border-bottom: 2px solid rgba(255,255,255,0.9);
            transform: rotate(35deg);
        }
        @keyframes ia-float {
            0%, 100% { transform: translateY(0px); }
            50% { transform: translateY(-4px); }
        }
        @keyframes ia-scan-arm {
            from { transform: rotate(-10deg); }
            to { transform: rotate(12deg); }
        }
        @keyframes ia-sort-arm {
            from { transform: rotate(-4deg); }
            to { transform: rotate(16deg); }
        }
        @keyframes ia-guard-arm {
            from { transform: rotate(-16deg); }
            to { transform: rotate(6deg); }
        }
        @keyframes ia-scan-glass {
            from { transform: translateX(0px) translateY(0px) rotate(-12deg); }
            to { transform: translateX(7px) translateY(-2px) rotate(10deg); }
        }
        @keyframes ia-envelope-bob {
            from { transform: translateY(0px) rotate(-4deg); }
            to { transform: translateY(-6px) rotate(4deg); }
        }
        @keyframes ia-shield-pulse {
            0%, 100% { transform: scale(1); opacity: 0.78; }
            50% { transform: scale(1.08); opacity: 1; }
        }
        .ia-metric-strip {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
            gap: 0.85rem;
            margin: 0.35rem 0 1rem 0;
        }
        .ia-metric-card {
            background: rgba(255,255,255,0.88);
            border: 1px solid var(--ia-line);
            border-radius: 18px;
            padding: 0.9rem 1rem;
            box-shadow: 0 12px 28px rgba(15, 23, 42, 0.06);
        }
        .ia-metric-label {
            font-size: 0.74rem;
            text-transform: uppercase;
            letter-spacing: 0.12em;
            color: #64748b;
            margin-bottom: 0.35rem;
        }
        .ia-metric-value {
            font-size: 1.55rem;
            font-weight: 700;
            color: var(--ia-ink);
            line-height: 1.1;
        }
        .ia-metric-note {
            font-size: 0.82rem;
            color: var(--ia-subtle);
            margin-top: 0.28rem;
        }
        .ia-metric-card[data-tone="primary"] {
            background: linear-gradient(180deg, rgba(219,234,254,0.78), rgba(255,255,255,0.92));
        }
        .ia-metric-card[data-tone="success"] {
            background: linear-gradient(180deg, rgba(209,250,229,0.78), rgba(255,255,255,0.92));
        }
        .ia-metric-card[data-tone="warning"] {
            background: linear-gradient(180deg, rgba(254,243,199,0.78), rgba(255,255,255,0.92));
        }
        .ia-metric-card[data-tone="danger"] {
            background: linear-gradient(180deg, rgba(254,226,226,0.78), rgba(255,255,255,0.92));
        }
        .ia-subsection {
            display: flex;
            align-items: center;
            justify-content: space-between;
            gap: 0.75rem;
            margin-bottom: 0.75rem;
        }
        .ia-subsection-label {
            font-size: 0.76rem;
            letter-spacing: 0.14em;
            text-transform: uppercase;
            color: #64748b;
            font-weight: 700;
        }
        .ia-pill {
            display: inline-flex;
            align-items: center;
            gap: 0.35rem;
            border-radius: 999px;
            padding: 0.28rem 0.62rem;
            font-size: 0.76rem;
            font-weight: 700;
            border: 1px solid transparent;
            white-space: nowrap;
            word-break: keep-all;
        }
        .ia-pill-safe {
            background: rgba(16,185,129,0.12);
            color: #047857;
            border-color: rgba(16,185,129,0.16);
        }
        .ia-pill-review {
            background: rgba(245,158,11,0.12);
            color: #b45309;
            border-color: rgba(245,158,11,0.16);
        }
        .ia-pill-blocked {
            background: rgba(239,68,68,0.12);
            color: #b91c1c;
            border-color: rgba(239,68,68,0.16);
        }
        .ia-pill-neutral {
            background: rgba(37,99,235,0.10);
            color: #1d4ed8;
            border-color: rgba(37,99,235,0.12);
        }
        .ia-callout {
            border-radius: 18px;
            padding: 0.9rem 1rem;
            margin: 0.2rem 0 0.9rem 0;
            border: 1px solid transparent;
        }
        .ia-callout-title {
            font-weight: 700;
            margin-bottom: 0.2rem;
            color: var(--ia-ink);
        }
        .ia-callout-body {
            color: #475569;
            font-size: 0.93rem;
            line-height: 1.5;
        }
        .ia-callout-info {
            background: rgba(219,234,254,0.72);
            border-color: rgba(59,130,246,0.16);
        }
        .ia-callout-warning {
            background: rgba(254,243,199,0.78);
            border-color: rgba(245,158,11,0.16);
        }
        .ia-callout-success {
            background: rgba(220,252,231,0.72);
            border-color: rgba(16,185,129,0.16);
        }
        .ia-sidebar-card {
            background: rgba(255,255,255,0.06);
            border: 1px solid rgba(255,255,255,0.12);
            border-radius: 18px;
            padding: 0.9rem 0.95rem;
            margin-bottom: 0.9rem;
        }
        .ia-sidebar-title {
            color: #f8fafc;
            font-size: 0.9rem;
            font-weight: 700;
            margin-bottom: 0.2rem;
        }
        .ia-sidebar-body {
            color: #cbd5e1;
            font-size: 0.84rem;
            line-height: 1.45;
        }
        .ia-empty-state {
            background: rgba(255,255,255,0.88);
            border: 1px dashed rgba(148,163,184,0.34);
            border-radius: 24px;
            padding: 1.2rem 1.25rem;
        }
        .ia-empty-title {
            color: var(--ia-ink);
            font-size: 1.1rem;
            font-weight: 700;
            margin-bottom: 0.25rem;
        }
        .ia-empty-copy {
            color: #475569;
            line-height: 1.55;
            margin-bottom: 0.85rem;
        }
        .ia-empty-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
            gap: 0.7rem;
        }
        .ia-empty-step {
            background: rgba(248,250,252,0.85);
            border: 1px solid rgba(148,163,184,0.18);
            border-radius: 18px;
            padding: 0.8rem 0.85rem;
        }
        .ia-empty-step h4 {
            margin: 0 0 0.2rem 0;
            color: var(--ia-ink);
            font-size: 0.95rem;
        }
        .ia-empty-step p {
            margin: 0;
            color: #64748b;
            font-size: 0.85rem;
            line-height: 1.45;
        }
        .ia-lane-summary {
            display: flex;
            flex-wrap: wrap;
            gap: 0.45rem;
            margin-bottom: 0.85rem;
        }
        .ia-panel-hint {
            color: #64748b;
            font-size: 0.84rem;
            margin-top: -0.2rem;
            margin-bottom: 0.65rem;
        }
        div[data-testid="stButton"] button {
            border-radius: 14px;
            border: 1px solid rgba(15,23,42,0.08);
            box-shadow: 0 8px 20px rgba(15,23,42,0.06);
            font-weight: 700;
            min-height: 2.9rem;
            white-space: normal !important;
            word-break: normal !important;
            writing-mode: horizontal-tb !important;
            text-orientation: mixed !important;
            line-height: 1.25;
            padding-top: 0.55rem;
            padding-bottom: 0.55rem;
        }
        div[data-testid="stButton"] button p,
        div[data-testid="stButton"] button span {
            color: inherit !important;
            white-space: normal !important;
            word-break: normal !important;
            writing-mode: horizontal-tb !important;
            display: inline-block !important;
            max-width: 100% !important;
            text-align: center;
        }
        div[data-testid="stButton"] button[kind="primary"] {
            background: linear-gradient(180deg, #3b82f6 0%, #1d4ed8 100%);
            color: white;
            border-color: rgba(255,255,255,0.12);
        }
        div[data-testid="stButton"] button[kind="secondary"] {
            background: rgba(255,255,255,0.9);
            color: #0f172a;
        }
        /* Final monochrome override */
        :root {
            --ia-ink: #111111;
            --ia-subtle: #525252;
            --ia-line: rgba(17, 17, 17, 0.12);
        }
        .stApp,
        .stApp [data-testid="stAppViewContainer"] {
            background: #ffffff !important;
            color: #111111 !important;
        }
        .stApp h1,
        .stApp h2,
        .stApp h3,
        .stApp h4,
        .stApp h5,
        .stApp h6,
        .stApp p,
        .stApp li,
        .stApp label,
        .stApp span,
        .stApp small,
        .stApp div,
        .stApp div[data-testid="stMarkdownContainer"] p,
        .stApp div[data-testid="stMarkdownContainer"] li,
        .stApp div[data-testid="stCaptionContainer"] {
            color: #111111;
        }
        div[data-testid="stVerticalBlockBorderWrapper"],
        div[data-testid="stForm"],
        div[data-testid="stExpander"],
        .ia-card,
        .ia-workspace-bar,
        .ia-control-card,
        .ia-metric-card,
        .ia-empty-state,
        .ia-empty-step,
        .ia-callout,
        .ia-sidebar-card {
            background: #ffffff !important;
            color: #111111 !important;
            border: 1px solid rgba(17,17,17,0.12) !important;
            box-shadow: 0 10px 24px rgba(0,0,0,0.05) !important;
        }
        .ia-workspace-title,
        .ia-control-title,
        .ia-subsection-label,
        .ia-metric-label,
        .ia-panel-hint,
        .ia-section-note,
        .ia-empty-step p,
        .ia-metric-note,
        .ia-workspace-copy,
        .ia-control-copy,
        .ia-empty-copy,
        .ia-callout-body {
            color: #525252 !important;
        }
        .ia-hero,
        .ia-stick-stage {
            background: #111111 !important;
            color: #ffffff !important;
            border: 1px solid rgba(255,255,255,0.08) !important;
            box-shadow: 0 18px 36px rgba(0,0,0,0.18) !important;
        }
        .ia-hero::after,
        .ia-stick-stage::after {
            background: rgba(255,255,255,0.12) !important;
        }
        .ia-hero h1,
        .ia-hero h2,
        .ia-hero h3,
        .ia-hero p,
        .ia-hero span,
        .ia-hero div,
        .ia-hero small,
        .ia-stick-stage h1,
        .ia-stick-stage h2,
        .ia-stick-stage h3,
        .ia-stick-stage p,
        .ia-stick-stage span,
        .ia-stick-stage div,
        .ia-stick-stage small {
            color: #ffffff !important;
        }
        .ia-chip,
        .ia-pill,
        .ia-pill-safe,
        .ia-pill-review,
        .ia-pill-blocked,
        .ia-pill-neutral {
            background: #ffffff !important;
            color: #111111 !important;
            border: 1px solid rgba(17,17,17,0.16) !important;
        }
        .ia-chip-dark {
            background: rgba(255,255,255,0.08) !important;
            color: #ffffff !important;
            border: 1px solid rgba(255,255,255,0.18) !important;
        }
        .ia-callout-info,
        .ia-callout-warning,
        .ia-callout-success {
            background: #f7f7f7 !important;
            border-color: rgba(17,17,17,0.14) !important;
        }
        .ia-callout-title,
        .ia-empty-title,
        .ia-empty-step h4,
        .ia-metric-value,
        .ia-sidebar-title {
            color: #111111 !important;
        }
        .ia-sidebar-body {
            color: #f5f5f5 !important;
        }
        div[data-testid="stTabs"] button {
            background: #ffffff !important;
            color: #111111 !important;
            border: 1px solid rgba(17,17,17,0.12) !important;
        }
        div[data-testid="stTabs"] button[aria-selected="true"] {
            background: #111111 !important;
            color: #ffffff !important;
        }
        div[data-testid="stTabs"] button[aria-selected="true"] p,
        div[data-testid="stTabs"] button[aria-selected="true"] span {
            color: #ffffff !important;
        }
        div[data-testid="stButton"] button {
            background: #ffffff !important;
            color: #111111 !important;
            border: 1px solid rgba(17,17,17,0.18) !important;
            box-shadow: 0 8px 18px rgba(0,0,0,0.04) !important;
        }
        div[data-testid="stButton"] button[kind="primary"] {
            background: #111111 !important;
            color: #ffffff !important;
            border-color: #111111 !important;
        }
        div[data-testid="stButton"] button[kind="primary"] p,
        div[data-testid="stButton"] button[kind="primary"] span {
            color: #ffffff !important;
        }
        body [data-baseweb="select"] > div,
        body [data-baseweb="input"] > div,
        body input,
        body textarea {
            background: #ffffff !important;
            color: #111111 !important;
            border: 1px solid rgba(17,17,17,0.18) !important;
        }
        body [data-baseweb="select"] *,
        body [data-baseweb="input"] *,
        body [role="combobox"] *,
        body [data-baseweb="tag"] *,
        body input::placeholder,
        body textarea::placeholder {
            color: #111111 !important;
            opacity: 1 !important;
        }
        body [data-baseweb="tag"] {
            background: #111111 !important;
            color: #ffffff !important;
            border: 1px solid #111111 !important;
        }
        body [data-baseweb="select"] svg,
        body [data-baseweb="input"] svg,
        body [data-baseweb="popover"] svg {
            fill: #111111 !important;
            color: #111111 !important;
        }
        body [data-baseweb="popover"] {
            z-index: 9999 !important;
        }
        body [data-baseweb="popover"] > div,
        body ul[role="listbox"],
        body div[role="listbox"] {
            background: #ffffff !important;
            color: #111111 !important;
            border: 1px solid rgba(17,17,17,0.18) !important;
            box-shadow: 0 14px 30px rgba(0,0,0,0.12) !important;
        }
        body li[role="option"],
        body div[role="option"] {
            background: #ffffff !important;
            color: #111111 !important;
            border-radius: 10px !important;
        }
        body li[role="option"] *,
        body div[role="option"] * {
            color: #111111 !important;
        }
        body li[role="option"]:hover,
        body div[role="option"]:hover {
            background: #f0f0f0 !important;
        }
        body li[role="option"][aria-selected="true"],
        body div[role="option"][aria-selected="true"] {
            background: #111111 !important;
            color: #ffffff !important;
        }
        body li[role="option"][aria-selected="true"] *,
        body div[role="option"][aria-selected="true"] * {
            color: #ffffff !important;
        }
        @media (max-width: 980px) {
            .ia-workspace-grid {
                grid-template-columns: 1fr;
            }
            .ia-stick-row {
                grid-template-columns: 1fr;
                gap: 0.8rem;
            }
            .ia-stick-stage::after {
                display: none;
            }
            .ia-stick-stage {
                min-height: auto;
            }
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def card_open(title: str, subtitle: Optional[str] = None) -> None:
    html = f'<div class="ia-card"><h3 style="margin:0;color:#0f172a;">{title}</h3>'
    if subtitle:
        html += f'<p style="margin:0.2rem 0 0.8rem;color:#475569;">{subtitle}</p>'
    st.markdown(html, unsafe_allow_html=True)


def card_close() -> None:
    st.markdown("</div>", unsafe_allow_html=True)


def render_metric_bar(items: Iterable[dict]) -> None:
    cards: list[str] = []
    for item in items:
        label = escape(str(item.get("label", "")))
        value = escape(str(item.get("value", "")))
        note = escape(str(item.get("note", "")))
        tone = escape(str(item.get("tone", "neutral")))
        cards.append(
            "\n".join(
                [
                    f'<div class="ia-metric-card" data-tone="{tone}">',
                    f'<div class="ia-metric-label">{label}</div>',
                    f'<div class="ia-metric-value">{value}</div>',
                    f'<div class="ia-metric-note">{note}</div>' if note else "",
                    "</div>",
                ]
            )
        )
    st.markdown(
        f'<div class="ia-metric-strip">{"".join(cards)}</div>',
        unsafe_allow_html=True,
    )


def render_pill_row(items: Iterable[tuple[str, str]], *, dark: bool = False) -> None:
    classes = "ia-chip ia-chip-dark" if dark else "ia-chip"
    markup = "".join(
        f'<span class="{classes}">{escape(label)}</span>'
        if tone == "chip"
        else f'<span class="ia-pill ia-pill-{escape(tone)}">{escape(label)}</span>'
        for label, tone in items
    )
    st.markdown(markup, unsafe_allow_html=True)


def render_callout(title: str, body: str, *, tone: str = "info") -> None:
    st.markdown(
        "\n".join(
            [
                f'<div class="ia-callout ia-callout-{escape(tone)}">',
                f'<div class="ia-callout-title">{escape(title)}</div>',
                f'<div class="ia-callout-body">{escape(body)}</div>',
                "</div>",
            ]
        ),
        unsafe_allow_html=True,
    )


def render_empty_state(title: str, body: str, steps: Iterable[tuple[str, str]]) -> None:
    grid = "".join(
        [
            "\n".join(
                [
                    '<div class="ia-empty-step">',
                    f"<h4>{escape(step_title)}</h4>",
                    f"<p>{escape(step_body)}</p>",
                    "</div>",
                ]
            )
            for step_title, step_body in steps
        ]
    )
    st.markdown(
        "\n".join(
            [
                '<div class="ia-empty-state">',
                f'<div class="ia-empty-title">{escape(title)}</div>',
                f'<div class="ia-empty-copy">{escape(body)}</div>',
                f'<div class="ia-empty-grid">{grid}</div>',
                "</div>",
            ]
        ),
        unsafe_allow_html=True,
    )


def render_workspace_shell(title: str, body: str, aside_html: str) -> None:
    st.markdown(
        "\n".join(
            [
                '<div class="ia-workspace-bar">',
                '<div class="ia-workspace-head">',
                '<div>',
                '<div class="ia-workspace-title">Control Deck</div>',
                f'<div class="ia-workspace-copy">{escape(body)}</div>',
                "</div>",
                "</div>",
                '<div class="ia-workspace-grid">',
                "\n".join(
                    [
                        '<div class="ia-control-card">',
                        f'<div class="ia-control-title">{escape(title)}</div>',
                        '<div class="ia-control-copy">'
                        "Tune provider, scale, and safety settings directly in the workspace."
                        "</div>",
                    ]
                ),
                aside_html,
                "</div>",
            ]
        ),
        unsafe_allow_html=True,
    )


def close_workspace_shell() -> None:
    st.markdown("</div></div>", unsafe_allow_html=True)


def render_operator_stage(status: str, summary: str) -> None:
    tone_map = {
        "safe": [
            ("Scout", "signal mapped", "Classifier", "safe", "scan"),
            ("Anchor", "queue sorted", "Coordinator", "safe", "sort"),
            ("Guard", "checks clear", "Safety", "safe", "guard"),
        ],
        "review": [
            ("Scout", "flags raised", "Classifier", "review", "scan"),
            ("Anchor", "approval wait", "Coordinator", "review", "sort"),
            ("Guard", "risk noted", "Safety", "review", "guard"),
        ],
        "blocked": [
            ("Scout", "threat found", "Classifier", "blocked", "scan"),
            ("Anchor", "action paused", "Coordinator", "blocked", "sort"),
            ("Guard", "blocked path", "Safety", "blocked", "guard"),
        ],
    }
    operators = tone_map.get(status, tone_map["review"])
    cards = []
    for label, bubble, role, tone, motion in operators:
        if motion == "scan":
            arm_class = "ia-stick-arm-scan"
            props = ['<div class="ia-stick-prop ia-prop-magnifier"></div>']
        elif motion == "sort":
            arm_class = "ia-stick-arm-sort"
            props = [
                '<div class="ia-stick-prop ia-prop-envelope"></div>',
                '<div class="ia-stick-prop ia-prop-envelope second"></div>',
            ]
        else:
            arm_class = "ia-stick-arm-guard"
            props = ['<div class="ia-stick-prop ia-prop-shield"></div>']
        cards.append(
            "\n".join(
                [
                    f'<div class="ia-stick-operator {tone}">',
                    f'<div class="bubble">{escape(bubble)}</div>',
                    '<div class="ia-stick-figure">',
                    *props,
                    (
                        '<svg viewBox="0 0 86 108" fill="none" '
                        'xmlns="http://www.w3.org/2000/svg">'
                    ),
                    '<circle cx="43" cy="18" r="9" stroke="white" stroke-width="3"/>',
                    (
                        '<path d="M43 27 L43 58" stroke="white" stroke-width="3" '
                        'stroke-linecap="round"/>'
                    ),
                    (
                        f'<path class="{arm_class}" d="M43 39 L26 48" '
                        'stroke="white" stroke-width="3" stroke-linecap="round"/>'
                    ),
                    (
                        '<path d="M43 39 L60 47" stroke="white" stroke-width="3" '
                        'stroke-linecap="round"/>'
                    ),
                    (
                        '<path d="M43 58 L31 88" stroke="white" stroke-width="3" '
                        'stroke-linecap="round"/>'
                    ),
                    (
                        '<path d="M43 58 L57 88" stroke="white" stroke-width="3" '
                        'stroke-linecap="round"/>'
                    ),
                    "</svg>",
                    "</div>",
                    f'<div class="label">{escape(label)}</div>',
                    f'<div class="ia-stick-role">{escape(role)}</div>',
                    "</div>",
                ]
            )
        )
    st.markdown(
        "\n".join(
            [
                '<div class="ia-stick-stage">',
                '<div class="ia-stick-stage-top">',
                '<div class="ia-stick-headline">Operator Crew</div>',
                f'<div class="ia-stick-copy">{escape(summary)}</div>',
                "</div>",
                f'<div class="ia-stick-row">{"".join(cards)}</div>',
                "</div>",
            ]
        ),
        unsafe_allow_html=True,
    )
