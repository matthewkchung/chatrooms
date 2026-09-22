from dotenv import load_dotenv
load_dotenv()   # Load .env file into environment variables


from flask import Flask, render_template, request, session, redirect, url_for, flash, abort
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from sqlalchemy import func
from datetime import datetime, timezone
from functools import wraps
from werkzeug.middleware.proxy_fix import ProxyFix
import msal
import uuid
import os

app = Flask(__name__)
app.wsgi_app = ProxyFix(app.wsgi_app, x_proto=1, x_host=1)

# Database configuration
database_url = os.environ.get("DATABASE_URL")
if not database_url:
    raise RuntimeError("DATABASE_URL environment variable is required.")

# Some platforms still provide the deprecated postgres:// prefix.
if database_url.startswith("postgres://"):
    database_url = database_url.replace("postgres://", "postgresql://", 1)

app.config["SQLALCHEMY_DATABASE_URI"] = database_url
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

# Flask session security
app.secret_key = os.environ.get("SECRET_KEY", "development-only-secret-key")

# ── Microsoft Entra ID Configuration ─────────────────────────
CLIENT_ID = os.environ.get("CLIENT_ID")
CLIENT_SECRET = os.environ.get("CLIENT_SECRET")
TENANT_ID = os.environ.get("TENANT_ID", "common")

AUTHORITY = f"https://login.microsoftonline.com/{TENANT_ID}"
SCOPE = ["User.Read"]

# Database setup
db = SQLAlchemy(app)
migrate = Migrate(app, db)


# ── Microsoft Entra helper ───────────────────────────────────
def _build_msal_app():
    """Create an MSAL ConfidentialClientApplication instance."""
    return msal.ConfidentialClientApplication(
        CLIENT_ID,
        authority=AUTHORITY,
        client_credential=CLIENT_SECRET
    )

def login_required(f):
    """Decorator: redirect to Microsoft login if user is not in session."""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user' not in session:
            # Save where the user was trying to go
            session['next'] = request.url
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function


class Room(db.Model):
    __tablename__ = "rooms"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    created_by = db.Column(db.String(80), nullable=False)
    created_at = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )

    messages = db.relationship(
        "Message",
        back_populates="room",
        cascade="all, delete-orphan",
        lazy="selectin",
    )


class Message(db.Model):
    __tablename__ = "messages"

    id = db.Column(db.Integer, primary_key=True)
    room_id = db.Column(
        db.Integer,
        db.ForeignKey("rooms.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    author = db.Column(db.String(80), nullable=False)
    content = db.Column(db.Text, nullable=False)
    posted_at = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        index=True,
    )

    room = db.relationship("Room", back_populates="messages")


@app.template_filter("datetime")
def format_datetime(value):
    if value is None:
        return "No activity yet"

    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)

    return value.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

@app.route('/login')
def login():
    """Redirect the user to Microsoft's login page."""
    # Generate a random state value to prevent CSRF attacks
    session['state'] = str(uuid.uuid4())

    auth_url = _build_msal_app().get_authorization_request_url(
        SCOPE,
        state=session['state'],
        redirect_uri=url_for('callback', _external=True)
    )
    return redirect(auth_url)

@app.route('/callback')
def callback():
    """Microsoft redirects here after the user logs in."""

    # Security check: verify the state matches to prevent CSRF
    if request.args.get('state') != session.get('state'):
        return redirect(url_for('index'))

    # Check if Microsoft returned an error (e.g. user cancelled login)
    if 'error' in request.args:
        error_msg = request.args.get('error_description', request.args.get('error'))
        return f'<h2>Login Error</h2><p>{error_msg}</p><a href="/">Return home</a>'

    # Exchange the authorization code for an ID token
    result = _build_msal_app().acquire_token_by_authorization_code(
        request.args['code'],
        scopes=SCOPE,
        redirect_uri=url_for('callback', _external=True)
    )

    if 'error' in result:
        return f'<h2>Token Error</h2><p>{result.get("error_description")}</p>'

    # Store the token claims in the session (contains name, email, etc.)
    session['user'] = result.get('id_token_claims')

    # Redirect to where the user was trying to go, or the home page
    next_page = session.pop('next', None)
    return redirect(next_page or url_for('index'))

@app.route('/logout')
def logout():
    """Clear the local session and sign out of Microsoft."""
    session.clear()
    # Redirect to Microsoft's logout endpoint so the browser session is fully cleared
    logout_url = (
        AUTHORITY
        + '/oauth2/v2.0/logout'
        + '?post_logout_redirect_uri='
        + url_for('index', _external=True)
    )
    return redirect(logout_url)


@app.route("/", methods=["GET", "POST"])
@login_required
def home():
    if request.method == "POST":
        room_name = request.form.get("name", "").strip()

        if not room_name:
            return redirect(url_for("home"))

        if len(room_name) > 120:
            room_name = room_name[:120]

        room = Room(
            name=room_name,
            created_by=session["user"]["name"],
        )
        db.session.add(room)
        db.session.commit()

        return redirect(url_for("room", room_id=room.id))

    message_count = func.count(Message.id).label("message_count")
    last_activity = func.max(Message.posted_at).label("last_activity")

    rooms = (
        db.session.query(
            Room,
            message_count,
            last_activity,
        )
        .outerjoin(Message, Room.id == Message.room_id)
        .group_by(Room.id)
        .order_by(
            func.coalesce(last_activity, Room.created_at).desc(),
            Room.id.desc(),
        )
        .all()
    )

    return render_template(
        "home.html",
        rooms=rooms,
        user_name=session["user"]["name"],
    )


@app.route("/rooms/<int:room_id>", methods=["GET", "POST"])
@login_required
def room(room_id):
    chat_room = db.session.get(Room, room_id)

    if chat_room is None:
        abort(404)

    if request.method == "POST":
        content = request.form.get("content", "").strip()

        if content:
            # Keep individual messages reasonably bounded.
            content = content[:4000]

            message = Message(
                room_id=chat_room.id,
                author=session["user"]["name"],
                content=content,
            )
            db.session.add(message)
            db.session.commit()

        # POST/Redirect/GET prevents duplicate messages when the browser refreshes.
        return redirect(url_for("room", room_id=chat_room.id))

    newest_messages = (
        Message.query
        .filter_by(room_id=chat_room.id)
        .order_by(Message.posted_at.desc(), Message.id.desc())
        .limit(50)
        .all()
    )

    messages = list(reversed(newest_messages))

    return render_template(
        "room.html",
        room=chat_room,
        messages=messages,
        user_name=session["user"]["name"],
    )


@app.errorhandler(404)
def not_found(error):
    return render_template(
        "404.html",
        user_name=(session.get("user") or {}).get("name", "Guest"),
    ), 404


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000, debug=True)
