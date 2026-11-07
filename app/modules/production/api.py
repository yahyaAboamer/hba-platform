"""Production's addresses (ADR 0069, ADR 0076).

What the old ChatGPT server answered, now under `/api/production/…` and
behind the platform's own sign-in: everyone here is signed in to HBA and
holds Production (`production.view`). Answers are the old shapes, with
`{"error": …}` for a refusal, because that is what the screens read.

| Address | What |
|---|---|
| `GET  /session` | Who is signed in, in the old shape |
| `POST /session` | Refused: signing in is HBA's now |
| `GET  /state` | Everything the screens draw from |
| `GET  /fixtures` | The fixed content, loaded before the first draw |
| `POST /actions` | Every change |
| `GET/POST /documents` | Document list and upload |
| `GET/POST /order-photos`, `GET /order-photos/{id}` | Order photos |
| `GET/POST /sample-photos`, `GET /sample-photos/{id}` | Sample photos |
"""

import json
import logging

from fastapi import APIRouter, Depends, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app.core.permissions import OWNER_ROLE, Permission, permissions_of_roles
from app.db import get_session
from app.modules.inbox.public import StorageError, file_bucket
from app.modules.production.services import actions, files
from app.modules.production.services.state import dumps, fixtures, shared_state
from app.shared.api.deps import current_user, roles_of
from app.shared.models.identity import UserAccount

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/production", tags=["production"])

NO_STORE = {"Cache-Control": "no-store"}


def _json(payload: dict, status: int = 200) -> Response:
    return Response(dumps(payload), status_code=status, media_type="application/json", headers=NO_STORE)


class Person:
    """The signed-in person, with what they may do in Production."""

    def __init__(self, user: UserAccount, roles: frozenset[str]) -> None:
        self.user = user
        self.roles = roles
        self.held = permissions_of_roles(roles)

    @property
    def name(self) -> str:
        return (self.user.display_name or "").strip() or self.user.email

    def view(self) -> dict:
        """The old `TeamUser`: its four roles decide what the screens offer.

        The manager handles suppliers, which only the old owner account
        could; the screens are told "admin" with the manager's own label, and
        the server still refuses what only the owner may do. Staff also
        record QC checks (ADR 0077): they stay "production" and the screens
        are told `canCheckQc`, so they get the checklist without the
        manager's supplier and settings controls.
        """
        user: dict = {"username": self.user.email, "name": self.name}
        if OWNER_ROLE in self.roles:
            user["role"] = "admin"
        elif Permission.PRODUCTION_SUPPLIERS in self.held:
            user["role"] = "admin"
            user["roleLabel"] = "Production manager"
        elif Permission.PRODUCTION_EDIT in self.held:
            user["role"] = "production"
            user["roleLabel"] = "Production staff"
            if Permission.PRODUCTION_QC in self.held:
                user["canCheckQc"] = True
        elif Permission.PRODUCTION_QC in self.held:
            user["role"] = "qc"
        else:
            user["role"] = "viewer"
        return user


def production_person(user: UserAccount = Depends(current_user), db: Session = Depends(get_session)) -> Person:
    person = Person(user, roles_of(db, user))
    if Permission.PRODUCTION_VIEW not in person.held:
        raise ProductionRefused(403, "Your account does not have access to Production")
    return person


class ProductionRefused(Exception):
    def __init__(self, status: int, message: str) -> None:
        self.status, self.message = status, message


def refused_handler(_request: Request, exc: ProductionRefused) -> Response:
    """Registered in `app.main`: a refusal in the old `{"error": …}` shape."""
    return _json({"error": exc.message}, exc.status)


@router.get("/session")
def session(person: Person = Depends(production_person)) -> Response:
    return _json({"user": person.view()})


@router.post("/session")
def session_post(_person: Person = Depends(production_person)) -> Response:
    return _json({"error": "Production uses your HBA account. Sign in and out from HBA."}, 400)


@router.get("/state")
def state(person: Person = Depends(production_person), db: Session = Depends(get_session)) -> Response:
    return _json(shared_state(db, person.view()))


@router.get("/fixtures")
def fixed_content(_person: Person = Depends(production_person), db: Session = Depends(get_session)) -> Response:
    return _json(fixtures(db))


@router.post("/actions")
async def perform_action(
    request: Request, person: Person = Depends(production_person), db: Session = Depends(get_session)
) -> Response:
    try:
        body = json.loads(await request.body())
    except (ValueError, UnicodeDecodeError):
        return _json({"error": "Invalid JSON payload"}, 400)

    def act() -> Response:
        status, answer = actions.perform(
            db, body, actor_name=person.name, actor_id=person.user.id, actor_email=person.user.email,
            held=person.held,
        )
        if status < 400:
            db.commit()
        else:
            db.rollback()
        return _json(answer, status)

    # Only reading the body waits on the network; the database work runs off
    # the event loop, as a plain `def` route's would.
    return await run_in_threadpool(act)


# ── Documents ─────────────────────────────────────────────────────────────────


def _too_large(request: Request) -> bool:
    """Refused before reading: too large, or of no stated size. A body sent
    without `Content-Length` would otherwise be read whole before its size
    could be checked."""
    length = request.headers.get("content-length")
    if length is None or not length.isdigit():
        return True
    return int(length) > files.MAX_BYTES + 1024 * 1024


@router.get("/documents")
def documents(person: Person = Depends(production_person), db: Session = Depends(get_session)) -> Response:
    # A confidential document is listed only to those who may upload one.
    trusted = bool({Permission.PRODUCTION_EDIT, Permission.PRODUCTION_QC} & person.held)
    return _json({"documents": files.list_documents(db, include_confidential=trusted)})


@router.post("/documents")
async def upload_document(
    request: Request, person: Person = Depends(production_person), db: Session = Depends(get_session)
) -> Response:
    if not ({Permission.PRODUCTION_EDIT, Permission.PRODUCTION_QC} & person.held):
        return _json({"error": "Your account does not have permission to upload"}, 403)
    if _too_large(request):
        return _json({"error": "Files must be 20 MB or smaller"}, 413)
    form = await request.form()
    upload = form.get("file")
    content = await upload.read() if hasattr(upload, "read") else b""
    if not content:
        return _json({"error": "A non-empty file is required"}, 400)
    if len(content) > files.MAX_BYTES:
        return _json({"error": "Files must be 20 MB or smaller"}, 413)
    def store() -> Response:
        try:
            answer = files.save_document(
                db,
                filename=getattr(upload, "filename", None) or "file",
                content=content,
                content_type=getattr(upload, "content_type", None) or "",
                module=str(form.get("module") or "Documents"),
                record_id=str(form.get("recordId") or "general"),
                document_type=str(form.get("documentType") or "Other"),
                confidential=form.get("confidential") == "true",
                actor_id=person.user.id,
                actor_email=person.user.email,
            )
        except StorageError:
            db.rollback()
            logger.exception("Production document could not be stored")
            return _json({"error": "Could not save the file. Please try again."}, 500)
        db.commit()
        return _json(answer, 201)

    return await run_in_threadpool(store)


# ── Photos ────────────────────────────────────────────────────────────────────


def _list(kind: str, request: Request, db: Session) -> Response:
    reference = request.query_params.get(kind) or ""
    record = files.find_record(db, kind, reference)
    if record is None:
        return _json({"error": "Production order not found" if kind == "order" else "Sample not found"}, 404)
    return _json({"photos": files.list_photos(db, kind, record.id)})


async def _upload(kind: str, request: Request, person: Person, db: Session) -> Response:
    if Permission.PRODUCTION_EDIT not in person.held:
        return _json({"error": "Sign in with an owner or production account to upload photos"}, 403)
    if _too_large(request):
        return _json({"error": "Photos must be 20 MB or smaller"}, 413)
    form = await request.form()
    upload = form.get("file")
    content = await upload.read() if hasattr(upload, "read") else b""
    return await run_in_threadpool(_store_photo, kind, form, upload, content, person, db)


def _store_photo(kind: str, form, upload, content: bytes, person: Person, db: Session) -> Response:
    record = files.find_record(db, kind, str(form.get(kind) or ""))
    if record is None:
        return _json({"error": "Production order not found" if kind == "order" else "Sample not found"}, 404)
    if not content:
        return _json({"error": "Choose a photo to upload"}, 400)
    if len(content) > files.MAX_BYTES:
        return _json({"error": "Photos must be 20 MB or smaller"}, 413)
    mime = files.image_type(content[:16])
    if mime is None:
        return _json({"error": "Use a JPG, PNG, WebP or GIF photo"}, 400)
    try:
        photo = files.save_photo(
            db, kind, record, filename=getattr(upload, "filename", None) or "", content=content, mime=mime,
            actor_name=person.name, actor_id=person.user.id, actor_email=person.user.email,
        )
        db.commit()
    except Exception:
        db.rollback()
        logger.exception("Production photo could not be saved")
        return _json({"error": "Could not save the photo. Please try again."}, 500)
    return _json({"photo": photo}, 201)


def _download(kind: str, photo_id: str, db: Session) -> Response:
    photo = files.photo_for_download(db, kind, photo_id)
    if photo is None:
        return _json({"error": "Photo not found"}, 404)
    try:
        content = file_bucket().get(photo.storage_key)
    except StorageError:
        return _json({"error": "Photo not found"}, 404)
    return Response(
        content,
        media_type=photo.mime_type,
        headers={"Content-Disposition": "inline", "X-Content-Type-Options": "nosniff",
                 "Cache-Control": "private, max-age=300"},
    )


@router.get("/order-photos")
def order_photos(request: Request, _p: Person = Depends(production_person), db: Session = Depends(get_session)):
    return _list("order", request, db)


@router.post("/order-photos")
async def upload_order_photo(request: Request, person: Person = Depends(production_person),
                             db: Session = Depends(get_session)):
    return await _upload("order", request, person, db)


@router.get("/order-photos/{photo_id}")
def order_photo(photo_id: str, _p: Person = Depends(production_person), db: Session = Depends(get_session)):
    return _download("order", photo_id, db)


@router.get("/sample-photos")
def sample_photos(request: Request, _p: Person = Depends(production_person), db: Session = Depends(get_session)):
    return _list("sample", request, db)


@router.post("/sample-photos")
async def upload_sample_photo(request: Request, person: Person = Depends(production_person),
                              db: Session = Depends(get_session)):
    return await _upload("sample", request, person, db)


@router.get("/sample-photos/{photo_id}")
def sample_photo(photo_id: str, _p: Person = Depends(production_person), db: Session = Depends(get_session)):
    return _download("sample", photo_id, db)

