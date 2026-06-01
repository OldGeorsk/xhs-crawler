"""
CDP (Chrome DevTools Protocol) helper.

Instead of launching a fresh Playwright browser and injecting cookies,
this module connects to YOUR existing Chrome browser — the one you use
every day, already logged into Xiaohongshu.

Why this works better:
    - Real browser fingerprint (no webdriver flags).
    - Real localStorage, service workers, IndexedDB.
    - Session trusted by XHS for ALL page layouts (old + new).

Setup (one-time):
    1. Close ALL Chrome windows.
    2. Launch Chrome from terminal with the debug port open:

       "C:\Program Files\Google\Chrome\Application\chrome.exe" --remote-debugging-port=9222

    3. Browse to xiaohongshu.com and log in if not already.
    4. Leave Chrome running and run the crawler with --cdp.
"""

import subprocess
import sys
from typing import Optional

from playwright.sync_api import Browser, BrowserContext, Page, sync_playwright

CDP_URL = "http://localhost:9222"


def is_cdp_available() -> bool:
    """Check whether Chrome is running with the debug port open."""
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.connect_over_cdp(CDP_URL)
            browser.close()
            return True
    except Exception:
        return False


def connect_to_chrome() -> Browser:
    """
    Connect Playwright to an already-running Chrome instance via CDP.

    Returns a connected Browser object.  The caller is responsible for
    closing it when done.
    """
    pw = sync_playwright().start()
    browser = pw.chromium.connect_over_cdp(CDP_URL)
    return browser


def get_chrome_page() -> Page:
    """
    Connect and return the first available page (or create a new one).

    Suitable as a drop-in replacement for creating a browser+context+page
    in the synchronizer.
    """
    pw = sync_playwright().start()
    browser = pw.chromium.connect_over_cdp(CDP_URL)

    # Use an existing open page or create a new one
    if browser.contexts:
        context = browser.contexts[0]
    else:
        context = browser.new_context()

    if context.pages:
        page = context.pages[0]
    else:
        page = context.new_page()

    return page


def print_setup_instructions() -> None:
    """Print one-time setup instructions for the user."""
    print("""
============================================================
  CDP Mode — Connect to Your Real Chrome
============================================================

  One-time setup:

  1. Close ALL Chrome windows completely.

  2. Open a terminal (cmd) and run:

     "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe" --remote-debugging-port=9222

     If Chrome is installed elsewhere, adjust the path.

  3. In the Chrome window that opens, go to:
     https://www.xiaohongshu.com
     and log in if you aren't already.

  4. Leave that Chrome window open.

  5. Run the crawler with --cdp:

     python main.py --cdp
     python main.py --cdp --creator 4

  This only needs to be done ONCE.  As long as Chrome stays
  running with --remote-debugging-port=9222, every subsequent
  sync will use your real session.
============================================================
""")


def launch_chrome_with_debug() -> bool:
    """
    Attempt to launch Chrome with the remote debugging port.

    Returns True if Chrome was launched successfully.
    """
    # Try common Chrome paths on Windows
    candidates = [
        "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe",
        "C:\\Program Files (x86)\\Google\\Chrome\\Application\\chrome.exe",
        f"C:\\Users\\{subprocess.os.environ.get('USERNAME', '')}\\AppData\\Local\\Google\\Chrome\\Application\\chrome.exe",
    ]

    for path in candidates:
        try:
            subprocess.Popen(
                [path, "--remote-debugging-port=9222", "--new-window", "https://www.xiaohongshu.com"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            print(f"[cdp] Launched Chrome from: {path}")
            return True
        except FileNotFoundError:
            continue

    print("[cdp] Could not find Chrome. Please launch it manually:")
    print_setup_instructions()
    return False
