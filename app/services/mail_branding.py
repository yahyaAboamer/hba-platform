"""The brand around the words.

**The plain text is the source, and this is derived from it.** Every template
in `notifications.py` writes one plain-text body; this wraps that exact text in
the logo, a button and a signature. Two consequences worth stating, because
both were the reason for doing it this way:

- The tests assert on the plain text, and they keep working. A second set of
  templates written in HTML would be a second place for the wording to live,
  and the day they drifted a model would be told two different things
  depending on which their mail client rendered.
- Every message carries both. A client that blocks HTML, a screen reader, and
  a person who prefers plain text all get the version that was actually
  written rather than a stripped-out approximation.

## Why it looks like 2005

Email clients are not browsers. Gmail strips `<style>` blocks, Outlook renders
through Word, and flexbox is unavailable in most of them. So: tables, inline
styles, and no layout that needs more than one column. The alternative is a
design that looks right in the client it was tested in and broken in the rest.

## Images are decoration, never information

Most clients block remote images until the reader asks for them, so the logo
is allowed to be missing. Nothing here depends on it: the sender's name, the
signature and the link all survive with images turned off.
"""

import html
import re

from app.config import settings

#: The brand red, from the identity artwork. Deliberately not the platform's
#: own `--refused` red (#b42318), which means "void" or "blocked" inside the
#: interface - the two must not be confused, and email is the one place the
#: brand colour belongs.
BRAND = "#e6001c"

INK = "#14181f"
QUIET = "#5c6673"
RULE = "#e4e7ec"
PAPER = "#fbfbfc"

#: Where a reply goes, and where the business is. Recorded in
#: `docs/operations.md` too, with a note on changing them.
INSTAGRAM = "hba.wear"
INSTAGRAM_URL = "https://instagram.com/hba.wear"
STORE_URL = "https://hbawear.store"

_URL = re.compile(r"^https?://\S+$")


def _logo_url() -> str:
    """The mark, served from the platform's own domain.

    Empty when the platform does not know its own address - the same condition
    that leaves invitation links empty. An email with no logo is fine; one
    with a broken image is not.
    """
    base = settings.public_base_url.strip().rstrip("/")
    return f"{base}/hba-logo.png" if base else ""


def _button(url: str) -> str:
    """A link somebody can hit with a thumb.

    Padding rather than a fixed height, and a background on the anchor itself
    rather than the cell: Outlook ignores the cell's background often enough
    that the text would sit unreadably on white.
    """
    safe = html.escape(url, quote=True)
    return (
        '<table role="presentation" cellpadding="0" cellspacing="0" '
        'style="margin:24px 0;"><tr><td>'
        f'<a href="{safe}" style="display:inline-block;padding:12px 22px;'
        f"background:{BRAND};color:#ffffff;text-decoration:none;"
        'border-radius:3px;font-weight:600;font-size:15px;">Open it</a>'
        "</td></tr></table>"
        # The address in full underneath, because a button cannot be copied,
        # forwarded to a laptop, or read out over the phone - and somebody
        # whose client refuses to render the button still needs the link.
        f'<p style="margin:0 0 16px;font-size:12px;color:{QUIET};'
        f'word-break:break-all;">Or copy this: {safe}</p>'
    )


def _paragraphs(body: str) -> str:
    """The plain-text body as HTML blocks, with links made into buttons."""
    out = []
    for block in body.strip().split("\n\n"):
        block = block.strip()
        if not block:
            continue
        # **Matched per line, not per block.** The templates write the address
        # as the last line of the sentence introducing it - "expires in two
        # hours:" and then the link underneath - so matching whole blocks
        # found nothing, and every email would have shipped without a button.
        run: list[str] = []

        def flush() -> None:
            if not run:
                return
            text = "<br>".join(html.escape(line) for line in run)
            out.append(
                f'<p style="margin:0 0 16px;font-size:15px;line-height:1.6;'
                f'color:{INK};">{text}</p>'
            )
            run.clear()

        for line in block.split("\n"):
            if _URL.match(line.strip()):
                flush()
                out.append(_button(line.strip()))
            else:
                run.append(line)
        flush()
    return "".join(out)


def wrap(body: str) -> str:
    """One plain-text body, wrapped in the brand.

    The signature is added here rather than by each template, so it cannot go
    missing from one of them - which is exactly what happened to the sign-off
    before this existed.
    """
    # The templates end with their own sign-off, written for plain text. The
    # HTML has a signature block of its own, so the text one is lifted off
    # rather than printed twice.
    body = body.replace("\n\nHBA Aesthetics", "").rstrip()

    logo = _logo_url()
    mark = (
        f'<img src="{html.escape(logo, quote=True)}" width="140" alt="HBA" '
        'style="display:block;border:0;height:auto;">'
        if logo
        else f'<span style="font-size:20px;font-weight:700;color:{BRAND};'
        'letter-spacing:0.04em;">HBA</span>'
    )

    return f"""<!doctype html>
<html lang="en"><body style="margin:0;padding:0;background:{PAPER};">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0"
       style="background:{PAPER};padding:32px 16px;">
  <tr><td align="center">
    <table role="presentation" width="100%" cellpadding="0" cellspacing="0"
           style="max-width:560px;background:#ffffff;border:1px solid {RULE};
                  border-radius:4px;">
      <tr><td style="padding:28px 28px 8px;">{mark}</td></tr>
      <tr><td style="padding:8px 28px 24px;font-family:-apple-system,
                     BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,
                     sans-serif;">
        {_paragraphs(body)}
      </td></tr>
      <tr><td style="padding:20px 28px 28px;border-top:1px solid {RULE};
                     font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',
                     Roboto,Helvetica,Arial,sans-serif;font-size:13px;
                     line-height:1.6;color:{QUIET};">
        <p style="margin:0 0 4px;color:{INK};font-weight:600;">The HBA Team</p>
        <p style="margin:0;">
          <a href="{STORE_URL}" style="color:{QUIET};">hbawear.store</a>
          &nbsp;·&nbsp;
          <a href="{INSTAGRAM_URL}" style="color:{QUIET};">@{INSTAGRAM}</a>
        </p>
      </td></tr>
    </table>
  </td></tr>
</table>
</body></html>"""
