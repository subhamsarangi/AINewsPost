"""Streamlit entry: builds the sidebar from sources.yaml.

Run from the project root:  uv run streamlit run ui/app.py
Pages: All items (home), Daily picks, Starred, then one page per source grouped by category.
Adding a source to sources.yaml adds its page automatically.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))  # so `import digest` works under streamlit

import streamlit as st  # noqa: E402

st.set_page_config(page_title="AI Digest", page_icon="🗞️", layout="wide")

import digests  # noqa: E402  (ui/digests.py)
import views  # noqa: E402  (ui/views.py)
from digest import db, auth  # noqa: E402
from digest.config import CATEGORIES, load_sources  # noqa: E402


# --- Login guard ---
def _show_login():
    """Show login form instead of app."""
    st.markdown(
        """
        <style>
        [data-testid="stForm"] {
            max-width: 400px;
            margin: 0 auto;
            padding: 2rem;
        }
        .login-container {
            max-width: 500px;
            margin: 2rem auto 0 auto;
            padding: 3rem;
        }
        .login-title {
            font-size: 3.5rem;
            font-weight: 700;
            margin: 0 0 0.5rem 0;
        }
        .login-subtitle {
            font-size: 1.3rem;
            color: #666;
            margin: 0 0 2rem 0;
        }
        .stButton button[kind="primary"] {
            transition: opacity 0.2s;
        }
        .stButton button[kind="primary"]:active {
            opacity: 0.5;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )
    
    st.markdown('<div class="login-container">', unsafe_allow_html=True)
    st.markdown('<div class="login-title">AINewsPost</div>', unsafe_allow_html=True)
    st.markdown('<div class="login-subtitle">Login</div>', unsafe_allow_html=True)
    
    with st.form("login_form", clear_on_submit=False):
        email = st.text_input("Email", placeholder="your@email.com")
        password = st.text_input("Password", type="password")
        submitted = st.form_submit_button("Login", use_container_width=True, type="primary")
        
        if submitted:
            if not email or not password:
                st.error("Enter email and password.")
            else:
                # Show spinner during login
                placeholder = st.empty()
                with placeholder.container():
                    st.info("Logging in...")
                _do_login(email, password)
                placeholder.empty()
    
    st.markdown('</div>', unsafe_allow_html=True)


def _do_login(email: str, password: str):
    """Execute login."""
    try:
        with db.connect() as conn:
            user_id = auth.login(conn, email, password)
        st.session_state["user_id"] = user_id
        st.session_state["user_email"] = email
        st.success("Logged in!")
        st.rerun()
    except auth.AuthError as e:
        st.error(str(e))
    except db.DatabaseProblem as e:
        st.error(str(e))
    except Exception as e:
        st.error(f"Login failed: {e}")


if not st.session_state.get("user_id"):
    # Clear query params when redirecting to login
    st.query_params.clear()
    # Hide sidebar when not logged in
    st.markdown(
        """
        <style>
        [data-testid="stSidebar"] {
            display: none;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )
    _show_login()
    st.stop()


def _navbar():
    """Simple navbar with AINewsPost title and logout."""
    # Reset scroll when page changes
    current_page = st.query_params.get("page", "all")
    if st.session_state.get("_last_page") != current_page:
        st.session_state["_last_page"] = current_page
    
    # FontAwesome icons
    st.markdown(
        f"""
        <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">
        <style>
        .navbar {{
            display: flex;
            align-items: center;
            justify-content: space-between;
            padding: 1rem 0;
            border-bottom: 1px solid #e0e0e0;
            margin-bottom: 1rem;
        }}
        .navbar-title {{
            font-size: 1.5rem;
            font-weight: 600;
        }}
        .navbar-user {{
            color: #666;
            font-size: 0.9rem;
        }}
        </style>
        <div class="navbar">
            <div class="navbar-title"><i class="fas fa-newspaper"></i> AINewsPost</div>
            <div class="navbar-user"><i class="fas fa-user"></i> {st.session_state.get('user_email', 'User')}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    
    # Logout button
    col1, col2 = st.columns([5, 1])
    with col2:
        if st.button("Logout", key="navbar_logout", use_container_width=True):
            st.session_state.clear()
            st.rerun()


def _footer():
    """Simple footer with copyright and link. Sticky to bottom."""
    st.markdown(
        """
        <style>
        [data-testid="stBottomBlockContainer"] {
            padding-bottom: 0;
        }
        .footer {
            position: fixed;
            bottom: 0;
            left: 0;
            right: 0;
            background-color: white;
            border-top: 1px solid #e0e0e0;
            padding: 1rem;
            text-align: center;
            font-size: 0.85rem;
            color: #666;
            z-index: 999;
        }
        </style>
        <div class="footer">
            © 2026 AINewsPost · 
            <a href="https://github.com/subhamsarangi" style="color: #666; text-decoration: none;">Developer</a> · Built with <i class="fas fa-heart" style="color: #e74c3c;"></i>
        </div>
        """,
        unsafe_allow_html=True,
    )

# Fail with a readable message (not a stack trace) if the database is not usable.
if not st.session_state.get("db_ok"):
    try:
        db.check()
        st.session_state["db_ok"] = True
    except db.DatabaseProblem as e:
        st.error(str(e))
        st.caption("Fix the problem above, then reload this page.")
        st.stop()


def _picks_link() -> None:
    """Shown at the top of the home page."""
    st.page_link(
        PICKS_PAGE, label="Daily picks: today's top items, past days, PDF", icon="📄"
    )
    latest = views.run_db(db.list_digests, 1)
    if latest:
        st.caption(
            f"Latest digest: {latest[0]['date']:%A, %B %d, %Y} · {latest[0]['n_items']} picks"
        )
    else:
        st.caption("No digest yet. Open Daily picks to generate one.")


def _all_page():
    views.feed_view("all", "All items", header_extra=_picks_link)


def _starred_page():
    views.feed_view("starred", "Starred", starred_only=True)


def _source_page(src: dict):
    def page():
        views.feed_view(f"src_{src['id']}", src["name"], source=src)

    return st.Page(page, title=src["name"], url_path=src["id"])


CATEGORY_LABELS = {
    "research": "Research",
    "mlops": "MLOps",
    "news": "News",
    "community": "Community",
    "funding": "Funding",
    "other": "Other",
}

PICKS_PAGE = st.Page(
    digests.picks_page, title="Daily picks", url_path="picks", icon="📄"
)

# Only build navigation if logged in
if st.session_state.get("user_id"):
    sections: dict[str, list] = {
        "Overview": [
            st.Page(_all_page, title="All items", url_path="all", default=True),
            PICKS_PAGE,
            st.Page(_starred_page, title="Starred", url_path="starred"),
        ]
    }
    by_category: dict[str, list] = {}
    for src in load_sources():
        by_category.setdefault(src.get("category") or "other", []).append(_source_page(src))
    for cat in [*CATEGORIES, "other"]:
        if cat in by_category:
            sections[CATEGORY_LABELS[cat]] = by_category[cat]

    _navbar()
    st.markdown("<style>.main { padding-bottom: 150px; }</style>", unsafe_allow_html=True)
    st.navigation(sections).run()
    _footer()
