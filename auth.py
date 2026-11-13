# auth.py
# Accounts: sign up with email + password, confirm with an emailed code, log in, log out.
# Supabase does the hard, security-sensitive parts (storing passwords, sending emails).

import streamlit as st
from supabase import create_client

from ai_scanner import get_secret

MIN_PASSWORD_LENGTH = 8


def get_client():
    """
    Each visitor gets their OWN Supabase connection, kept in their session.
    (If everyone shared one connection, one person's login could leak to another!)
    """
    if "supabase" not in st.session_state:
        url = get_secret("SUPABASE_URL")
        key = get_secret("SUPABASE_KEY")
        if not url or not key:
            st.error("Accounts aren't set up yet. (Developer: add SUPABASE_URL and SUPABASE_KEY to your secrets.)")
            st.stop()
        st.session_state.supabase = create_client(url, key)
    return st.session_state.supabase


def current_user():
    """Returns {'id': ..., 'email': ...} if someone is logged in, otherwise None."""
    return st.session_state.get("user")


def _log_in_user(user):
    st.session_state.user = {"id": user.id, "email": user.email}


def logout():
    try:
        get_client().auth.sign_out()
    except Exception:
        pass
    # Wipe everything from this session (rooms, photos, login) so the next person sees nothing
    for key in list(st.session_state.keys()):
        del st.session_state[key]
    st.rerun()


# ---------- The screens ----------

def show_login_page():
    st.title("🏠 Home Contents Scanner")

    # If someone has just signed up, show the "enter your code" screen instead
    if st.session_state.get("pending_email"):
        _show_code_screen()
        return

    st.write("Log in or create a free account to start your home contents list.")
    tab_login, tab_signup = st.tabs(["Log in", "Create account"])

    with tab_login:
        _show_login_form()

    with tab_signup:
        _show_signup_form()


def _show_login_form():
    with st.form("login_form"):
        email = st.text_input("Email")
        password = st.text_input("Password", type="password")
        submitted = st.form_submit_button("Log in", type="primary")

    if not submitted:
        return

    email = email.strip().lower()
    logged_in = False
    try:
        result = get_client().auth.sign_in_with_password({"email": email, "password": password})
        _log_in_user(result.user)
        logged_in = True
    except Exception as e:
        message = str(e).lower()
        print(f"[login error] {e!r}")
        if "not confirmed" in message:
            # They signed up but never entered the code. Send them to the code screen.
            st.session_state.pending_email = email
            _resend_code(email, quiet=True)
            st.rerun()
        else:
            st.error("That email or password isn't right. Please try again.")

    # Note: st.rerun() must be OUTSIDE the try/except, or the except would catch it
    if logged_in:
        st.rerun()


def _show_signup_form():
    with st.form("signup_form"):
        email = st.text_input("Email")
        password = st.text_input(f"Password (at least {MIN_PASSWORD_LENGTH} characters)", type="password")
        password2 = st.text_input("Type the password again", type="password")
        submitted = st.form_submit_button("Create account", type="primary")

    if not submitted:
        return

    email = email.strip().lower()

    # Check the form before bothering Supabase
    if "@" not in email or "." not in email:
        st.error("Please enter a valid email address.")
        return
    if len(password) < MIN_PASSWORD_LENGTH:
        st.error(f"Your password needs at least {MIN_PASSWORD_LENGTH} characters.")
        return
    if password != password2:
        st.error("The two passwords don't match.")
        return

    signed_up = False
    try:
        result = get_client().auth.sign_up({"email": email, "password": password})
        # Supabase quietly returns an empty identity list if the email already has an account
        if result.user is not None and result.user.identities == []:
            st.warning("That email may already have an account. Try the Log in tab instead.")
        else:
            st.session_state.pending_email = email
            signed_up = True
    except Exception as e:
        print(f"[signup error] {e!r}")
        message = str(e).lower()
        if "rate limit" in message or "too many" in message:
            st.error("Too many sign-up emails have been sent recently. Please wait a while and try again.")
        else:
            st.error("Couldn't create your account. Please check your details and try again.")

    if signed_up:
        st.rerun()


def _show_code_screen():
    email = st.session_state.pending_email
    st.subheader("Check your email 📧")
    st.write(f"We've sent a confirmation code to **{email}**. Enter it below to finish creating your account.")
    st.caption("Can't see it? Check your spam or junk folder. It can take a minute to arrive.")

    with st.form("code_form"):
        code = st.text_input("Confirmation code", max_chars=10)
        submitted = st.form_submit_button("Confirm", type="primary")

    if submitted:
        if _verify_code(email, code.strip()):
            del st.session_state["pending_email"]
            st.rerun()
        else:
            st.error("That code didn't work. Check it and try again, or send a new code.")

    col1, col2 = st.columns(2)
    if col1.button("Send a new code"):
        _resend_code(email)
    if col2.button("Use a different email"):
        del st.session_state["pending_email"]
        st.rerun()


def _verify_code(email, code):
    """Check the emailed code with Supabase. Returns True if it worked."""
    client = get_client()
    # Supabase has used two names for this check over time, so we try both
    for code_type in ("email", "signup"):
        try:
            result = client.auth.verify_otp({"email": email, "token": code, "type": code_type})
            if result.user:
                _log_in_user(result.user)
                return True
        except Exception as e:
            print(f"[verify error, type={code_type}] {e!r}")
    return False


def _resend_code(email, quiet=False):
    try:
        get_client().auth.resend({"type": "signup", "email": email})
        if not quiet:
            st.success("A new code is on its way.")
    except Exception as e:
        print(f"[resend error] {e!r}")
        if not quiet:
            st.error("Couldn't send a new code yet. Please wait a minute and try again.")
            
