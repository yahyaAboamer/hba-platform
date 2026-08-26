"""Payment proof: stripped, compressed, capped, and shown only to its owner.

§14, and **ADR 0017 is a decision to re-read before touching any of this.**

The screenshot is shown to the affiliate because visible proof removes an entire
category of *"did you send it?"* messages — the business asked for it. An
external review noted that a transfer screenshot may expose HBA's sender name,
account details, transaction identifiers or balance to about twenty external
people. **The business accepted that knowingly.**

The mitigations below are not optional extras that came with the feature. They
are the conditions under which the risk was accepted, and dropping one because
it is inconvenient re-opens a decision somebody made deliberately:

**EXIF is stripped.** A screenshot carries device and, on a phone, location. The
image is re-encoded rather than filtered, so nothing survives by being in a
metadata block nobody thought to remove.

**Re-encoding also answers "is this actually an image?"** A file that will not
decode is refused, so an executable renamed to `.jpg` never reaches storage.
That is a security property, not a formatting one.

**It is compressed and capped**, because §14's storage budget assumes ~200 KB a
screenshot and an uncapped upload is an uncapped bill.

**It is served per request**, checked against the session — never by an
unguessable URL. A URL that is its own permission leaks the moment somebody
forwards a message.

Storage is Postgres, in this table, for the reasons in ADR 0026.
"""

import hashlib
import io

from PIL import Image, UnidentifiedImageError
from sqlalchemy.orm import Session

from app.models.payments import ProofFile

#: §14's budget is ~200 KB a screenshot. Five megabytes is generous for a phone
#: screenshot and mean enough that nobody uploads a video by accident.
MAX_UPLOAD_BYTES = 5 * 1024 * 1024

#: Long enough that a transfer reference is readable, small enough to stay
#: inside the storage budget. Phone screenshots are commonly ~1200 wide.
MAX_DIMENSION = 1600

#: Quality chosen so a screenshot of text stays legible. Below about 70 the
#: digits of an account number start to smear, which defeats the point.
JPEG_QUALITY = 80


class ProofRejected(ValueError):
    """The upload was refused, with a reason a person can act on."""


def sanitise(raw: bytes) -> tuple[bytes, str]:
    """Strip, shrink, re-encode. Returns ``(bytes, content type)``.

    **Re-encoded, never filtered.** Removing known metadata blocks leaves the
    ones nobody thought of; decoding to pixels and writing a fresh file leaves
    nothing to survive. It is also what makes a non-image impossible to store.
    """
    if not raw:
        raise ProofRejected("The file is empty")
    if len(raw) > MAX_UPLOAD_BYTES:
        raise ProofRejected(
            f"That file is {len(raw) // 1024}KB. The limit is "
            f"{MAX_UPLOAD_BYTES // 1024}KB - a screenshot should be well under it."
        )

    try:
        image = Image.open(io.BytesIO(raw))
        image.load()
    except (UnidentifiedImageError, OSError) as exc:
        raise ProofRejected(
            "That file is not an image the platform can read. A screenshot "
            "from a phone or a browser will work."
        ) from exc

    # Flatten transparency onto white rather than losing it to JPEG, which has
    # no alpha channel - a PNG screenshot would otherwise get a black
    # background wherever it was transparent.
    if image.mode in ("RGBA", "LA", "P"):
        image = image.convert("RGBA")
        flattened = Image.new("RGB", image.size, (255, 255, 255))
        flattened.paste(image, mask=image.split()[-1])
        image = flattened
    elif image.mode != "RGB":
        image = image.convert("RGB")

    image.thumbnail((MAX_DIMENSION, MAX_DIMENSION))

    out = io.BytesIO()
    # No exif= argument, so none is written. The decode above already discarded
    # what came in.
    image.save(out, format="JPEG", quality=JPEG_QUALITY, optimize=True)
    return out.getvalue(), "image/jpeg"


def store_proof(
    db: Session,
    affiliate,
    raw: bytes,
    *,
    actor_id: int | None = None,
) -> ProofFile:
    """Sanitise and keep one screenshot. Returns the existing row if identical.

    Keyed by content hash, so re-uploading the same screenshot - which happens
    when somebody is unsure whether the first attempt worked - stores it once.
    """
    cleaned, content_type = sanitise(raw)
    digest = hashlib.sha256(cleaned).hexdigest()

    existing = db.get(ProofFile, digest)
    if existing is not None:
        return existing

    stored = ProofFile(
        id=digest,
        affiliate_id=affiliate.id,
        content=cleaned,
        content_type=content_type,
        size_bytes=len(cleaned),
        uploaded_by=actor_id,
    )
    db.add(stored)
    db.flush()
    return stored


def readable_by(db: Session, file_id: str, *, affiliate_id: int) -> ProofFile | None:
    """The file, but only if it belongs to this affiliate.

    §14: *proof is served only to the affiliate it belongs to*. Checked here so
    the rule has one home rather than being remembered at each call site - and
    so a maintainer route and an affiliate route cannot drift apart on it.
    """
    stored = db.get(ProofFile, file_id)
    if stored is None or stored.affiliate_id != affiliate_id:
        return None
    return stored


def total_stored_bytes(db: Session) -> int:
    """How much proof is being kept.

    ADR 0026 puts the trigger for revisiting storage at 200 MB, which is only a
    trigger if somebody can see the number.
    """
    from sqlalchemy import func, select

    return (
        db.scalar(select(func.coalesce(func.sum(ProofFile.size_bytes), 0))) or 0
    )
