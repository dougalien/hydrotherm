"""Shared helpers: PNG rendering and a copy-able figure display for Streamlit."""

import base64
import io

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import streamlit as st
import streamlit.components.v1 as components


def embed_html(html, height):
    """st.iframe on current Streamlit; components.html on older versions."""
    if hasattr(st, "iframe"):
        st.iframe(html, height=height)
    else:
        components.html(html, height=height)


def to_png(fig) -> bytes:
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=200, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    return buf.getvalue()


def show_figure(png: bytes, name: str, key: str):
    """Show the image with download and copy-to-clipboard buttons."""
    st.image(png)
    c1, c2 = st.columns([1, 1])
    c1.download_button("Download PNG", png, f"{name}.png", "image/png", key=f"dl_{key}")
    b64 = base64.b64encode(png).decode()
    with c2:
        embed_html(
            f"""
            <button id="b" style="padding:6px 14px;font-size:14px;border-radius:6px;border:1px solid #888;
                                  background:#fff;cursor:pointer">Copy image to clipboard</button>
            <span id="m" style="font-family:sans-serif;font-size:13px;margin-left:8px"></span>
            <script>
            document.getElementById('b').onclick = async () => {{
              const m = document.getElementById('m');
              try {{
                const r = await fetch('data:image/png;base64,{b64}');
                const blob = await r.blob();
                await navigator.clipboard.write([new ClipboardItem({{'image/png': blob}})]);
                m.textContent = 'Copied — paste into PowerPoint';
              }} catch (e) {{ m.textContent = 'Blocked by browser — right-click the image and choose Copy image'; }}
            }};
            </script>""",
            height=45,
        )
