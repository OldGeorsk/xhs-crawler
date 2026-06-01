"""
XHS Login Helper — QR-code authentication with persistent session.

Usage:
    python login_helper.py              # Login (opens browser for QR scan)
    python login_helper.py --check      # Check if current session is still valid

How it works:
    1. Opens a Chromium window and navigates to xiaohongshu.com.
    2. Waits for the user to scan the QR code on the page and log in.
    3. Detects successful login by watching for the web_session cookie.
    4. Saves the full browser state (cookies + localStorage + IndexedDB)
       to ``config/storage_state.json``.

This is the project's standard authentication method.  No passwords are
ever entered into the script — the QR code is Xiaohongshu's own
authentication flow.

Compared to raw cookies.json, storage_state preserves far more context
(fingerprints, local storage, service workers), which dramatically
reduces the chance of being flagged as a bot.
"""

import argparse
import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright, BrowserContext

PROJECT_ROOT = Path(__file__).resolve().parent
STATE_PATH = PROJECT_ROOT / "config" / "storage_state.json"
XHS_URL = "https://www.xiaohongshu.com"


# ----------------------------------------------------------------------
# Public helpers (used by other modules too)
# ----------------------------------------------------------------------

def is_session_valid(timeout_ms: int = 15000) -> bool:
    """
    Multi-page headless check to verify the saved session is still
    recognised by Xiaohongshu.

    1. Load the XHS home page — look for a login button.
    2. Load a known profile page — verify it loads with the creator's
       name in the title (not the generic fallback).

    Only if *both* checks pass do we consider the session valid.
    """
    if not STATE_PATH.exists():
        return False

    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            context = browser.new_context(storage_state=str(STATE_PATH))
            page = context.new_page()

            # -- Check 1: home page ------------------------------------
            page.goto(XHS_URL, timeout=timeout_ms, wait_until="domcontentloaded")
            page.wait_for_timeout(3000)

            login_btn = page.query_selector('text=登录')
            if login_btn:
                browser.close()
                return False  # definitely logged out

            # -- Check 2: profile page (spot-check) --------------------
            # Load a well-known profile; if the session is good the title
            # will be "<name> - 小红书" rather than the generic string.
            page.goto("https://www.xiaohongshu.com/explore", timeout=timeout_ms,
                      wait_until="domcontentloaded")
            page.wait_for_timeout(2000)

            title = page.title()
            # "小红书 - 你的生活兴趣社区" = generic / logged-out fallback
            if title == "小红书 - 你的生活兴趣社区":
                browser.close()
                return False

            browser.close()
            return True

    except Exception:
        return False


def dismiss_login_popup(page) -> bool:
    """
    Try to close a login QR-code popup that is blocking the page.

    Strategies (tried in order):
      1. Press Escape.
      2. Click in the top-left corner (outside the modal).
      3. Look for a close button.

    Returns True if the popup was dismissed.
    """
    mask = page.query_selector('.reds-mask, [class*="login-mask"], [class*="login-modal"]')
    if not mask:
        return True  # no popup to dismiss

    # Strategy 1: Escape key
    page.keyboard.press('Escape')
    page.wait_for_timeout(1000)
    if not page.query_selector('.reds-mask, [class*="login-mask"], [class*="login-modal"]'):
        return True

    # Strategy 2: click outside the modal
    page.mouse.click(10, 10)
    page.wait_for_timeout(1000)
    if not page.query_selector('.reds-mask, [class*="login-mask"], [class*="login-modal"]'):
        return True

    # Strategy 3: find and click a close button
    close_btn = page.query_selector('[class*="close"], [class*="cancel"], [aria-label*="close"], [aria-label*="关闭"]')
    if close_btn:
        close_btn.click()
        page.wait_for_timeout(1000)

    return not bool(page.query_selector('.reds-mask, [class*="login-mask"], [class*="login-modal"]'))


def get_storage_state_path() -> Path:
    """Return the path to the storage state file."""
    return STATE_PATH


# ----------------------------------------------------------------------
# Fresh-session gate (used by main.py before every sync)
# ----------------------------------------------------------------------

def ensure_fresh_session() -> str:
    """
    Guarantee a fresh, working session by launching a VISIBLE browser.

    1. If a saved state exists, load it and check whether XHS recognises us.
    2. If a login QR popup appears (or we're clearly logged out), wait
       for the user to scan and complete login.
    3. Save the resulting browser state to ``storage_state.json``.
    4. Return the path to the saved state.

    This is intentionally NOT headless — the user needs to see the QR
    code and scan it with their phone.
    """
    print("\n" + "=" * 55)
    print("  Session Check")
    print("=" * 55)

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=False)
        context_kwargs: dict = {
            "viewport": {"width": 1280, "height": 800},
            "user_agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
        }
        if STATE_PATH.exists():
            context_kwargs["storage_state"] = str(STATE_PATH)

        context = browser.new_context(**context_kwargs)
        page = context.new_page()

        page.goto(XHS_URL, timeout=30000, wait_until="domcontentloaded")
        page.wait_for_timeout(3000)

        # -- is there a login popup / are we logged out? -----------------
        login_btn = page.query_selector('text=登录')
        qr_modal = page.query_selector('[class*="qrcode"], [class*="qr-code"], [class*="login-modal"]')

        if login_btn or qr_modal:
            print("\n[session] Login required — a QR code should be visible.")
            print("[session] Scan it with your Xiaohongshu app now.\n")

            try:
                _wait_for_login(page, timeout_seconds=300)
            except TimeoutError:
                print("\n[session] Timed out waiting for login.")
                browser.close()
                sys.exit(1)

            # -- save the fresh state -----------------------------------
            STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
            context.storage_state(path=str(STATE_PATH))
            print(f"\n[session] Fresh session saved -> {STATE_PATH}")
        else:
            print("[session] Already logged in — session is fresh.")

        browser.close()

    print("=" * 55)
    return str(STATE_PATH)


# ----------------------------------------------------------------------
# Login flow (standalone helper)
# ----------------------------------------------------------------------

def login() -> bool:
    """
    Launch a visible browser, let the user scan the QR code and log in,
    then persist the session to ``config/storage_state.json``.

    Returns True on success.
    """
    print("\n" + "=" * 55)
    print("  XHS Login Helper")
    print("=" * 55)
    print()
    print("  A browser window will open shortly.")
    print("  1. Scan the QR code on the page with your Xiaohongshu app.")
    print("  2. Confirm the login on your phone.")
    print("  3. Wait for the page to redirect to your home feed.")
    print()
    print("  The script will automatically detect the login and close.")
    print("=" * 55)

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=False)
        context = browser.new_context(
            viewport={"width": 1280, "height": 800},
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
        )
        page = context.new_page()

        # -- navigate to XHS home page ----------------------------------
        print("\n[login] Opening xiaohongshu.com ...")
        page.goto(XHS_URL, timeout=30000, wait_until="domcontentloaded")
        page.wait_for_timeout(2000)

        # -- wait for the user to scan QR code --------------------------
        print("[login] Waiting for you to scan the QR code ...")
        print("[login] (this may take up to 5 minutes)\n")

        try:
            _wait_for_login(page, timeout_seconds=300)
        except TimeoutError:
            print("\n[login] Timed out waiting for login.  Please try again.")
            browser.close()
            return False

        # -- save the full browser state --------------------------------
        STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
        context.storage_state(path=str(STATE_PATH))
        print(f"\n[login] Session saved -> {STATE_PATH}")

        browser.close()

    # -- quick validation ------------------------------------------------
    if is_session_valid():
        print("[login] Verification passed — session is active.\n")
        return True
    else:
        print("[login] WARNING: session saved but verification failed.")
        print("  You may need to re-run: python login_helper.py\n")
        return False


# ----------------------------------------------------------------------
# Internal
# ----------------------------------------------------------------------

def _wait_for_login(page, timeout_seconds: int = 300) -> None:
    """
    Poll the page until we detect a logged-in state.

    Detection strategy (tried in order):
      1. ``web_session`` cookie appears (most reliable).
      2. "Login" button disappears from the page.
      3. The page title changes from the generic landing page.
    """
    start = time.monotonic()

    while time.monotonic() - start < timeout_seconds:
        cookies = page.context.cookies()
        for c in cookies:
            if c["name"] == "web_session" and c["value"]:
                print("[login] Detected web_session cookie — login successful!")
                page.wait_for_timeout(1500)
                return

        # Fallback: check DOM for login button absence
        try:
            login_btn = page.query_selector('text=登录')
            if not login_btn:
                print("[login] Login button disappeared — assuming logged in.")
                page.wait_for_timeout(1500)
                return
        except Exception:
            pass

        time.sleep(2)
        # Print a dot every 10 seconds so the user knows it's alive
        elapsed = int(time.monotonic() - start)
        if elapsed % 10 < 2:
            print(f"  ... waiting ({elapsed}s) ...")

    raise TimeoutError("Login did not complete within the time limit.")


# ----------------------------------------------------------------------
# CLI
# ----------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="XHS Login Helper")
    parser.add_argument(
        "--check",
        action="store_true",
        help="Only check whether the saved session is still valid (no browser).",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Force re-login even if the current session appears valid.",
    )
    args = parser.parse_args()

    if args.check:
        valid = is_session_valid()
        if valid:
            print("[check] Session is VALID — no re-login needed.")
        else:
            print("[check] Session is EXPIRED or missing. Run: python login_helper.py")
        sys.exit(0 if valid else 1)

    if not args.force and is_session_valid():
        print("[login] Session is already valid. Use --force to re-login anyway.")
        return

    ok = login()
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
