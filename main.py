"""
Viavios - memoir / legacy book / chronicle / testament web app.
FastAPI + SQLAlchemy (SQLite by default, PostgreSQL via DATABASE_URL on AWS).
Vanilla frontend served from ./static. Passwords: PBKDF2 (stdlib). Sessions: server-side tokens in a cookie.
"""
import base64, hashlib, hmac, json, os, secrets, shutil, time
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI, Request, Depends, HTTPException, UploadFile, File, Form
from fastapi.responses import JSONResponse, FileResponse, Response
from fastapi.staticfiles import StaticFiles
from sqlalchemy import (create_engine, Column, Integer, String, Text, Boolean,
                        DateTime, ForeignKey, UniqueConstraint)
from sqlalchemy.orm import declarative_base, sessionmaker, Session

from emails import render_email, deliver as deliver_email

BASE_DIR = Path(__file__).parent
DATABASE_URL = os.environ.get("DATABASE_URL", "sqlite:///./remora.db")
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)
UPLOAD_DIR = Path(os.environ.get("UPLOAD_DIR", str(BASE_DIR / "uploads")))
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}
engine = create_engine(DATABASE_URL, connect_args=connect_args)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
Base = declarative_base()

PAID_PLANS = {"subscription_monthly", "subscription_yearly", "lifetime"}
FREE_BOOK_LIMIT = 1

# ---------- Tokens: the app's credits (the "price → token" note) ----------
# All token economics live here so they can be retuned in one place.
WELCOME_TOKENS = 50        # free grant when an account is created
TERMS_VERSION = "2026-11-14"  # clickwrap version recorded at acceptance
AI_SUGGEST_COST = 5        # tokens charged per AI suggestion
TOKEN_PACKS = [
    {"id": "tokens_100", "name": "100 tokens", "price": "$5", "tokens": 100,
     "features": ["100 writing tokens", "Good for 20 AI suggestions"]},
    {"id": "tokens_300", "name": "300 tokens", "price": "$12", "tokens": 300,
     "features": ["300 writing tokens", "Good for 60 AI suggestions", "Best value"]},
]
PLAN_TOKEN_GRANTS = {"subscription_monthly": 200, "subscription_yearly": 200, "lifetime": 2000}

# ---------- Models ----------
class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True)
    name = Column(String(120), nullable=False)
    email = Column(String(255), unique=True, nullable=False, index=True)
    password_hash = Column(String(255), nullable=True)  # None for Google/passkey-only accounts
    auth_provider = Column(String(40), default="password", nullable=False)  # password | google
    provider_sub = Column(String(255), nullable=True)
    plan = Column(String(40), default="free", nullable=False)
    token_balance = Column(Integer, default=WELCOME_TOKENS)
    terms_version = Column(String(40))
    terms_accepted_at = Column(DateTime)
    phone = Column(String(30))
    phone_verified = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)

class StripeEvent(Base):
    __tablename__ = "stripe_events"
    id = Column(Integer, primary_key=True)
    event_id = Column(String(255), unique=True, nullable=False, index=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class TokenLedger(Base):
    __tablename__ = "token_ledger"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    delta = Column(Integer, nullable=False)  # + grant/purchase, - spend
    reason = Column(String(40), default="")  # welcome | ai_suggest | token_pack | plan_grant
    created_at = Column(DateTime, default=datetime.utcnow)


class PasskeyCredential(Base):
    __tablename__ = "passkey_credentials"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    credential_id = Column(String(512), unique=True, nullable=False, index=True)  # base64url
    public_key = Column(Text, nullable=False)  # base64url of the COSE public key bytes
    sign_count = Column(Integer, default=0, nullable=False)
    transports = Column(String(255), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

class AuthChallenge(Base):
    __tablename__ = "auth_challenges"
    id = Column(Integer, primary_key=True)
    flow_id = Column(String(64), unique=True, nullable=False, index=True)
    purpose = Column(String(20), nullable=False)  # passkey_register | passkey_login | google
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    challenge = Column(String(512), nullable=False)  # base64url (webauthn) or oauth state token
    created_at = Column(DateTime, default=datetime.utcnow)

class EmailOutbox(Base):
    __tablename__ = "email_outbox"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    to_email = Column(String(255), nullable=False)
    kind = Column(String(40), nullable=False)
    subject = Column(String(300), nullable=False)
    body_text = Column(Text, nullable=False)
    body_html = Column(Text, nullable=False)
    status = Column(String(20), default="stored", nullable=False)  # sent | stored | failed
    error = Column(String(300), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

class SessionToken(Base):
    __tablename__ = "sessions"
    token = Column(String(128), primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

class Book(Base):
    __tablename__ = "books"
    id = Column(Integer, primary_key=True)
    owner_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    title = Column(String(255), nullable=False)
    type = Column(String(40), default="Memoir")  # Memoir | Legacy Book | Chronicle | Testament | Photo Story (free text, no validation list)
    description = Column(Text, default="")
    visibility = Column(String(20), default="private")  # private | family | public | testament
    family_emails = Column(Text, default="")  # comma-separated
    testament_recipients = Column(Text, default="")
    release_note = Column(Text, default="")
    publisher_optin = Column(Boolean, default=False)
    font = Column(String(20), default="serif")  # serif | sans | hand | large
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

class Chapter(Base):
    __tablename__ = "chapters"
    id = Column(Integer, primary_key=True)
    book_id = Column(Integer, ForeignKey("books.id"), nullable=False, index=True)
    title = Column(String(255), nullable=False)
    body = Column(Text, default="")
    visibility = Column(String(20), default="inherit")  # inherit | private | family | public | testament
    status = Column(String(20), default="published")  # draft | published
    sort_order = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

class Media(Base):
    __tablename__ = "media"
    id = Column(Integer, primary_key=True)
    book_id = Column(Integer, ForeignKey("books.id"), nullable=False, index=True)
    chapter_id = Column(Integer, ForeignKey("chapters.id"), nullable=True)
    kind = Column(String(20), default="photo")  # photo | audio | video | voiceover | youtube | voice_transcript
    filename = Column(String(255), default="")  # stored file name (photo/audio/video); empty for transcript/links
    url = Column(String(500), nullable=True)  # external link for youtube entries
    original_name = Column(String(255), default="")
    transcript = Column(Text, default="")  # for voice_transcript entries
    created_at = Column(DateTime, default=datetime.utcnow)

class TimelineEntry(Base):
    __tablename__ = "timeline_entries"
    id = Column(Integer, primary_key=True)
    book_id = Column(Integer, ForeignKey("books.id"), nullable=False, index=True)
    date_text = Column(String(120), default="")
    event_text = Column(Text, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

class Letter(Base):
    __tablename__ = "letters"
    id = Column(Integer, primary_key=True)
    book_id = Column(Integer, ForeignKey("books.id"), nullable=False, index=True)
    recipient_name = Column(String(255), nullable=False)
    body = Column(Text, default="")
    created_at = Column(DateTime, default=datetime.utcnow)

class Vote(Base):
    __tablename__ = "votes"
    __table_args__ = (UniqueConstraint("book_id", "user_id", name="uq_one_vote_per_user_book"),)
    id = Column(Integer, primary_key=True)
    book_id = Column(Integer, ForeignKey("books.id"), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

Base.metadata.create_all(bind=engine)


def _ensure_columns():
    """Tiny additive migration: create_all never adds columns to existing
    tables, so add this project's later columns when missing (SQLite + PG)."""
    wanted = {
        "chapters": [("status", "VARCHAR(20) DEFAULT 'published'"),
                     ("updated_at", "TIMESTAMP")],
        "books": [("font", "VARCHAR(20) DEFAULT 'serif'")],
        "media": [("url", "VARCHAR(500)")],
        "users": [("auth_provider", "VARCHAR(20) DEFAULT 'password'"),
                  ("provider_sub", "VARCHAR(255)"),
                  ("token_balance", "INTEGER DEFAULT 50"),
                  ("terms_version", "VARCHAR(40)"),
                  ("terms_accepted_at", "TIMESTAMP"),
                  ("phone", "VARCHAR(30)"),
                  ("phone_verified", "BOOLEAN DEFAULT FALSE")],
    }
    from sqlalchemy import inspect as sa_inspect, text as sa_text
    insp = sa_inspect(engine)
    tables = set(insp.get_table_names())
    with engine.begin() as conn:
        for table, cols in wanted.items():
            if table not in tables:
                continue
            existing = {c["name"] for c in insp.get_columns(table)}
            for name, ddl in cols:
                if name not in existing:
                    conn.execute(sa_text(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}"))


_ensure_columns()

# ---------- Helpers ----------
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 200_000)
    return f"pbkdf2${salt}${dk.hex()}"

def verify_password(password: str, stored: str) -> bool:
    try:
        _, salt, hexdk = stored.split("$")
        dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 200_000)
        return hmac.compare_digest(dk.hex(), hexdk)
    except Exception:
        return False

def current_user(request: Request, db: Session):
    token = request.cookies.get("remora_session")
    if not token:
        return None
    s = db.query(SessionToken).filter_by(token=token).first()
    if not s:
        return None
    return db.query(User).filter_by(id=s.user_id).first()

def require_user(request: Request, db: Session = Depends(get_db)):
    u = current_user(request, db)
    if not u:
        raise HTTPException(401, "Sign in required")
    return u

def user_json(u: User):
    return {"id": u.id, "name": u.name,
            "email": None if (u.email or "").endswith("@phone.viavios.local") else u.email,
            "plan": u.plan, "is_paid": u.plan in PAID_PLANS,
            "tokens": u.token_balance if u.token_balance is not None else WELCOME_TOKENS,
            "terms_accepted": bool(getattr(u, "terms_accepted_at", None)),
            "terms_version": getattr(u, "terms_version", None),
            "phone": getattr(u, "phone", None),
            "phone_verified": bool(getattr(u, "phone_verified", False))}


def move_tokens(db: Session, user: User, delta: int, reason: str):
    """Adjust a user's token balance and record it. Caller commits."""
    bal = user.token_balance if user.token_balance is not None else WELCOME_TOKENS
    user.token_balance = bal + delta
    db.add(TokenLedger(user_id=user.id, delta=delta, reason=reason))

def queue_email(db: Session, user, kind: str, to_email: str = None, name: str = None, **ctx):
    """Render, record, and deliver one transactional email. Never raises:
    an email problem must not break the action that triggered it."""
    try:
        subject, text, html = render_email(kind, {"name": name or (user.name if user else ""), **ctx})
        row = EmailOutbox(user_id=(user.id if user else None),
                          to_email=to_email or (user.email if user else ""),
                          kind=kind, subject=subject, body_text=text, body_html=html,
                          status="stored")
        db.add(row); db.commit(); db.refresh(row)
        status, error = deliver_email(row.to_email, subject, text, html)
        row.status, row.error = status, error
        db.commit()
        return row
    except Exception:
        try: db.rollback()
        except Exception: pass
        return None

def vote_count(db: Session, book_id: int) -> int:
    return db.query(Vote).filter_by(book_id=book_id).count()

def book_json(db: Session, b: Book, include_owner=False):
    data = {"id": b.id, "owner_id": b.owner_id, "title": b.title, "type": b.type,
            "description": b.description or "", "visibility": b.visibility,
            "family_emails": b.family_emails or "", "testament_recipients": b.testament_recipients or "",
            "release_note": b.release_note or "", "publisher_optin": bool(b.publisher_optin),
            "font": getattr(b, "font", None) or "serif",
            "votes": vote_count(db, b.id),
            "created_at": b.created_at.isoformat() if b.created_at else None}
    if include_owner:
        owner = db.query(User).filter_by(id=b.owner_id).first()
        data["author_name"] = owner.name if owner else ""
    return data

def get_own_book(db: Session, book_id: int, user: User) -> Book:
    b = db.query(Book).filter_by(id=book_id, owner_id=user.id).first()
    if not b:
        raise HTTPException(404, "Book not found")
    return b

def can_read_book(db: Session, b: Book, user) -> bool:
    if user and b.owner_id == user.id:
        return True
    if b.visibility == "public":
        return True
    if b.visibility == "family" and user:
        emails = [e.strip().lower() for e in (b.family_emails or "").split(",") if e.strip()]
        return user.email.lower() in emails
    return False  # private and testament are owner-only until a future verified release process

app = FastAPI(title="Viavios")

# ---------- Auth ----------
@app.post("/api/signup")
async def signup(request: Request, db: Session = Depends(get_db)):
    data = await request.json()
    name = (data.get("name") or "").strip()
    email = (data.get("email") or "").strip().lower()
    password = data.get("password") or ""
    if not name or not email or len(password) < 6:
        raise HTTPException(400, "Name, email and a password of 6+ characters are required")
    if data.get("accept_terms") is not True:
        raise HTTPException(400, "Please agree to the Terms of Use and Privacy Policy to create your account")
    if db.query(User).filter_by(email=email).first():
        raise HTTPException(400, "An account with that email already exists")
    u = User(name=name, email=email, password_hash=hash_password(password), plan="free",
             terms_version=TERMS_VERSION, terms_accepted_at=datetime.utcnow())
    db.add(u); db.commit(); db.refresh(u)
    db.add(TokenLedger(user_id=u.id, delta=WELCOME_TOKENS, reason="welcome")); db.commit()
    queue_email(db, u, "welcome")
    queue_email(db, u, "next_steps")
    return set_session(db, u)

@app.post("/api/signin")
async def signin(request: Request, db: Session = Depends(get_db)):
    data = await request.json()
    email = (data.get("email") or "").strip().lower()
    u = db.query(User).filter_by(email=email).first()
    if not u:
        raise HTTPException(401, "Wrong email or password")
    if not u.password_hash:
        raise HTTPException(401, "This account was created with Google or a passkey — please use that to sign in")
    if not verify_password(data.get("password") or "", u.password_hash):
        raise HTTPException(401, "Wrong email or password")
    return set_session(db, u)

def set_session(db: Session, u: User):
    token = secrets.token_urlsafe(48)
    db.add(SessionToken(token=token, user_id=u.id)); db.commit()
    resp = JSONResponse(user_json(u))
    resp.set_cookie("remora_session", token, httponly=True, samesite="lax", max_age=60*60*24*30)
    return resp

@app.post("/api/signout")
def signout(request: Request, db: Session = Depends(get_db)):
    token = request.cookies.get("remora_session")
    if token:
        db.query(SessionToken).filter_by(token=token).delete(); db.commit()
    resp = JSONResponse({"ok": True})
    resp.delete_cookie("remora_session")
    return resp

@app.get("/api/me")
def me(request: Request, db: Session = Depends(get_db)):
    u = current_user(request, db)
    return user_json(u) if u else JSONResponse({"user": None}, status_code=200) if False else (user_json(u) if u else {"id": None})

@app.get("/api/me/emails")
def my_emails(db: Session = Depends(get_db), user: User = Depends(require_user)):
    rows = db.query(EmailOutbox).filter_by(user_id=user.id).order_by(EmailOutbox.created_at.desc(), EmailOutbox.id.desc()).limit(50).all()
    return [{"id": r.id, "kind": r.kind, "subject": r.subject, "status": r.status,
             "created_at": r.created_at.isoformat() if r.created_at else None} for r in rows]

@app.patch("/api/me")
async def update_me(request: Request, db: Session = Depends(get_db), user: User = Depends(require_user)):
    data = await request.json()
    changes = []
    new_name = (data.get("name") or "").strip()
    if new_name and new_name != user.name:
        user.name = new_name
        changes.append("your display name was changed")
    new_password = data.get("new_password") or ""
    if new_password:
        if not verify_password(data.get("current_password") or "", user.password_hash):
            raise HTTPException(400, "Current password is wrong")
        if len(new_password) < 6:
            raise HTTPException(400, "New password needs 6+ characters")
        user.password_hash = hash_password(new_password)
        changes.append("your password was changed")
    if not changes:
        raise HTTPException(400, "Nothing to change")
    db.commit(); db.refresh(user)
    queue_email(db, user, "account_updated", changes=" and ".join(changes))
    return user_json(user)

@app.delete("/api/me")
async def delete_me(request: Request, db: Session = Depends(get_db), user: User = Depends(require_user)):
    data = await request.json()
    if not verify_password(data.get("password") or "", user.password_hash):
        raise HTTPException(400, "Password confirmation is wrong")
    name, email = user.name, user.email
    book_ids = [b.id for b in db.query(Book).filter_by(owner_id=user.id).all()]
    if book_ids:
        for model in (Chapter, Media, TimelineEntry, Letter, Vote):
            db.query(model).filter(model.book_id.in_(book_ids)).delete(synchronize_session=False)
    db.query(Book).filter_by(owner_id=user.id).delete(synchronize_session=False)
    db.query(Vote).filter_by(user_id=user.id).delete(synchronize_session=False)
    db.query(SessionToken).filter_by(user_id=user.id).delete(synchronize_session=False)
    db.query(PasskeyCredential).filter_by(user_id=user.id).delete(synchronize_session=False)
    db.query(TokenLedger).filter_by(user_id=user.id).delete(synchronize_session=False)
    db.query(AuthChallenge).filter_by(user_id=user.id).delete(synchronize_session=False)
    db.query(EmailOutbox).filter_by(user_id=user.id).update({"user_id": None}, synchronize_session=False)
    db.delete(user); db.commit()
    queue_email(db, None, "account_cancelled", to_email=email, name=name)
    resp = JSONResponse({"ok": True})
    resp.delete_cookie("remora_session")
    return resp

@app.post("/api/app-updates")
async def app_update(request: Request, db: Session = Depends(get_db)):
    key = os.environ.get("APP_UPDATE_KEY")
    if not key or request.headers.get("x-admin-key") != key:
        raise HTTPException(403, "Not authorized")
    data = await request.json()
    subject = (data.get("subject") or "").strip()
    message = (data.get("message") or "").strip()
    if not subject or not message:
        raise HTTPException(400, "Subject and message are required")
    users = db.query(User).all()
    for u in users:
        queue_email(db, u, "app_update", subject=subject, message=message)
    return {"ok": True, "recipients": len(users)}

# ---------- Modern sign-in: Google, passkeys, Apple ----------
import base64, json as _json, urllib.parse, urllib.request as _urlreq
from fastapi.responses import RedirectResponse

def _b64u_dec(s: str) -> bytes:
    return base64.urlsafe_b64decode((s or "") + "=" * (-len(s or "") % 4))

def _app_base(request: Request) -> str:
    base = os.environ.get("APP_BASE_URL", "").rstrip("/")
    return base if base else str(request.base_url).rstrip("/")

def _rp_id(request: Request) -> str:
    return os.environ.get("WEBAUTHN_RP_ID") or (request.url.hostname or "localhost")

def _start_session(db: Session, u: User, resp):
    token = secrets.token_urlsafe(48)
    db.add(SessionToken(token=token, user_id=u.id)); db.commit()
    resp.set_cookie("remora_session", token, httponly=True, samesite="lax", max_age=60*60*24*30)
    return resp

def _store_flow(db: Session, purpose: str, challenge_value: str, user_id=None) -> str:
    flow = secrets.token_urlsafe(24)
    db.add(AuthChallenge(flow_id=flow, purpose=purpose, user_id=user_id, challenge=challenge_value)); db.commit()
    return flow

def _take_flow(db: Session, flow_id: str, purpose: str):
    if not flow_id:
        return None
    row = db.query(AuthChallenge).filter_by(flow_id=flow_id, purpose=purpose).first()
    if row:
        db.delete(row); db.commit()
    return row

# ----- Google -----
@app.get("/api/auth/providers")
def auth_providers():
    return {"google": bool(os.environ.get("GOOGLE_CLIENT_ID")),
            "apple": bool(os.environ.get("APPLE_CLIENT_ID")),
            "passkeys": True, "phone": True}

@app.get("/auth/google/start")
def google_start(request: Request, db: Session = Depends(get_db)):
    cid = os.environ.get("GOOGLE_CLIENT_ID")
    if not cid:
        raise HTTPException(501, "Google sign-in is not switched on yet")
    state = secrets.token_urlsafe(24)
    _store_flow(db, "google", state)
    params = {"client_id": cid, "redirect_uri": _app_base(request) + "/auth/google/callback",
              "response_type": "code", "scope": "openid email profile", "state": state,
              "access_type": "online", "prompt": "select_account"}
    return RedirectResponse("https://accounts.google.com/o/oauth2/v2/auth?" + urllib.parse.urlencode(params), status_code=302)

@app.get("/auth/google/callback")
def google_callback(request: Request, code: str = "", state: str = "", db: Session = Depends(get_db)):
    row = db.query(AuthChallenge).filter_by(challenge=state, purpose="google").first() if state else None
    if not row or not code:
        return RedirectResponse("/?auth_error=google", status_code=302)
    db.delete(row); db.commit()
    try:
        form = urllib.parse.urlencode({"code": code, "client_id": os.environ["GOOGLE_CLIENT_ID"],
                                       "client_secret": os.environ["GOOGLE_CLIENT_SECRET"],
                                       "redirect_uri": _app_base(request) + "/auth/google/callback",
                                       "grant_type": "authorization_code"}).encode()
        req = _urlreq.Request("https://oauth2.googleapis.com/token", data=form,
                              headers={"Content-Type": "application/x-www-form-urlencoded"})
        tok = _json.loads(_urlreq.urlopen(req, timeout=20).read())
        req2 = _urlreq.Request("https://openidconnect.googleapis.com/v1/userinfo",
                               headers={"Authorization": "Bearer " + tok["access_token"]})
        info = _json.loads(_urlreq.urlopen(req2, timeout=20).read())
    except Exception:
        return RedirectResponse("/?auth_error=google", status_code=302)
    email = (info.get("email") or "").strip().lower()
    if not email or not info.get("email_verified"):
        return RedirectResponse("/?auth_error=google", status_code=302)
    u = db.query(User).filter_by(email=email).first()
    if not u:
        u = User(name=info.get("name") or email.split("@")[0], email=email, password_hash=None,
                 auth_provider="google", provider_sub=info.get("sub"), plan="free")
        db.add(u); db.commit(); db.refresh(u)
        db.add(TokenLedger(user_id=u.id, delta=WELCOME_TOKENS, reason="welcome")); db.commit()
        queue_email(db, u, "welcome")
        queue_email(db, u, "next_steps")
    elif not u.provider_sub:
        u.provider_sub = info.get("sub"); db.commit()
    return _start_session(db, u, RedirectResponse("/", status_code=302))

# ----- Apple (activates when the Apple Developer credentials are set) -----
@app.get("/auth/apple/start")
def apple_start(request: Request, db: Session = Depends(get_db)):
    cid = os.environ.get("APPLE_CLIENT_ID")
    if not cid:
        raise HTTPException(501, "Apple sign-in is not switched on yet — it needs the Apple Developer setup first")
    state = secrets.token_urlsafe(24)
    _store_flow(db, "apple", state)
    params = {"client_id": cid, "redirect_uri": _app_base(request) + "/auth/apple/callback",
              "response_type": "code", "scope": "name email", "response_mode": "form_post", "state": state}
    return RedirectResponse("https://appleid.apple.com/auth/authorize?" + urllib.parse.urlencode(params), status_code=302)


def _b64u(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _b64u_decode(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def _apple_client_secret() -> str:
    """Apple requires a short-lived ES256 JWT as the OAuth client secret,
    signed with the .p8 key from the Apple Developer account."""
    from cryptography.hazmat.primitives import serialization, hashes
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature
    pem = os.environ["APPLE_PRIVATE_KEY"].replace("\\n", "\n")
    key = serialization.load_pem_private_key(pem.encode(), password=None)
    now = int(time.time())
    header = {"alg": "ES256", "kid": os.environ["APPLE_KEY_ID"], "typ": "JWT"}
    payload = {"iss": os.environ["APPLE_TEAM_ID"], "iat": now, "exp": now + 1200,
               "aud": "https://appleid.apple.com", "sub": os.environ["APPLE_CLIENT_ID"]}
    signing_input = (_b64u(json.dumps(header, separators=(",", ":")).encode()) + "." +
                     _b64u(json.dumps(payload, separators=(",", ":")).encode())).encode()
    der = key.sign(signing_input, ec.ECDSA(hashes.SHA256()))
    r, s = decode_dss_signature(der)
    raw = r.to_bytes(32, "big") + s.to_bytes(32, "big")
    return signing_input.decode() + "." + _b64u(raw)


def _verify_apple_id_token(id_token: str, client_id: str) -> dict:
    """Verify an Apple id_token against Apple's published keys (RS256)."""
    import urllib.request as _u
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import padding
    from cryptography.hazmat.primitives.asymmetric.rsa import RSAPublicNumbers
    head_b, payload_b, sig_b = id_token.split(".")
    header = json.loads(_b64u_decode(head_b))
    jwks_url = os.environ.get("APPLE_JWKS_URL", "https://appleid.apple.com/auth/keys")
    with _u.urlopen(jwks_url, timeout=15) as resp:
        jwks = json.loads(resp.read().decode())
    jwk = next((k for k in jwks.get("keys", []) if k.get("kid") == header.get("kid")), None)
    if not jwk:
        raise ValueError("unknown signing key")
    n = int.from_bytes(_b64u_decode(jwk["n"]), "big")
    e = int.from_bytes(_b64u_decode(jwk["e"]), "big")
    pub = RSAPublicNumbers(e, n).public_key()
    pub.verify(_b64u_decode(sig_b), (head_b + "." + payload_b).encode(),
               padding.PKCS1v15(), hashes.SHA256())
    claims = json.loads(_b64u_decode(payload_b))
    if claims.get("iss") != "https://appleid.apple.com" or claims.get("aud") != client_id:
        raise ValueError("issuer/audience mismatch")
    if int(claims.get("exp", 0)) < int(time.time()):
        raise ValueError("token expired")
    return claims


@app.post("/auth/apple/callback")
async def apple_callback(request: Request, db: Session = Depends(get_db)):
    form = await request.form()
    code, state = form.get("code") or "", form.get("state") or ""
    row = db.query(AuthChallenge).filter_by(challenge=state, purpose="apple").first() if state else None
    if not row or not code or form.get("error"):
        return RedirectResponse("/?auth_error=apple", status_code=302)
    db.delete(row); db.commit()
    import urllib.request as _u
    try:
        token_url = os.environ.get("APPLE_TOKEN_URL", "https://appleid.apple.com/auth/token")
        fields = urllib.parse.urlencode({
            "client_id": os.environ["APPLE_CLIENT_ID"], "client_secret": _apple_client_secret(),
            "code": code, "grant_type": "authorization_code",
            "redirect_uri": _app_base(request) + "/auth/apple/callback"})
        req = _u.Request(token_url, data=fields.encode(),
                         headers={"Content-Type": "application/x-www-form-urlencoded"})
        with _u.urlopen(req, timeout=20) as r:
            tokens = json.loads(r.read().decode())
        claims = _verify_apple_id_token(tokens["id_token"], os.environ["APPLE_CLIENT_ID"])
    except Exception:
        return RedirectResponse("/?auth_error=apple", status_code=302)
    sub = claims.get("sub") or ""
    email = (claims.get("email") or "").strip().lower()
    u = db.query(User).filter_by(auth_provider="apple", provider_sub=sub).first() if sub else None
    if not u and email:
        u = db.query(User).filter_by(email=email).first()
    if not u:
        name = email.split("@")[0] if email else "Apple user"
        try:  # Apple sends the name only on the very first consent
            info = json.loads(form.get("user") or "{}")
            nm = info.get("name") or {}
            full = ((nm.get("firstName") or "") + " " + (nm.get("lastName") or "")).strip()
            if full:
                name = full
        except Exception:
            pass
        if not email:
            return RedirectResponse("/?auth_error=apple", status_code=302)
        u = User(name=name, email=email, password_hash=None,
                 auth_provider="apple", provider_sub=sub, plan="free")
        db.add(u); db.commit(); db.refresh(u)
        db.add(TokenLedger(user_id=u.id, delta=WELCOME_TOKENS, reason="welcome")); db.commit()
        queue_email(db, u, "welcome")
        queue_email(db, u, "next_steps")
    elif not u.provider_sub and sub:
        u.provider_sub = sub
        if not u.auth_provider or u.auth_provider == "password":
            pass  # keep the original provider label; sub is linked for next time
        db.commit()
    return _start_session(db, u, RedirectResponse("/", status_code=302))

# ----- Phone number + one-time code (OTP) -----
# Sign in (or sign up) with a phone number: we text a 6-digit code; entering it
# proves the person controls a real phone. SMS goes out through Twilio when
# TWILIO_ACCOUNT_SID / TWILIO_AUTH_TOKEN / TWILIO_FROM_NUMBER are set; until
# then the app runs in demo mode and shows the code on screen (same pattern as
# the email system before a sender was connected).
OTP_TTL_SECONDS = 600
OTP_MAX_ATTEMPTS = 5


def _normalize_phone(raw: str) -> str:
    digits = "".join(c for c in (raw or "") if c.isdigit())
    if len(digits) == 10:
        digits = "1" + digits
    if not (10 <= len(digits) <= 15):
        raise HTTPException(400, "Enter a valid phone number, with country code if outside the US")
    return "+" + digits


def _send_sms(phone: str, text: str) -> bool:
    sid = os.environ.get("TWILIO_ACCOUNT_SID", "")
    tok = os.environ.get("TWILIO_AUTH_TOKEN", "")
    frm = os.environ.get("TWILIO_FROM_NUMBER", "")
    if not (sid and tok and frm):
        return False
    import urllib.request as _u
    try:
        req = _u.Request(f"https://api.twilio.com/2010-04-01/Accounts/{sid}/Messages.json",
                         data=urllib.parse.urlencode({"To": phone, "From": frm, "Body": text}).encode(),
                         headers={"Authorization": "Basic " + base64.b64encode(f"{sid}:{tok}".encode()).decode(),
                                  "Content-Type": "application/x-www-form-urlencoded"})
        with _u.urlopen(req, timeout=20) as r:
            return r.status in (200, 201)
    except Exception:
        return False


@app.post("/api/auth/phone/start")
async def phone_start(request: Request, db: Session = Depends(get_db)):
    data = await request.json()
    phone = _normalize_phone(data.get("phone") or "")
    for old in db.query(AuthChallenge).filter_by(purpose="phone_otp").all():
        if old.challenge.split("|")[0] == phone:
            db.delete(old)
    db.commit()
    code = f"{secrets.randbelow(1000000):06d}"
    digest = hashlib.sha256(code.encode()).hexdigest()
    expires = int(time.time()) + OTP_TTL_SECONDS
    db.add(AuthChallenge(flow_id=secrets.token_urlsafe(24), purpose="phone_otp",
                         challenge=f"{phone}|{digest}|0|{expires}"))
    db.commit()
    sent = _send_sms(phone, f"Your Viavios code is {code}. It expires in 10 minutes.")
    return {"sent": True, "sms": sent, "demo_code": None if sent else code}


def _check_otp(db: Session, phone: str, code: str):
    """Validate a code; returns True or raises. Consumes the challenge on success."""
    row = None
    for r in db.query(AuthChallenge).filter_by(purpose="phone_otp").all():
        if r.challenge.split("|")[0] == phone:
            row = r
    if not row:
        raise HTTPException(400, "No code is waiting for that number — request a new one")
    parts = row.challenge.split("|")
    digest, attempts, expires = parts[1], int(parts[2]), int(parts[3])
    if int(time.time()) > expires:
        db.delete(row); db.commit()
        raise HTTPException(400, "That code has expired — request a new one")
    if not hmac.compare_digest(hashlib.sha256((code or "").strip().encode()).hexdigest(), digest):
        attempts += 1
        if attempts >= OTP_MAX_ATTEMPTS:
            db.delete(row); db.commit()
            raise HTTPException(400, "Too many wrong tries — request a new code")
        row.challenge = f"{phone}|{digest}|{attempts}|{expires}"; db.commit()
        raise HTTPException(401, "That code doesn't match — check and try again")
    db.delete(row); db.commit()
    return True


@app.post("/api/auth/phone/verify")
async def phone_verify(request: Request, db: Session = Depends(get_db)):
    data = await request.json()
    phone = _normalize_phone(data.get("phone") or "")
    _check_otp(db, phone, data.get("code") or "")
    # Signed-in user linking a phone to their account?
    me_user = current_user(request, db)
    owner = db.query(User).filter_by(phone=phone).first()
    if me_user:
        if owner and owner.id != me_user.id:
            raise HTTPException(400, "That number already belongs to another account")
        me_user.phone = phone; me_user.phone_verified = True; db.commit()
        return user_json(me_user)
    if owner and owner.phone_verified:
        return set_session(db, owner)
    flow = _store_flow(db, "phone_verified", phone)
    return {"needs_profile": True, "flow": flow}


@app.post("/api/auth/phone/complete")
async def phone_complete(request: Request, db: Session = Depends(get_db)):
    data = await request.json()
    row = db.query(AuthChallenge).filter_by(flow_id=data.get("flow") or "", purpose="phone_verified").first()
    if not row or (datetime.utcnow() - row.created_at).total_seconds() > 1800:
        raise HTTPException(400, "That verification has expired — start again")
    phone = row.challenge
    name = (data.get("name") or "").strip()
    if not name:
        raise HTTPException(400, "Your name is required")
    if data.get("accept_terms") is not True:
        raise HTTPException(400, "Please agree to the Terms of Use and Privacy Policy to create your account")
    if db.query(User).filter_by(phone=phone).first():
        raise HTTPException(400, "An account with that number already exists — sign in instead")
    db.delete(row); db.commit()
    u = User(name=name, email=f"{phone.replace('+', '')}@phone.viavios.local", password_hash=None,
             auth_provider="phone", plan="free", phone=phone, phone_verified=True,
             terms_version=TERMS_VERSION, terms_accepted_at=datetime.utcnow())
    db.add(u); db.commit(); db.refresh(u)
    db.add(TokenLedger(user_id=u.id, delta=WELCOME_TOKENS, reason="welcome")); db.commit()
    queue_email(db, u, "welcome")
    queue_email(db, u, "next_steps")
    return set_session(db, u)


# ----- Passkeys (WebAuthn — Face ID, Touch ID, Android, Windows Hello) -----
from webauthn import (generate_registration_options, verify_registration_response,
                      generate_authentication_options, verify_authentication_response, options_to_json)
from webauthn.helpers import base64url_to_bytes, bytes_to_base64url
from webauthn.helpers.structs import (AuthenticatorSelectionCriteria, ResidentKeyRequirement,
                                      UserVerificationRequirement, PublicKeyCredentialDescriptor)

@app.post("/api/passkeys/register/options")
def passkey_register_options(request: Request, db: Session = Depends(get_db), user: User = Depends(require_user)):
    existing = db.query(PasskeyCredential).filter_by(user_id=user.id).all()
    opts = generate_registration_options(
        rp_id=_rp_id(request), rp_name="Viavios",
        user_id=str(user.id).encode(), user_name=user.email, user_display_name=user.name,
        authenticator_selection=AuthenticatorSelectionCriteria(
            resident_key=ResidentKeyRequirement.PREFERRED,
            user_verification=UserVerificationRequirement.PREFERRED),
        exclude_credentials=[PublicKeyCredentialDescriptor(id=base64url_to_bytes(c.credential_id)) for c in existing])
    flow = _store_flow(db, "passkey_register", bytes_to_base64url(opts.challenge), user_id=user.id)
    resp = JSONResponse(_json.loads(options_to_json(opts)))
    resp.set_cookie("wa_flow", flow, httponly=True, samesite="lax", max_age=300)
    return resp

@app.post("/api/passkeys/register/verify")
async def passkey_register_verify(request: Request, db: Session = Depends(get_db), user: User = Depends(require_user)):
    body = await request.json()
    row = _take_flow(db, request.cookies.get("wa_flow"), "passkey_register")
    if not row or row.user_id != user.id:
        raise HTTPException(400, "Passkey setup expired — please try again")
    try:
        verified = verify_registration_response(
            credential=body, expected_challenge=base64url_to_bytes(row.challenge),
            expected_origin=_app_base(request), expected_rp_id=_rp_id(request))
    except Exception as e:
        raise HTTPException(400, f"That passkey could not be verified ({str(e)[:120]})")
    transports = body.get("response", {}).get("transports") or []
    db.add(PasskeyCredential(user_id=user.id, credential_id=bytes_to_base64url(verified.credential_id),
                             public_key=bytes_to_base64url(verified.credential_public_key),
                             sign_count=verified.sign_count, transports=",".join(transports)))
    db.commit()
    return {"ok": True}

@app.post("/api/passkeys/login/options")
def passkey_login_options(request: Request, db: Session = Depends(get_db)):
    opts = generate_authentication_options(rp_id=_rp_id(request),
                                           user_verification=UserVerificationRequirement.PREFERRED)
    flow = _store_flow(db, "passkey_login", bytes_to_base64url(opts.challenge))
    resp = JSONResponse(_json.loads(options_to_json(opts)))
    resp.set_cookie("wa_flow", flow, httponly=True, samesite="lax", max_age=300)
    return resp

@app.post("/api/passkeys/login/verify")
async def passkey_login_verify(request: Request, db: Session = Depends(get_db)):
    body = await request.json()
    row = _take_flow(db, request.cookies.get("wa_flow"), "passkey_login")
    if not row:
        raise HTTPException(400, "Passkey sign-in expired — please try again")
    cred = db.query(PasskeyCredential).filter_by(credential_id=body.get("id") or "").first()
    if not cred:
        raise HTTPException(400, "That passkey is not registered here — sign in another way first, then add it in your Account page")
    user = db.query(User).filter_by(id=cred.user_id).first()
    try:
        verified = verify_authentication_response(
            credential=body, expected_challenge=base64url_to_bytes(row.challenge),
            expected_origin=_app_base(request), expected_rp_id=_rp_id(request),
            credential_public_key=base64url_to_bytes(cred.public_key),
            credential_current_sign_count=cred.sign_count)
    except Exception as e:
        raise HTTPException(400, f"That passkey could not be verified ({str(e)[:120]})")
    cred.sign_count = verified.new_sign_count; db.commit()
    return set_session(db, user)

@app.get("/api/me/passkeys")
def my_passkeys(db: Session = Depends(get_db), user: User = Depends(require_user)):
    rows = db.query(PasskeyCredential).filter_by(user_id=user.id).order_by(PasskeyCredential.created_at.desc()).all()
    return [{"id": r.id, "created_at": r.created_at.isoformat() if r.created_at else None} for r in rows]

@app.delete("/api/me/passkeys/{pid}")
def delete_passkey(pid: int, db: Session = Depends(get_db), user: User = Depends(require_user)):
    row = db.query(PasskeyCredential).filter_by(id=pid, user_id=user.id).first()
    if not row:
        raise HTTPException(404, "Passkey not found")
    db.delete(row); db.commit()
    return {"ok": True}

# ---------- Books ----------
@app.get("/api/books")
def my_books(db: Session = Depends(get_db), user: User = Depends(require_user)):
    books = db.query(Book).filter_by(owner_id=user.id).order_by(Book.created_at.desc()).all()
    return [book_json(db, b) for b in books]

@app.post("/api/books")
async def create_book(request: Request, db: Session = Depends(get_db), user: User = Depends(require_user)):
    data = await request.json()
    if user.plan not in PAID_PLANS:
        count = db.query(Book).filter_by(owner_id=user.id).count()
        if count >= FREE_BOOK_LIMIT:
            raise HTTPException(402, {"error": "Free plan allows 1 book. Upgrade to create more books.", "upgrade_required": True})
    title = (data.get("title") or "").strip()
    if not title:
        raise HTTPException(400, "Title is required")
    b = Book(owner_id=user.id, title=title, type=data.get("type") or "Memoir",
             description=data.get("description") or "")
    db.add(b); db.commit(); db.refresh(b)
    return book_json(db, b)

@app.put("/api/books/{book_id}")
async def update_book(book_id: int, request: Request, db: Session = Depends(get_db), user: User = Depends(require_user)):
    b = get_own_book(db, book_id, user)
    data = await request.json()
    new_visibility = data.get("visibility", b.visibility)
    if new_visibility == "testament" and user.plan not in PAID_PLANS:
        raise HTTPException(402, {"error": "Testament setup is a paid-plan feature. Upgrade to use it.", "upgrade_required": True})
    for field in ("title", "type", "description", "visibility", "family_emails", "testament_recipients", "release_note", "font"):
        if field in data:
            setattr(b, field, data[field])
    if "publisher_optin" in data:
        b.publisher_optin = bool(data["publisher_optin"])
    db.commit(); db.refresh(b)
    return book_json(db, b)

@app.delete("/api/books/{book_id}")
def delete_book(book_id: int, db: Session = Depends(get_db), user: User = Depends(require_user)):
    b = get_own_book(db, book_id, user)
    for model in (Chapter, Media, TimelineEntry, Letter, Vote):
        db.query(model).filter_by(book_id=b.id).delete()
    db.delete(b); db.commit()
    return {"ok": True}

@app.get("/api/books/{book_id}")
def read_book(book_id: int, request: Request, db: Session = Depends(get_db)):
    b = db.query(Book).filter_by(id=book_id).first()
    user = current_user(request, db)
    if not b or not can_read_book(db, b, user):
        raise HTTPException(404, "Book not found or not shared with you")
    chapters = db.query(Chapter).filter_by(book_id=b.id).order_by(Chapter.sort_order, Chapter.id).all()
    # Non-owners only see published chapters that are inherit/public (owner sees all, incl. drafts)
    if not (user and user.id == b.owner_id):
        chapters = [c for c in chapters if c.visibility in ("inherit", "public")
                    and (getattr(c, "status", None) or "published") == "published"]
    media = db.query(Media).filter_by(book_id=b.id).all()
    timeline = db.query(TimelineEntry).filter_by(book_id=b.id).order_by(TimelineEntry.id).all()
    letters = db.query(Letter).filter_by(book_id=b.id).all() if (user and user.id == b.owner_id) else []
    data = book_json(db, b, include_owner=True)
    data["chapters"] = [{"id": c.id, "title": c.title, "body": c.body, "visibility": c.visibility,
                         "status": getattr(c, "status", None) or "published"} for c in chapters]
    data["media"] = [{"id": m.id, "chapter_id": m.chapter_id, "kind": m.kind,
                      "url": getattr(m, "url", None) or (f"/uploads/{m.filename}" if m.filename else None),
                      "original_name": m.original_name, "transcript": m.transcript or ""} for m in media]
    data["timeline"] = [{"id": t.id, "date_text": t.date_text, "event_text": t.event_text} for t in timeline]
    data["letters"] = [{"id": l.id, "recipient_name": l.recipient_name, "body": l.body} for l in letters]
    data["my_vote"] = bool(user and db.query(Vote).filter_by(book_id=b.id, user_id=user.id).first())
    return data

# ---------- Chapters ----------
@app.post("/api/books/{book_id}/chapters")
async def create_chapter(book_id: int, request: Request, db: Session = Depends(get_db), user: User = Depends(require_user)):
    b = get_own_book(db, book_id, user)
    data = await request.json()
    c = Chapter(book_id=b.id, title=(data.get("title") or "Untitled chapter").strip(),
                body=data.get("body") or "", visibility=data.get("visibility") or "inherit",
                status=data.get("status") if data.get("status") in ("draft", "published") else "published",
                sort_order=db.query(Chapter).filter_by(book_id=b.id).count())
    db.add(c); db.commit(); db.refresh(c)
    return {"id": c.id, "title": c.title, "body": c.body, "visibility": c.visibility, "status": c.status}

@app.put("/api/chapters/{chapter_id}")
async def update_chapter(chapter_id: int, request: Request, db: Session = Depends(get_db), user: User = Depends(require_user)):
    c = db.query(Chapter).filter_by(id=chapter_id).first()
    if not c:
        raise HTTPException(404, "Chapter not found")
    get_own_book(db, c.book_id, user)
    data = await request.json()
    for field in ("title", "body", "visibility"):
        if field in data:
            setattr(c, field, data[field])
    if data.get("status") in ("draft", "published"):
        c.status = data["status"]
    db.commit()
    return {"id": c.id, "title": c.title, "body": c.body, "visibility": c.visibility,
            "status": getattr(c, "status", None) or "published"}

@app.delete("/api/chapters/{chapter_id}")
def delete_chapter(chapter_id: int, db: Session = Depends(get_db), user: User = Depends(require_user)):
    c = db.query(Chapter).filter_by(id=chapter_id).first()
    if not c:
        raise HTTPException(404, "Chapter not found")
    get_own_book(db, c.book_id, user)
    db.query(Media).filter_by(chapter_id=c.id).update({"chapter_id": None})
    db.delete(c); db.commit()
    return {"ok": True}

# ---------- Media / timeline / letters ----------
@app.post("/api/books/{book_id}/media")
async def upload_media(book_id: int, kind: str = Form("photo"), chapter_id: str = Form(""),
                       transcript: str = Form(""), url: str = Form(""), file: UploadFile = File(None),
                       db: Session = Depends(get_db), user: User = Depends(require_user)):
    b = get_own_book(db, book_id, user)
    cid = int(chapter_id) if chapter_id.strip().isdigit() else None
    if kind == "voice_transcript":
        m = Media(book_id=b.id, chapter_id=cid, kind=kind, transcript=transcript)
    elif kind == "youtube":
        link = (url or transcript or "").strip()
        if not link.startswith("http"):
            raise HTTPException(400, "A YouTube link is required")
        m = Media(book_id=b.id, chapter_id=cid, kind="youtube", url=link, original_name="YouTube video")
    else:
        if file is None:
            raise HTTPException(400, "A file is required for photo/audio uploads")
        safe = f"{b.id}_{secrets.token_hex(6)}_{Path(file.filename or 'file').name}"
        dest = UPLOAD_DIR / safe
        with dest.open("wb") as out:
            shutil.copyfileobj(file.file, out)
        m = Media(book_id=b.id, chapter_id=cid, kind=kind, filename=safe, original_name=file.filename or safe)
    db.add(m); db.commit(); db.refresh(m)
    return {"id": m.id, "kind": m.kind, "url": getattr(m, "url", None) or (f"/uploads/{m.filename}" if m.filename else None), "transcript": m.transcript or ""}

@app.post("/api/books/{book_id}/timeline")
async def add_timeline(book_id: int, request: Request, db: Session = Depends(get_db), user: User = Depends(require_user)):
    b = get_own_book(db, book_id, user)
    data = await request.json()
    t = TimelineEntry(book_id=b.id, date_text=data.get("date_text") or "", event_text=(data.get("event_text") or "").strip())
    if not t.event_text:
        raise HTTPException(400, "Event text is required")
    db.add(t); db.commit(); db.refresh(t)
    return {"id": t.id, "date_text": t.date_text, "event_text": t.event_text}

@app.post("/api/books/{book_id}/letters")
async def add_letter(book_id: int, request: Request, db: Session = Depends(get_db), user: User = Depends(require_user)):
    b = get_own_book(db, book_id, user)
    data = await request.json()
    l = Letter(book_id=b.id, recipient_name=(data.get("recipient_name") or "").strip(), body=data.get("body") or "")
    if not l.recipient_name:
        raise HTTPException(400, "Recipient name is required")
    db.add(l); db.commit(); db.refresh(l)
    return {"id": l.id, "recipient_name": l.recipient_name, "body": l.body}

# ---------- Writing tools: Google Docs import, grammar, AI suggestions ----------
@app.post("/api/books/{book_id}/import/google-doc")
async def import_google_doc(book_id: int, request: Request, db: Session = Depends(get_db), user: User = Depends(require_user)):
    """Import a Google Doc shared as 'anyone with the link can view' as a new
    draft chapter. Private docs arrive with the full Google sign-in setup."""
    import re as _re, urllib.request as _u
    b = get_own_book(db, book_id, user)
    data = await request.json()
    m = _re.search(r"docs\.google\.com/document/d/([\w-]{10,})", data.get("url") or "")
    if not m:
        raise HTTPException(400, "That doesn't look like a Google Docs link. Copy the link from your document (Share → Copy link).")
    export_url = f"https://docs.google.com/document/d/{m.group(1)}/export?format=txt"
    try:
        req = _u.Request(export_url, headers={"User-Agent": "Mozilla/5.0"})
        with _u.urlopen(req, timeout=20) as r:
            text = r.read().decode("utf-8", "replace")
    except Exception:
        raise HTTPException(400, "Google wouldn't share that document. In the Doc, choose Share → 'Anyone with the link' → Viewer, then try again.")
    lines = [ln for ln in text.splitlines()]
    title = next((ln.strip() for ln in lines if ln.strip()), "Imported from Google Docs")
    c = Chapter(book_id=b.id, title=title[:255], body=text.strip(), status="draft",
                sort_order=db.query(Chapter).filter_by(book_id=b.id).count())
    db.add(c); db.commit(); db.refresh(c)
    return {"id": c.id, "title": c.title, "status": c.status, "chars": len(text)}


@app.post("/api/grammar/check")
async def grammar_check(request: Request, user: User = Depends(require_user)):
    """Grammarly-style check via the public LanguageTool API. Runs only when
    the writer clicks Check grammar — their text is sent for that check only."""
    import urllib.request as _u, urllib.parse as _p
    data = await request.json()
    text = (data.get("text") or "")[:20000]
    if len(text.strip()) < 3:
        return {"matches": []}
    form = _p.urlencode({"text": text, "language": "en-US"}).encode()
    try:
        req = _u.Request("https://api.languagetool.org/v2/check", data=form,
                         headers={"Content-Type": "application/x-www-form-urlencoded",
                                  "User-Agent": "Viavios/1.0 (memoir writing app)",
                                  "Accept": "application/json"})
        with _u.urlopen(req, timeout=25) as r:
            out = json.loads(r.read().decode())
    except Exception as e:
        code = getattr(e, "code", None)
        hint = f" (the checker answered {code})" if code else ""
        raise HTTPException(502, "The grammar checker is unreachable right now — your writing is saved; try again in a moment." + hint)
    return {"matches": [{"message": mt.get("message", ""), "offset": mt.get("offset", 0),
                         "length": mt.get("length", 0),
                         "replacements": [x.get("value", "") for x in mt.get("replacements", [])][:5]}
                        for mt in out.get("matches", [])][:60]}


@app.post("/api/ai/suggest")
async def ai_suggest(request: Request, db: Session = Depends(get_db), user: User = Depends(require_user)):
    """AI writing suggestions. Privacy rule: a passage is sent to the AI only
    when the writer clicks for a suggestion, and nothing is stored from it.
    Activates when AI_API_KEY is configured (OpenAI-compatible endpoint)."""
    import urllib.request as _u
    key = os.environ.get("AI_API_KEY", "")
    if not key:
        raise HTTPException(501, "AI suggestions are not switched on yet — they arrive with the AI key. Your words stay private either way: text is only ever sent when you click for a suggestion.")
    balance = user.token_balance if user.token_balance is not None else WELCOME_TOKENS
    if balance < AI_SUGGEST_COST:
        raise HTTPException(402, f"An AI suggestion costs {AI_SUGGEST_COST} tokens and your balance is {balance}. Token packs are on the Pricing page.")
    data = await request.json()
    text = (data.get("text") or "")[:6000]
    if len(text.strip()) < 10:
        raise HTTPException(400, "Write a few sentences first, then ask for a suggestion.")
    base = os.environ.get("AI_API_BASE", "https://api.openai.com/v1").rstrip("/")
    payload = {"model": os.environ.get("AI_MODEL", "gpt-4o-mini"),
               "messages": [{"role": "system", "content": "You help memoir writers. Reply with ONE short, concrete suggestion (a stronger opening line, a detail to add, or a gentler phrasing) for the passage. Keep the writer's voice. Under 60 words."},
                            {"role": "user", "content": text}],
               "max_tokens": 160}
    try:
        req = _u.Request(base + "/chat/completions", data=json.dumps(payload).encode(),
                         headers={"Authorization": "Bearer " + key, "Content-Type": "application/json"})
        with _u.urlopen(req, timeout=30) as r:
            out = json.loads(r.read().decode())
        suggestion = out["choices"][0]["message"]["content"].strip()
    except Exception:
        raise HTTPException(502, "The AI helper is unreachable right now — try again in a moment.")
    move_tokens(db, user, -AI_SUGGEST_COST, "ai_suggest")
    db.commit()
    return {"suggestion": suggestion, "tokens_charged": AI_SUGGEST_COST,
            "balance": user.token_balance}


# ---------- Discover / voting / publishers ----------
@app.get("/api/discover")
def discover(db: Session = Depends(get_db), sort: str = "votes"):
    books = db.query(Book).filter_by(visibility="public").all()
    out = [book_json(db, b, include_owner=True) for b in books]
    out.sort(key=lambda x: x["votes"], reverse=True) if sort == "votes" else out.sort(key=lambda x: x["created_at"] or "", reverse=True)
    return out

@app.get("/api/publishers")
def publishers(db: Session = Depends(get_db)):
    books = db.query(Book).filter_by(visibility="public", publisher_optin=True).all()
    out = [book_json(db, b, include_owner=True) for b in books]
    out.sort(key=lambda x: x["votes"], reverse=True)
    return out

@app.post("/api/books/{book_id}/vote")
def vote(book_id: int, db: Session = Depends(get_db), user: User = Depends(require_user)):
    b = db.query(Book).filter_by(id=book_id, visibility="public").first()
    if not b:
        raise HTTPException(404, "Public book not found")
    if db.query(Vote).filter_by(book_id=b.id, user_id=user.id).first():
        raise HTTPException(400, "You already voted for this book")
    db.add(Vote(book_id=b.id, user_id=user.id)); db.commit()
    return {"ok": True, "votes": vote_count(db, b.id)}

# ---------- Plans / simulated checkout ----------
PLANS = [
    {"id": "free", "name": "Free", "price": "$0", "features": ["1 book", "Chapters, timeline, letters, photo & voice uploads", "Private and Family sharing", "Read in app"]},
    {"id": "subscription_monthly", "name": "Keeper — Monthly", "price": "$9/month", "features": ["Unlimited books", "PDF export", "Testament setup & recipients", "Public stories + publisher opt-in", "Print ordering"]},
    {"id": "subscription_yearly", "name": "Keeper — Yearly", "price": "$79/year", "features": ["Everything in Monthly", "Two months free vs monthly"]},
    {"id": "lifetime", "name": "Lifetime Legacy — One-time", "price": "$249 once", "features": ["Everything in Keeper, forever", "No subscription — one payment"]},
]

@app.get("/api/plans")
def plans():
    return PLANS

@app.post("/api/checkout")
async def checkout(request: Request, db: Session = Depends(get_db), user: User = Depends(require_user)):
    data = await request.json()
    plan = data.get("plan")
    pack = next((p for p in TOKEN_PACKS if p["id"] == plan), None)
    if plan not in [p["id"] for p in PLANS] and not pack:
        raise HTTPException(400, "Unknown plan")
    if os.environ.get("STRIPE_SECRET_KEY"):
        return _stripe_checkout(request, user, plan)
    if pack:
        # Token pack: balance grows, plan unchanged. Simulated like the plans.
        move_tokens(db, user, pack["tokens"], "token_pack")
        db.commit()
        queue_email(db, user, "payment_receipt", plan_name=pack["name"], price=pack["price"],
                    date=datetime.utcnow().strftime("%B %d, %Y"), simulated=True)
        return {"ok": True, "simulated": True, "tokens_granted": pack["tokens"], "user": user_json(user)}
    if plan not in [p["id"] for p in PLANS]:
        raise HTTPException(400, "Unknown plan")
    # SIMULATED checkout: no real payment is taken. Stripe replaces this endpoint at real launch (see README).
    user.plan = plan
    grant = PLAN_TOKEN_GRANTS.get(plan, 0)
    if grant:
        move_tokens(db, user, grant, "plan_grant")
    db.commit()
    plan_info = next((p for p in PLANS if p["id"] == plan), {"name": plan, "price": ""})
    queue_email(db, user, "payment_receipt", plan_name=plan_info["name"], price=plan_info["price"],
                date=datetime.utcnow().strftime("%B %d, %Y"), simulated=True)
    return {"ok": True, "simulated": True, "user": user_json(user)}


# ---------- Stripe (real payments; activates when STRIPE_SECRET_KEY is set) ----------
# item id -> (checkout mode, unit amount in cents, recurring interval or None)
STRIPE_ITEMS = {
    "subscription_monthly": ("subscription", 900, "month"),
    "subscription_yearly": ("subscription", 7900, "year"),
    "lifetime": ("payment", 24900, None),
    "tokens_100": ("payment", 500, None),
    "tokens_300": ("payment", 1200, None),
}


def _item_name(item: str) -> str:
    p = next((x for x in PLANS if x["id"] == item), None) or next((x for x in TOKEN_PACKS if x["id"] == item), None)
    return p["name"] if p else item


def _stripe_checkout(request: Request, user: User, item: str):
    import urllib.request as _u
    mode, amount, interval = STRIPE_ITEMS[item]
    base = _app_base(request)
    fields = {
        "mode": mode,
        "success_url": base + "/?paid=1",
        "cancel_url": base + "/?paid=0",
        "client_reference_id": str(user.id),
        "customer_email": user.email,
        "metadata[user_id]": str(user.id),
        "metadata[item]": item,
        "line_items[0][quantity]": "1",
        "line_items[0][price_data][currency]": "usd",
        "line_items[0][price_data][unit_amount]": str(amount),
        "line_items[0][price_data][product_data][name]": "Viavios — " + _item_name(item),
    }
    if interval:
        fields["line_items[0][price_data][recurring][interval]"] = interval
    api = os.environ.get("STRIPE_API_BASE", "https://api.stripe.com").rstrip("/")
    try:
        req = _u.Request(api + "/v1/checkout/sessions",
                         data=urllib.parse.urlencode(fields).encode(),
                         headers={"Authorization": "Bearer " + os.environ["STRIPE_SECRET_KEY"],
                                  "Content-Type": "application/x-www-form-urlencoded"})
        with _u.urlopen(req, timeout=25) as r:
            sess = json.loads(r.read().decode())
        return {"checkout_url": sess["url"], "stripe": True}
    except Exception:
        raise HTTPException(502, "Stripe could not open the checkout just now — no charge was made. Try again in a moment.")


def _apply_purchase(db: Session, user: User, item: str, simulated: bool):
    """Grant whatever an item buys + send the receipt. Caller commits."""
    pack = next((p for p in TOKEN_PACKS if p["id"] == item), None)
    if pack:
        move_tokens(db, user, pack["tokens"], "token_pack")
        name, price = pack["name"], pack["price"]
    else:
        user.plan = item
        grant = PLAN_TOKEN_GRANTS.get(item, 0)
        if grant:
            move_tokens(db, user, grant, "plan_grant")
        info = next((p for p in PLANS if p["id"] == item), {"name": item, "price": ""})
        name, price = info["name"], info["price"]
    db.commit()
    queue_email(db, user, "payment_receipt", plan_name=name, price=price,
                date=datetime.utcnow().strftime("%B %d, %Y"), simulated=simulated)


@app.get("/api/payments/status")
def payments_status():
    return {"stripe": bool(os.environ.get("STRIPE_SECRET_KEY"))}


@app.post("/api/stripe/webhook")
async def stripe_webhook(request: Request, db: Session = Depends(get_db)):
    payload = await request.body()
    secret = os.environ.get("STRIPE_WEBHOOK_SECRET", "")
    if secret:
        sig = request.headers.get("stripe-signature", "")
        parts = dict(p.split("=", 1) for p in sig.split(",") if "=" in p)
        # multiple v1 values possible; collect them all
        v1s = [p.split("=", 1)[1] for p in sig.split(",") if p.startswith("v1=")]
        try:
            t = int(parts.get("t", "0"))
        except Exception:
            raise HTTPException(400, "Bad signature")
        expected = hmac.new(secret.encode(), str(t).encode() + b"." + payload, hashlib.sha256).hexdigest()
        if abs(int(time.time()) - t) > 300 or not any(hmac.compare_digest(expected, v) for v in v1s):
            raise HTTPException(400, "Bad signature")
    try:
        evt = json.loads(payload.decode())
    except Exception:
        raise HTTPException(400, "Bad payload")
    if evt.get("type") == "checkout.session.completed":
        sess = evt.get("data", {}).get("object", {})
        md = sess.get("metadata") or {}
        try:
            uid = int(md.get("user_id", "0"))
        except Exception:
            uid = 0
        item = md.get("item", "")
        user = db.query(User).filter_by(id=uid).first()
        if user and item in STRIPE_ITEMS:
            if db.query(StripeEvent).filter_by(event_id=evt.get("id", "")).first():
                return {"ok": True, "duplicate": True}
            db.add(StripeEvent(event_id=evt.get("id", "")))
            db.commit()
            _apply_purchase(db, user, item, simulated=False)
    return {"ok": True}


@app.get("/api/token-packs")
def token_packs():
    return TOKEN_PACKS


@app.get("/api/me/tokens")
def my_tokens(db: Session = Depends(get_db), user: User = Depends(require_user)):
    rows = (db.query(TokenLedger).filter_by(user_id=user.id)
            .order_by(TokenLedger.id.desc()).limit(30).all())
    return {"balance": user.token_balance if user.token_balance is not None else WELCOME_TOKENS,
            "ai_suggest_cost": AI_SUGGEST_COST,
            "ledger": [{"delta": r.delta, "reason": r.reason,
                        "created_at": r.created_at.isoformat() if r.created_at else None} for r in rows]}

# ---------- PDF export (paid gate) ----------
@app.get("/api/books/{book_id}/pdf")
def export_pdf(book_id: int, request: Request, db: Session = Depends(get_db)):
    user = current_user(request, db)
    if not user:
        raise HTTPException(401, "Sign in required")
    b = db.query(Book).filter_by(id=book_id).first()
    if not b or not can_read_book(db, b, user):
        raise HTTPException(404, "Book not found")
    if b.owner_id == user.id and user.plan not in PAID_PLANS:
        raise HTTPException(402, "PDF export is a paid-plan feature. Upgrade on the Pricing page.")
    from fpdf import FPDF
    def clean(s):
        return (s or "").encode("latin-1", "replace").decode("latin-1")
    def txt(pdf, size, style, h, s):
        pdf.set_font("helvetica", style, size)
        pdf.set_x(pdf.l_margin)
        pdf.multi_cell(0, h, clean(s), new_x="LMARGIN", new_y="NEXT")
    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=20)
    pdf.add_page()
    txt(pdf, 24, "B", 12, b.title)
    txt(pdf, 12, "", 7, f"{b.type} - Viavios")
    if b.description:
        pdf.ln(4); txt(pdf, 12, "", 7, b.description)
    chapters = db.query(Chapter).filter_by(book_id=b.id).order_by(Chapter.sort_order, Chapter.id).all()
    for c in chapters:
        pdf.add_page()
        txt(pdf, 18, "B", 10, c.title)
        txt(pdf, 12, "", 7, c.body or "")
    timeline = db.query(TimelineEntry).filter_by(book_id=b.id).all()
    if timeline:
        pdf.add_page(); txt(pdf, 18, "B", 10, "Chronicle / Timeline")
        for t in timeline:
            txt(pdf, 12, "", 7, f"{t.date_text}: {t.event_text}")
    out = bytes(pdf.output())
    return Response(content=out, media_type="application/pdf",
                    headers={"Content-Disposition": f'attachment; filename="remora-book-{b.id}.pdf"'})

# ---------- Bundled photos (base64 fallback) ----------
# The photographs travel in the repo as base64 text (static/img_b64/) because
# the GitHub push pipeline carries text only; decode_photos.py restores the
# .jpg files at build time on hosts that run it. On hosts that never run the
# restore step (e.g. Vercel), serve the photos by decoding the .b64 on the fly.
@app.get("/static/img/{img_name}")
def static_img(img_name: str):
    if "/" in img_name or "\\" in img_name or ".." in img_name:
        raise HTTPException(status_code=404)
    jpg = BASE_DIR / "static" / "img" / img_name
    if jpg.exists():
        return FileResponse(str(jpg), media_type="image/jpeg")
    b64 = BASE_DIR / "static" / "img_b64" / (img_name + ".b64")
    if b64.exists():
        data = base64.b64decode(b64.read_text())
        return Response(content=data, media_type="image/jpeg",
                        headers={"Cache-Control": "public, max-age=86400"})
    raise HTTPException(status_code=404)

# ---------- Static frontend ----------
app.mount("/uploads", StaticFiles(directory=str(UPLOAD_DIR)), name="uploads")
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")

@app.get("/")
def index():
    return FileResponse(BASE_DIR / "static" / "index.html")


@app.post("/api/me/accept-terms")
def accept_terms(db: Session = Depends(get_db), user: User = Depends(require_user)):
    """Clickwrap acceptance for accounts created via Google/Apple/passkeys,
    and for future terms versions. Records the version + timestamp."""
    user.terms_version = TERMS_VERSION
    user.terms_accepted_at = datetime.utcnow()
    db.commit()
    return user_json(user)


@app.get("/privacy")
def privacy():
    return FileResponse(BASE_DIR / "static" / "privacy.html")


@app.get("/terms")
def terms():
    return FileResponse(BASE_DIR / "static" / "terms.html")

@app.get("/health")
def health():
    return {"ok": True, "app": "remora"}
