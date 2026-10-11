"""Login page: email + password only."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import streamlit as st

from digest import db, auth


def login_page() -> None:
    """Simple login form."""
    # If already logged in, redirect to app
    if st.session_state.get("user_id"):
        st.switch_page("pages/app.py")
    
    st.set_page_config(page_title="Login - AINewsPost", layout="centered")
    
    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        st.markdown("### 📰 AINewsPost")
        st.markdown("---")
        
        email = st.text_input("Email", placeholder="your@email.com")
        password = st.text_input("Password", type="password")
        
        if st.button("Login", type="primary", use_container_width=True):
            if not email or not password:
                st.error("Please enter email and password.")
                return
            
            try:
                with db.connect() as conn:
                    user_id = auth.login(conn, email, password)
                st.session_state["user_id"] = user_id
                st.session_state["user_email"] = email
                st.success("Logged in!")
                st.switch_page("pages/app.py")
            except auth.AuthError as e:
                st.error(str(e))
            except db.DatabaseProblem as e:
                st.error(str(e))
            except Exception as e:
                st.error(f"Login failed: {e}")


if __name__ == "__main__":
    if st.session_state.get("user_id"):
        st.switch_page("pages/app.py")
    login_page()
