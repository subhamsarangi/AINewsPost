"""Landing page: login link or redirect if logged in."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import streamlit as st


def home_page() -> None:
    """Simple landing page."""
    st.set_page_config(
        page_title="AINewsPost - Your AI News Digest",
        page_icon="📰",
        layout="centered",
    )
    
    # If already logged in, redirect to app
    if st.session_state.get("user_id"):
        st.switch_page("pages/app.py")
    
    # Landing page
    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        st.markdown("# 📰 AINewsPost")
        st.markdown("### Your personal AI news digest")
        st.markdown(
            """
            Curated AI news from top sources:
            - **OpenAI**, **DeepMind**, **Anthropic** research pages
            - **Hacker News** AI posts
            - **The Batch** newsletter
            - And more...
            
            Delivered daily to your PDF.
            """
        )
        
        if st.button("Sign In", type="primary", use_container_width=True, key="home_login"):
            st.switch_page("login.py")


if __name__ == "__main__":
    home_page()
