# eventlet.monkey_patch() MUST run before anything else is imported - including
# mysql.connector - so every socket/thread those libraries open underneath is
# the non-blocking eventlet version. Importing it late is a common source of
# WebSocket connections that mysteriously hang.
import eventlet
eventlet.monkey_patch()

import os
import uuid
from datetime import timedelta, datetime
from flask import Flask, request, jsonify, g
from flask_cors import CORS
from flask_bcrypt import Bcrypt
from flask_jwt_extended import (
    JWTManager, create_access_token, create_refresh_token,
    jwt_required, get_jwt_identity, get_jwt, decode_token,
)
from flask_socketio import SocketIO, join_room
import mysql.connector
from werkzeug.utils import secure_filename
from functools import wraps
from config import get_db

app = Flask(__name__)

# ------------------------------------------------------------------
# JWT config
# ------------------------------------------------------------------
app.config["JWT_SECRET_KEY"] = "change-this-to-something-random-in-production"
app.config["JWT_ACCESS_TOKEN_EXPIRES"] = timedelta(minutes=15)
app.config["JWT_REFRESH_TOKEN_EXPIRES"] = timedelta(days=7)
jwt = JWTManager(app)


@jwt.expired_token_loader
def handle_expired_token(jwt_header, jwt_payload):
    # The frontend's Axios interceptor only tries to refresh when it sees this
    # exact code. Other 401s (wrong password on login, wrong current password
    # when changing it) are real answers and must NOT trigger a token refresh.
    return jsonify({"error": "Token expired", "code": "token_expired"}), 401

# the frontend sends the token in an Authorization header now, not a cookie,
# so no credentials/cookies need to cross origins anymore - but the browser's
# CORS preflight does need to be told that an Authorization header is allowed
CORS(app, origins=["http://localhost:5173"], allow_headers=["Content-Type", "Authorization"])
bcrypt = Bcrypt(app)

# ------------------------------------------------------------------
# SocketIO - real-time notifications
# ------------------------------------------------------------------
socketio = SocketIO(app, cors_allowed_origins=["http://localhost:5173"], async_mode="eventlet")

# sid -> {"user_id": str, "role": str}, for the current process only. Good
# enough for one dev server; a multi-process deployment would need a shared
# store (e.g. Redis) instead of this plain dict.
connected_users = {}


@socketio.on("connect")
def on_connect(auth):
    """
    Authenticates the socket using the SAME access token already used for
    REST calls (sent as `{ auth: { token } }` when the client opens the
    connection) and joins rooms based on what the token actually says -
    not based on anything the client claims in a message after connecting.
    A client-sent 'join' event with a self-reported role would let anyone
    claim role: 'admin' and silently read other people's order volume.
    """
    token = (auth or {}).get("token")
    if not token:
        return False  # reject the connection - no anonymous sockets

    try:
        decoded = decode_token(token)
    except Exception:
        return False  # missing/expired/invalid token - reject

    user_id = decoded["sub"]
    role = decoded.get("role")
    connected_users[request.sid] = {"user_id": user_id, "role": role}

    join_room(f"user_{user_id}")
    if role == "admin":
        join_room("admins")

    print(f"Client connected: {request.sid} (user {user_id}, role {role})")


@socketio.on("disconnect")
def on_disconnect():
    info = connected_users.pop(request.sid, None)
    print(f"Client disconnected: {request.sid} (was user {info['user_id']})" if info else f"Client disconnected: {request.sid}")

# ------------------------------------------------------------------
# Image upload config
# ------------------------------------------------------------------
UPLOAD_FOLDER = os.path.join(app.root_path, "static", "uploads")
ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "webp"}
MAX_FILE_SIZE = 2 * 1024 * 1024  # 2 MB

os.makedirs(UPLOAD_FOLDER, exist_ok=True)
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER
app.config["MAX_CONTENT_LENGTH"] = MAX_FILE_SIZE


def allowed_file(filename):
    ext = filename.rsplit(".", 1)[-1].lower()
    return "." in filename and ext in ALLOWED_EXTENSIONS


def delete_uploaded_file(image_url):
    """
    Deletes a file previously saved by /api/upload, given its stored
    relative path (e.g. "/static/uploads/abc123.jpg"). Safe to call with
    None or a path that isn't one of our own uploads (e.g. a leftover
    external URL) - it just does nothing in that case.
    """
    if not image_url or not image_url.startswith("/static/uploads/"):
        return
    filename = image_url.rsplit("/", 1)[-1]
    filepath = os.path.join(UPLOAD_FOLDER, secure_filename(filename))
    if os.path.exists(filepath):
        try:
            os.remove(filepath)
        except OSError:
            pass  # don't let a filesystem hiccup break the request


# ------------------------------------------------------------------
# Helpers / decorators
# ------------------------------------------------------------------
def login_required(f):
    """Requires a valid access token. Exposes g.user_id / g.role for the route."""
    @wraps(f)
    @jwt_required()
    def wrapper(*args, **kwargs):
        g.user_id = get_jwt_identity()
        g.role = get_jwt().get("role")
        return f(*args, **kwargs)
    return wrapper


def admin_required(f):
    """Requires a valid access token AND an admin role claim."""
    @wraps(f)
    @jwt_required()
    def wrapper(*args, **kwargs):
        claims = get_jwt()
        if claims.get("role") != "admin":
            return jsonify({"error": "Admin access only"}), 403
        g.user_id = get_jwt_identity()
        g.role = claims.get("role")
        return f(*args, **kwargs)
    return wrapper


# ------------------------------------------------------------------
# Auth routes
# ------------------------------------------------------------------
@app.route("/api/register", methods=["POST"])
def register():
    data = request.get_json() or {}
    name = data.get("name", "").strip()
    email = data.get("email", "").strip().lower()
    password = data.get("password", "")

    if not name or not email or not password:
        return jsonify({"error": "name, email and password are required"}), 400
    if len(password) < 6:
        return jsonify({"error": "Password must be at least 6 characters"}), 400

    hashed = bcrypt.generate_password_hash(password).decode("utf-8")

    db = get_db()
    cur = db.cursor(dictionary=True)
    try:
        cur.execute("SELECT id FROM users WHERE email = %s", (email,))
        if cur.fetchone():
            return jsonify({"error": "Email already registered"}), 409

        cur.execute(
            "INSERT INTO users (name, email, password, role) VALUES (%s, %s, %s, 'customer')",
            (name, email, hashed),
        )
        db.commit()
        user_id = cur.lastrowid

        access_token = create_access_token(
            identity=str(user_id),
            additional_claims={"role": "customer", "name": name},
        )
        refresh_token = create_refresh_token(identity=str(user_id))

        return jsonify({
            "access_token": access_token,
            "refresh_token": refresh_token,
            "user": {"id": user_id, "name": name, "email": email, "role": "customer", "avatar_url": None},
        }), 201
    finally:
        cur.close()
        db.close()


@app.route("/api/login", methods=["POST"])
def login():
    data = request.get_json() or {}
    email = data.get("email", "").strip().lower()
    password = data.get("password", "")

    db = get_db()
    cur = db.cursor(dictionary=True)
    try:
        cur.execute("SELECT * FROM users WHERE email = %s", (email,))
        user = cur.fetchone()

        if not user or not bcrypt.check_password_hash(user["password"], password):
            return jsonify({"error": "Invalid email or password"}), 401

        access_token = create_access_token(
            identity=str(user["id"]),
            additional_claims={"role": user["role"], "name": user["name"]},
        )
        refresh_token = create_refresh_token(identity=str(user["id"]))

        return jsonify({
            "access_token": access_token,
            "refresh_token": refresh_token,
            "user": {
                "id": user["id"], "name": user["name"],
                "email": user["email"], "role": user["role"],
                "avatar_url": user.get("avatar_url"),
            },
        })
    finally:
        cur.close()
        db.close()


@app.route("/api/refresh", methods=["POST"])
@jwt_required(refresh=True)
def refresh():
    user_id = get_jwt_identity()

    db = get_db()
    cur = db.cursor(dictionary=True)
    try:
        cur.execute("SELECT * FROM users WHERE id = %s", (user_id,))
        user = cur.fetchone()
        if not user:
            return jsonify({"error": "User no longer exists"}), 401

        new_token = create_access_token(
            identity=user_id,
            additional_claims={"role": user["role"], "name": user["name"]},
        )
        return jsonify({"access_token": new_token})
    finally:
        cur.close()
        db.close()


@app.route("/api/logout", methods=["GET"])
def logout():
    # JWTs are stateless - there's nothing to invalidate server-side for this
    # app's scope. The frontend simply deletes both tokens from localStorage.
    return jsonify({"message": "Logged out"})


def profile_payload(row):
    """Shapes a users row into the profile JSON the frontend expects."""
    created = row.get("created_at")
    return {
        "id": row["id"],
        "name": row["name"],
        "email": row["email"],
        "role": row["role"],
        "avatar_url": row.get("avatar_url"),  # None -> JSON null -> frontend shows initials
        "created_at": created.strftime("%Y-%m-%d") if created else None,
    }


@app.route("/api/me", methods=["GET"])
@jwt_required()
def me():
    user_id = get_jwt_identity()

    db = get_db()
    cur = db.cursor(dictionary=True)
    try:
        cur.execute(
            "SELECT id, name, email, role, avatar_url, created_at FROM users WHERE id = %s",
            (user_id,),
        )
        user = cur.fetchone()
        if not user:
            return jsonify({"error": "User not found"}), 404
        return jsonify(profile_payload(user))
    finally:
        cur.close()
        db.close()


@app.route("/api/me", methods=["PUT"])
@jwt_required()
def update_profile():
    user_id = get_jwt_identity()
    data = request.get_json() or {}
    name = (data.get("name") or "").strip()
    # lowercased to match register/login, which both look emails up in lowercase -
    # otherwise saving "Ravi@Example.com" here would make login fail afterwards
    email = (data.get("email") or "").strip().lower()

    if not name or not email:
        return jsonify({"error": "Name and email required"}), 400
    if "@" not in email or "." not in email.rsplit("@", 1)[-1]:
        return jsonify({"error": "Enter a valid email address"}), 400

    db = get_db()
    cur = db.cursor(dictionary=True)
    try:
        cur.execute(
            "UPDATE users SET name = %s, email = %s WHERE id = %s",
            (name, email, user_id),
        )
        db.commit()
        return jsonify({"message": "Profile updated", "name": name, "email": email}), 200
    except mysql.connector.IntegrityError:
        db.rollback()
        return jsonify({"error": "Email already in use"}), 409
    finally:
        cur.close()
        db.close()


@app.route("/api/me/password", methods=["PUT"])
@jwt_required()
def change_password():
    user_id = get_jwt_identity()
    data = request.get_json() or {}
    current = data.get("current_password") or ""
    new_pass = data.get("new_password") or ""
    confirm = data.get("confirm_password") or ""

    if not current:
        return jsonify({"error": "Current password is required"}), 400
    if new_pass != confirm:
        return jsonify({"error": "Passwords do not match"}), 400
    if len(new_pass) < 6:
        return jsonify({"error": "Min 6 characters"}), 400

    db = get_db()
    cur = db.cursor(dictionary=True)
    try:
        cur.execute("SELECT password FROM users WHERE id = %s", (user_id,))
        user = cur.fetchone()
        if not user:
            return jsonify({"error": "User not found"}), 404

        if not bcrypt.check_password_hash(user["password"], current):
            return jsonify({"error": "Current password incorrect"}), 401

        hashed = bcrypt.generate_password_hash(new_pass).decode("utf-8")
        cur.execute("UPDATE users SET password = %s WHERE id = %s", (hashed, user_id))
        db.commit()
        return jsonify({"message": "Password changed"}), 200
    finally:
        cur.close()
        db.close()


@app.route("/api/me/avatar", methods=["PUT"])
@jwt_required()
def update_avatar():
    """Uploads a new profile picture and saves it on the user in one step."""
    user_id = get_jwt_identity()

    if "image" not in request.files:
        return jsonify({"error": "No file provided"}), 400
    file = request.files["image"]
    if file.filename == "":
        return jsonify({"error": "No file selected"}), 400
    if not allowed_file(file.filename):
        return jsonify({"error": "Invalid file type. Allowed: png, jpg, jpeg, webp"}), 400

    db = get_db()
    cur = db.cursor(dictionary=True)
    new_url = None
    try:
        cur.execute("SELECT avatar_url FROM users WHERE id = %s", (user_id,))
        user = cur.fetchone()
        if not user:
            return jsonify({"error": "User not found"}), 404
        old_url = user["avatar_url"]

        ext = file.filename.rsplit(".", 1)[-1].lower()
        safe_name = secure_filename(f"{uuid.uuid4().hex}.{ext}")
        file.save(os.path.join(app.config["UPLOAD_FOLDER"], safe_name))
        new_url = f"/static/uploads/{safe_name}"

        cur.execute("UPDATE users SET avatar_url = %s WHERE id = %s", (new_url, user_id))
        db.commit()

        # only after the DB points at the new file is it safe to remove the old one
        delete_uploaded_file(old_url)
        return jsonify({"avatar_url": new_url}), 200
    except Exception as e:
        db.rollback()
        delete_uploaded_file(new_url)  # don't leave an orphaned file behind
        return jsonify({"error": "Could not update profile picture", "detail": str(e)}), 500
    finally:
        cur.close()
        db.close()


@app.route("/api/me/stats", methods=["GET"])
@jwt_required()
def my_account_stats():
    """Total orders placed and total spent, for the profile page's activity summary."""
    user_id = get_jwt_identity()

    db = get_db()
    cur = db.cursor(dictionary=True)
    try:
        cur.execute("""
            SELECT
                COUNT(*) AS total_orders,
                COALESCE(SUM(CASE WHEN status != 'Cancelled' THEN total_amount ELSE 0 END), 0) AS total_spent
            FROM orders
            WHERE user_id = %s
        """, (user_id,))
        row = cur.fetchone()
        return jsonify({
            "total_orders": row["total_orders"],
            "total_spent": float(row["total_spent"]),
        })
    finally:
        cur.close()
        db.close()


@app.route("/api/me", methods=["DELETE"])
@jwt_required()
def delete_account():
    """
    Permanently deletes the logged-in user's own account.

    Design choice: this is a hard delete, not an anonymize-and-keep-orders
    approach some real stores use for accounting/legal reasons. Order
    history is deleted along with the account. If you need to retain order
    records for business reasons, replace this with an "anonymize" step
    instead (blank out name/email, keep the orders rows).
    """
    user_id = get_jwt_identity()

    db = get_db()
    cur = db.cursor(dictionary=True)
    try:
        cur.execute("SELECT avatar_url FROM users WHERE id = %s", (user_id,))
        user = cur.fetchone()
        if not user:
            return jsonify({"error": "User not found"}), 404

        # orders.user_id has no ON DELETE CASCADE in the schema, so orders (and
        # their order_items, which DO cascade from orders) must be removed
        # explicitly before the user row itself. ratings and wishlist already
        # cascade from users, so deleting the user row cleans those up.
        cur.execute("DELETE FROM orders WHERE user_id = %s", (user_id,))
        cur.execute("DELETE FROM users WHERE id = %s", (user_id,))
        db.commit()

        delete_uploaded_file(user["avatar_url"])
        return jsonify({"message": "Account deleted"}), 200
    except Exception as e:
        db.rollback()
        return jsonify({"error": "Could not delete account", "detail": str(e)}), 500
    finally:
        cur.close()
        db.close()


# ------------------------------------------------------------------
# Category routes
# ------------------------------------------------------------------
@app.route("/api/categories", methods=["GET"])
def get_categories():
    db = get_db()
    cur = db.cursor(dictionary=True)
    try:
        cur.execute("SELECT * FROM categories ORDER BY name")
        return jsonify(cur.fetchall())
    finally:
        cur.close()
        db.close()


# ------------------------------------------------------------------
# Image upload (admin only)
# ------------------------------------------------------------------
@app.route("/api/upload", methods=["POST"])
@admin_required
def upload_image():
    if "image" not in request.files:
        return jsonify({"error": "No file provided"}), 400

    file = request.files["image"]
    if file.filename == "":
        return jsonify({"error": "No file selected"}), 400

    if not allowed_file(file.filename):
        return jsonify({"error": "Invalid file type. Allowed: png, jpg, jpeg, webp"}), 400

    # Generate a unique filename so uploads never overwrite each other
    ext = file.filename.rsplit(".", 1)[-1].lower()
    unique_name = f"{uuid.uuid4().hex}.{ext}"
    safe_name = secure_filename(unique_name)
    filepath = os.path.join(app.config["UPLOAD_FOLDER"], safe_name)
    file.save(filepath)

    # relative path only - the file lives inside static/, so Flask serves it
    # automatically at http://localhost:5000/static/uploads/<filename>
    image_url = f"/static/uploads/{safe_name}"
    return jsonify({"image_url": image_url}), 201


# ------------------------------------------------------------------
# Product routes (public)
# ------------------------------------------------------------------
@app.route("/api/products", methods=["GET"])
def get_products():
    category = request.args.get("category")
    search = request.args.get("search")
    sort = request.args.get("sort")
    page = max(int(request.args.get("page", 1)), 1)
    limit = max(int(request.args.get("limit", 8)), 1)
    offset = (page - 1) * limit

    where_clause = " WHERE 1=1"
    params = []

    if category:
        where_clause += " AND p.category_id = %s"
        params.append(category)

    if search:
        where_clause += " AND (p.name LIKE %s OR p.description LIKE %s)"
        like = f"%{search}%"
        params.extend([like, like])

    sort_map = {
        "price_asc": " ORDER BY p.price ASC",
        "price_desc": " ORDER BY p.price DESC",
        "newest": " ORDER BY p.created_at DESC",
    }
    order_clause = sort_map.get(sort, " ORDER BY p.id ASC")

    db = get_db()
    cur = db.cursor(dictionary=True)
    try:
        # count total matching products first, so the frontend knows how many pages exist
        count_query = "SELECT COUNT(*) AS total FROM products p" + where_clause
        cur.execute(count_query, params)
        total = cur.fetchone()["total"]

        query = """
            SELECT p.*, c.name AS category_name,
                   ROUND(AVG(r.rating), 1) AS avg_rating,
                   COUNT(DISTINCT r.id) AS rating_count
            FROM products p
            LEFT JOIN categories c ON p.category_id = c.id
            LEFT JOIN ratings r ON r.product_id = p.id
        """ + where_clause + " GROUP BY p.id" + order_clause + " LIMIT %s OFFSET %s"

        cur.execute(query, params + [limit, offset])
        products = cur.fetchall()

        return jsonify({
            "products": products,
            "total": total,
            "page": page,
            "limit": limit,
            "total_pages": max(1, -(-total // limit)),  # ceiling division
        })
    finally:
        cur.close()
        db.close()


@app.route("/api/products/<int:product_id>", methods=["GET"])
def get_product(product_id):
    db = get_db()
    cur = db.cursor(dictionary=True)
    try:
        cur.execute("""
            SELECT p.*, c.name AS category_name,
                   ROUND(AVG(r.rating), 1) AS avg_rating,
                   COUNT(r.id) AS rating_count
            FROM products p
            LEFT JOIN categories c ON p.category_id = c.id
            LEFT JOIN ratings r ON r.product_id = p.id
            WHERE p.id = %s
            GROUP BY p.id
        """, (product_id,))
        product = cur.fetchone()
        if not product:
            return jsonify({"error": "Product not found"}), 404

        cur.execute(
            "SELECT id, image_url FROM product_images WHERE product_id = %s ORDER BY id",
            (product_id,),
        )
        product["images"] = cur.fetchall()

        return jsonify(product)
    finally:
        cur.close()
        db.close()


# ------------------------------------------------------------------
# Product gallery routes (admin only)
# ------------------------------------------------------------------
@app.route("/api/products/<int:product_id>/images", methods=["POST"])
@admin_required
def add_product_image(product_id):
    if "image" not in request.files:
        return jsonify({"error": "No file provided"}), 400

    file = request.files["image"]
    if file.filename == "":
        return jsonify({"error": "No file selected"}), 400
    if not allowed_file(file.filename):
        return jsonify({"error": "Invalid file type. Allowed: png, jpg, jpeg, webp"}), 400

    db = get_db()
    cur = db.cursor(dictionary=True)
    try:
        cur.execute("SELECT id FROM products WHERE id = %s", (product_id,))
        if not cur.fetchone():
            return jsonify({"error": "Product not found"}), 404

        ext = file.filename.rsplit(".", 1)[-1].lower()
        unique_name = f"{uuid.uuid4().hex}.{ext}"
        safe_name = secure_filename(unique_name)
        file.save(os.path.join(app.config["UPLOAD_FOLDER"], safe_name))
        image_url = f"/static/uploads/{safe_name}"

        cur.execute(
            "INSERT INTO product_images (product_id, image_url) VALUES (%s, %s)",
            (product_id, image_url),
        )
        db.commit()
        return jsonify({"id": cur.lastrowid, "image_url": image_url}), 201
    finally:
        cur.close()
        db.close()


@app.route("/api/products/<int:product_id>/images/<int:image_id>", methods=["DELETE"])
@admin_required
def delete_product_image(product_id, image_id):
    db = get_db()
    cur = db.cursor(dictionary=True)
    try:
        cur.execute(
            "SELECT image_url FROM product_images WHERE id = %s AND product_id = %s",
            (image_id, product_id),
        )
        image = cur.fetchone()
        if not image:
            return jsonify({"error": "Image not found"}), 404

        cur.execute("DELETE FROM product_images WHERE id = %s", (image_id,))
        db.commit()

        delete_uploaded_file(image["image_url"])
        return jsonify({"message": "Image deleted"})
    finally:
        cur.close()
        db.close()


# ------------------------------------------------------------------
# Rating routes
# ------------------------------------------------------------------
@app.route("/api/products/<int:product_id>/ratings", methods=["GET"])
def get_product_ratings(product_id):
    db = get_db()
    cur = db.cursor(dictionary=True)
    try:
        cur.execute("""
            SELECT r.*, u.name AS customer_name
            FROM ratings r
            JOIN users u ON r.user_id = u.id
            WHERE r.product_id = %s
            ORDER BY r.created_at DESC
        """, (product_id,))
        return jsonify(cur.fetchall())
    finally:
        cur.close()
        db.close()


@app.route("/api/products/<int:product_id>/ratings", methods=["POST"])
@login_required
def rate_product(product_id):
    data = request.get_json() or {}
    rating = data.get("rating")
    review = data.get("review", "")

    if not isinstance(rating, int) or not (1 <= rating <= 5):
        return jsonify({"error": "Rating must be an integer from 1 to 5"}), 400

    db = get_db()
    cur = db.cursor(dictionary=True)
    try:
        # only customers who actually bought this product may rate it
        cur.execute("""
            SELECT 1
            FROM order_items oi
            JOIN orders o ON oi.order_id = o.id
            WHERE o.user_id = %s AND oi.product_id = %s
            LIMIT 1
        """, (g.user_id, product_id))
        if not cur.fetchone():
            return jsonify({"error": "You can only rate products you have purchased"}), 403

        # one rating per user per product - insert or update
        cur.execute("""
            INSERT INTO ratings (user_id, product_id, rating, review)
            VALUES (%s, %s, %s, %s)
            ON DUPLICATE KEY UPDATE rating = VALUES(rating), review = VALUES(review)
        """, (g.user_id, product_id, rating, review))
        db.commit()
        return jsonify({"message": "Rating saved"}), 201
    finally:
        cur.close()
        db.close()


# ------------------------------------------------------------------
# Wishlist routes (customer)
# ------------------------------------------------------------------
@app.route("/api/wishlist", methods=["GET"])
@login_required
def get_wishlist():
    db = get_db()
    cur = db.cursor(dictionary=True)
    try:
        cur.execute("""
            SELECT p.*, c.name AS category_name, w.added_at,
                   ROUND(AVG(r.rating), 1) AS avg_rating,
                   COUNT(DISTINCT r.id) AS rating_count
            FROM wishlist w
            JOIN products p ON w.product_id = p.id
            LEFT JOIN categories c ON p.category_id = c.id
            LEFT JOIN ratings r ON r.product_id = p.id
            WHERE w.user_id = %s
            GROUP BY p.id, w.added_at
            ORDER BY w.added_at DESC
        """, (g.user_id,))
        return jsonify(cur.fetchall())
    finally:
        cur.close()
        db.close()


@app.route("/api/wishlist", methods=["POST"])
@login_required
def add_to_wishlist():
    data = request.get_json() or {}
    product_id = data.get("product_id")
    if not product_id:
        return jsonify({"error": "product_id is required"}), 400

    db = get_db()
    cur = db.cursor(dictionary=True)
    try:
        cur.execute("""
            INSERT IGNORE INTO wishlist (user_id, product_id) VALUES (%s, %s)
        """, (g.user_id, product_id))
        db.commit()
        return jsonify({"message": "Added to wishlist"}), 201
    finally:
        cur.close()
        db.close()


@app.route("/api/wishlist/<int:product_id>", methods=["DELETE"])
@login_required
def remove_from_wishlist(product_id):
    db = get_db()
    cur = db.cursor(dictionary=True)
    try:
        cur.execute(
            "DELETE FROM wishlist WHERE user_id = %s AND product_id = %s",
            (g.user_id, product_id),
        )
        db.commit()
        return jsonify({"message": "Removed from wishlist"})
    finally:
        cur.close()
        db.close()


# ------------------------------------------------------------------
# Product routes (admin only)
# ------------------------------------------------------------------
@app.route("/api/products", methods=["POST"])
@admin_required
def create_product():
    data = request.get_json() or {}
    required = ["name", "price", "stock"]
    if any(f not in data or data[f] in ("", None) for f in required):
        return jsonify({"error": "name, price and stock are required"}), 400

    db = get_db()
    cur = db.cursor(dictionary=True)
    try:
        cur.execute("""
            INSERT INTO products (name, description, price, stock, category_id, image_url)
            VALUES (%s, %s, %s, %s, %s, %s)
        """, (
            data["name"], data.get("description", ""), data["price"],
            data["stock"], data.get("category_id"), data.get("image_url", ""),
        ))
        db.commit()
        return jsonify({"id": cur.lastrowid, "message": "Product created"}), 201
    finally:
        cur.close()
        db.close()


@app.route("/api/products/<int:product_id>", methods=["PUT"])
@admin_required
def update_product(product_id):
    data = request.get_json() or {}
    db = get_db()
    cur = db.cursor(dictionary=True)
    try:
        cur.execute("SELECT * FROM products WHERE id = %s", (product_id,))
        existing = cur.fetchone()
        if not existing:
            return jsonify({"error": "Product not found"}), 404

        new_image_url = data.get("image_url", "")

        cur.execute("""
            UPDATE products
            SET name=%s, description=%s, price=%s, stock=%s,
                category_id=%s, image_url=%s
            WHERE id=%s
        """, (
            data.get("name"), data.get("description", ""), data.get("price"),
            data.get("stock"), data.get("category_id"), new_image_url,
            product_id,
        ))
        db.commit()

        # the cover image was replaced with a different file - remove the old one from disk
        old_image_url = existing["image_url"]
        if old_image_url and old_image_url != new_image_url:
            delete_uploaded_file(old_image_url)

        return jsonify({"message": "Product updated"})
    finally:
        cur.close()
        db.close()


@app.route("/api/products/<int:product_id>", methods=["DELETE"])
@admin_required
def delete_product(product_id):
    db = get_db()
    cur = db.cursor(dictionary=True)
    try:
        cur.execute("SELECT image_url FROM products WHERE id = %s", (product_id,))
        product = cur.fetchone()
        if not product:
            return jsonify({"error": "Product not found"}), 404

        cur.execute("SELECT image_url FROM product_images WHERE product_id = %s", (product_id,))
        gallery_images = cur.fetchall()

        # ON DELETE CASCADE removes the product_images rows automatically
        cur.execute("DELETE FROM products WHERE id = %s", (product_id,))
        db.commit()

        # clean up every file that belonged only to this product
        delete_uploaded_file(product["image_url"])
        for img in gallery_images:
            delete_uploaded_file(img["image_url"])

        return jsonify({"message": "Product deleted"})
    finally:
        cur.close()
        db.close()


# ------------------------------------------------------------------
# Order routes (customer)
# ------------------------------------------------------------------
@app.route("/api/orders", methods=["POST"])
@login_required
def create_order():
    data = request.get_json() or {}
    items = data.get("items", [])
    address = data.get("address", "").strip()
    coupon_code = (data.get("coupon_code") or "").strip().upper()

    if not items:
        return jsonify({"error": "Cart is empty"}), 400
    if not address:
        return jsonify({"error": "Delivery address is required"}), 400

    db = get_db()
    cur = db.cursor(dictionary=True)
    try:
        # --- Step 1: validate stock for every item BEFORE changing anything ---
        product_rows = {}
        subtotal = 0
        for item in items:
            product_id = item.get("product_id")
            quantity = int(item.get("quantity", 0))
            if quantity <= 0:
                return jsonify({"error": "Invalid quantity"}), 400

            cur.execute("SELECT * FROM products WHERE id = %s", (product_id,))
            product = cur.fetchone()
            if not product:
                return jsonify({"error": f"Product {product_id} does not exist"}), 400
            if product["stock"] < quantity:
                return jsonify({
                    "error": f"'{product['name']}' has only {product['stock']} in stock "
                             f"(requested {quantity})"
                }), 400

            product_rows[product_id] = {"product": product, "quantity": quantity}
            subtotal += float(product["price"]) * quantity

        # --- Step 1b: validate coupon (if provided) ---
        discount_amount = 0.0
        applied_code = None
        if coupon_code:
            coupon = get_valid_coupon(cur, coupon_code)
            if not coupon:
                return jsonify({"error": "Invalid or expired coupon code"}), 400
            discount_amount = round(subtotal * coupon["discount_percent"] / 100, 2)
            applied_code = coupon["code"]

        total = round(subtotal - discount_amount, 2)

        # --- Step 2: everything validated -> create order, items, reduce stock ---
        cur.execute(
            "INSERT INTO orders (user_id, total_amount, address, status, coupon_code, discount_amount) "
            "VALUES (%s, %s, %s, 'Pending', %s, %s)",
            (g.user_id, total, address, applied_code, discount_amount),
        )
        order_id = cur.lastrowid

        for product_id, entry in product_rows.items():
            product = entry["product"]
            quantity = entry["quantity"]

            cur.execute("""
                INSERT INTO order_items (order_id, product_id, quantity, unit_price)
                VALUES (%s, %s, %s, %s)
            """, (order_id, product_id, quantity, product["price"]))

            cur.execute(
                "UPDATE products SET stock = stock - %s WHERE id = %s",
                (quantity, product_id),
            )

        db.commit()

        # --- Step 3: notify every admin, live, that a new order came in ---
        # One INSERT per admin (not a single bulk INSERT...SELECT) so each
        # admin gets their OWN row with a real id back immediately - letting
        # the frontend mark it read/delete it right away, with no need to
        # wait for a page refresh to reconcile a placeholder id.
        customer_name = get_jwt().get("name", "A customer")
        message = f"New order #{order_id} placed by {customer_name} — ${total:.2f}"

        cur.execute("SELECT id FROM users WHERE role = 'admin'")
        admin_ids = [row["id"] for row in cur.fetchall()]

        notifications = []
        for admin_id in admin_ids:
            cur.execute(
                "INSERT INTO notifications (user_id, message, type) VALUES (%s, %s, 'order')",
                (admin_id, message),
            )
            notifications.append({"admin_id": admin_id, "notification_id": cur.lastrowid})
        db.commit()

        created_at = datetime.now().isoformat()
        for n in notifications:
            socketio.emit("new_notification", {
                "id": n["notification_id"],
                "message": message,
                "type": "order",
                "order_id": order_id,
                "is_read": False,
                "created_at": created_at,
            }, room=f"user_{n['admin_id']}")

        return jsonify({
            "order_id": order_id,
            "subtotal": subtotal,
            "discount_amount": discount_amount,
            "total_amount": total,
            "status": "Pending",
            "message": "Order placed successfully",
        }), 201

    except Exception as e:
        db.rollback()
        return jsonify({"error": "Could not place order", "detail": str(e)}), 500
    finally:
        cur.close()
        db.close()


@app.route("/api/orders/my", methods=["GET"])
@login_required
def my_orders():
    db = get_db()
    cur = db.cursor(dictionary=True)
    try:
        cur.execute("""
            SELECT * FROM orders WHERE user_id = %s ORDER BY ordered_at DESC
        """, (g.user_id,))
        orders = cur.fetchall()

        for order in orders:
            cur.execute("""
                SELECT oi.*, p.name AS product_name, p.image_url
                FROM order_items oi
                JOIN products p ON oi.product_id = p.id
                WHERE oi.order_id = %s
            """, (order["id"],))
            order["items"] = cur.fetchall()

        return jsonify(orders)
    finally:
        cur.close()
        db.close()


# ------------------------------------------------------------------
# Order routes (admin only)
# ------------------------------------------------------------------
@app.route("/api/orders", methods=["GET"])
@admin_required
def all_orders():
    page = max(int(request.args.get("page", 1)), 1)
    limit = max(int(request.args.get("limit", 10)), 1)
    offset = (page - 1) * limit

    db = get_db()
    cur = db.cursor(dictionary=True)
    try:
        cur.execute("SELECT COUNT(*) AS total FROM orders")
        total = cur.fetchone()["total"]

        cur.execute("""
            SELECT o.*, u.name AS customer_name, u.email AS customer_email
            FROM orders o
            JOIN users u ON o.user_id = u.id
            ORDER BY o.ordered_at DESC
            LIMIT %s OFFSET %s
        """, (limit, offset))
        orders = cur.fetchall()

        for order in orders:
            cur.execute("""
                SELECT oi.*, p.name AS product_name
                FROM order_items oi
                JOIN products p ON oi.product_id = p.id
                WHERE oi.order_id = %s
            """, (order["id"],))
            order["items"] = cur.fetchall()

        return jsonify({
            "orders": orders,
            "total": total,
            "page": page,
            "limit": limit,
            "total_pages": max(1, -(-total // limit)),
        })
    finally:
        cur.close()
        db.close()


@app.route("/api/orders/<int:order_id>/status", methods=["PUT"])
@admin_required
def update_order_status(order_id):
    data = request.get_json() or {}
    status = data.get("status")
    valid = ["Pending", "Confirmed", "Shipped", "Delivered", "Cancelled"]
    if status not in valid:
        return jsonify({"error": f"Status must be one of {valid}"}), 400

    db = get_db()
    cur = db.cursor(dictionary=True)
    try:
        cur.execute("UPDATE orders SET status = %s WHERE id = %s", (status, order_id))
        db.commit()
        if cur.rowcount == 0:
            return jsonify({"error": "Order not found"}), 404
        return jsonify({"message": "Order status updated", "status": status})
    finally:
        cur.close()
        db.close()


@app.errorhandler(413)
def file_too_large(e):
    return jsonify({"error": "Image is too large (max 2 MB)"}), 413


# ------------------------------------------------------------------
# Coupon routes
# ------------------------------------------------------------------
def get_valid_coupon(cur, code):
    """Returns the coupon row if it exists, is active, and hasn't expired; else None."""
    cur.execute("""
        SELECT * FROM coupons
        WHERE code = %s AND active = TRUE
          AND (expires_at IS NULL OR expires_at >= CURDATE())
    """, (code,))
    return cur.fetchone()


@app.route("/api/coupons/validate", methods=["POST"])
@login_required
def validate_coupon():
    data = request.get_json() or {}
    code = data.get("code", "").strip().upper()
    subtotal = float(data.get("subtotal", 0))

    if not code:
        return jsonify({"error": "Enter a coupon code"}), 400

    db = get_db()
    cur = db.cursor(dictionary=True)
    try:
        coupon = get_valid_coupon(cur, code)
        if not coupon:
            return jsonify({"error": "Invalid or expired coupon code"}), 404

        discount_amount = round(subtotal * coupon["discount_percent"] / 100, 2)
        return jsonify({
            "code": coupon["code"],
            "discount_percent": coupon["discount_percent"],
            "discount_amount": discount_amount,
        })
    finally:
        cur.close()
        db.close()


@app.route("/api/coupons", methods=["GET"])
@admin_required
def list_coupons():
    db = get_db()
    cur = db.cursor(dictionary=True)
    try:
        cur.execute("SELECT * FROM coupons ORDER BY created_at DESC")
        return jsonify(cur.fetchall())
    finally:
        cur.close()
        db.close()


@app.route("/api/coupons", methods=["POST"])
@admin_required
def create_coupon():
    data = request.get_json() or {}
    code = data.get("code", "").strip().upper()
    discount_percent = data.get("discount_percent")
    expires_at = data.get("expires_at") or None

    if not code or not discount_percent:
        return jsonify({"error": "code and discount_percent are required"}), 400
    if not (1 <= int(discount_percent) <= 100):
        return jsonify({"error": "discount_percent must be between 1 and 100"}), 400

    db = get_db()
    cur = db.cursor(dictionary=True)
    try:
        cur.execute("SELECT id FROM coupons WHERE code = %s", (code,))
        if cur.fetchone():
            return jsonify({"error": "A coupon with that code already exists"}), 409

        cur.execute("""
            INSERT INTO coupons (code, discount_percent, active, expires_at)
            VALUES (%s, %s, TRUE, %s)
        """, (code, discount_percent, expires_at))
        db.commit()
        return jsonify({"id": cur.lastrowid, "message": "Coupon created"}), 201
    finally:
        cur.close()
        db.close()


@app.route("/api/coupons/<int:coupon_id>/toggle", methods=["PUT"])
@admin_required
def toggle_coupon(coupon_id):
    db = get_db()
    cur = db.cursor(dictionary=True)
    try:
        cur.execute("SELECT active FROM coupons WHERE id = %s", (coupon_id,))
        coupon = cur.fetchone()
        if not coupon:
            return jsonify({"error": "Coupon not found"}), 404

        new_status = not coupon["active"]
        cur.execute("UPDATE coupons SET active = %s WHERE id = %s", (new_status, coupon_id))
        db.commit()
        return jsonify({"message": "Coupon updated", "active": new_status})
    finally:
        cur.close()
        db.close()


@app.route("/api/coupons/<int:coupon_id>", methods=["DELETE"])
@admin_required
def delete_coupon(coupon_id):
    db = get_db()
    cur = db.cursor(dictionary=True)
    try:
        cur.execute("DELETE FROM coupons WHERE id = %s", (coupon_id,))
        db.commit()
        if cur.rowcount == 0:
            return jsonify({"error": "Coupon not found"}), 404
        return jsonify({"message": "Coupon deleted"})
    finally:
        cur.close()
        db.close()


# ------------------------------------------------------------------
# Admin sales summary
# ------------------------------------------------------------------
@app.route("/api/admin/stats", methods=["GET"])
@admin_required
def admin_stats():
    db = get_db()
    cur = db.cursor(dictionary=True)
    try:
        cur.execute("""
            SELECT
                COUNT(*) AS total_orders,
                COALESCE(SUM(CASE WHEN status != 'Cancelled' THEN total_amount ELSE 0 END), 0) AS total_revenue
            FROM orders
        """)
        summary = cur.fetchone()

        cur.execute("""
            SELECT
                p.id, p.name, p.image_url,
                SUM(oi.quantity) AS units_sold,
                SUM(oi.quantity * oi.unit_price) AS revenue
            FROM order_items oi
            JOIN products p ON oi.product_id = p.id
            JOIN orders o ON oi.order_id = o.id
            WHERE o.status != 'Cancelled'
            GROUP BY p.id
            ORDER BY units_sold DESC
            LIMIT 5
        """)
        top_products = cur.fetchall()

        cur.execute("SELECT COUNT(*) AS low_stock_count FROM products WHERE stock < 5")
        low_stock = cur.fetchone()

        return jsonify({
            "total_orders": summary["total_orders"],
            "total_revenue": float(summary["total_revenue"]),
            "low_stock_count": low_stock["low_stock_count"],
            "top_products": top_products,
        })
    finally:
        cur.close()
        db.close()


# ------------------------------------------------------------------
# Notification routes
# ------------------------------------------------------------------
@app.route("/api/notifications", methods=["GET"])
@login_required
def get_notifications():
    db = get_db()
    cur = db.cursor(dictionary=True)
    try:
        # capped at 50 - the dropdown only shows the latest 10 anyway, and an
        # unbounded SELECT would only get slower as notifications pile up
        cur.execute("""
            SELECT id, message, type, is_read, created_at
            FROM notifications
            WHERE user_id = %s
            ORDER BY created_at DESC
            LIMIT 50
        """, (g.user_id,))
        rows = cur.fetchall()
        for row in rows:
            row["created_at"] = row["created_at"].isoformat()
        return jsonify(rows)
    finally:
        cur.close()
        db.close()


@app.route("/api/notifications/<int:notification_id>/read", methods=["PUT"])
@login_required
def mark_notification_read(notification_id):
    db = get_db()
    cur = db.cursor(dictionary=True)
    try:
        # scoped to g.user_id so one user can never mark/see another
        # person's notification just by guessing an id
        cur.execute(
            "UPDATE notifications SET is_read = TRUE WHERE id = %s AND user_id = %s",
            (notification_id, g.user_id),
        )
        db.commit()
        if cur.rowcount == 0:
            return jsonify({"error": "Notification not found"}), 404
        return jsonify({"message": "Marked as read"})
    finally:
        cur.close()
        db.close()


@app.route("/api/notifications/read-all", methods=["PUT"])
@login_required
def mark_all_notifications_read():
    db = get_db()
    cur = db.cursor(dictionary=True)
    try:
        cur.execute("UPDATE notifications SET is_read = TRUE WHERE user_id = %s", (g.user_id,))
        db.commit()
        return jsonify({"message": "All notifications marked as read"})
    finally:
        cur.close()
        db.close()


@app.route("/api/notifications/<int:notification_id>", methods=["DELETE"])
@login_required
def delete_notification(notification_id):
    db = get_db()
    cur = db.cursor(dictionary=True)
    try:
        cur.execute(
            "DELETE FROM notifications WHERE id = %s AND user_id = %s",
            (notification_id, g.user_id),
        )
        db.commit()
        if cur.rowcount == 0:
            return jsonify({"error": "Notification not found"}), 404
        return jsonify({"message": "Notification deleted"})
    finally:
        cur.close()
        db.close()


if __name__ == "__main__":
    # use_reloader=False avoids a well-known Flask-SocketIO + eventlet quirk:
    # Werkzeug's reloader spawns a second process that re-runs this whole
    # module (monkey-patching eventlet a second time) and can leave the
    # socket server in a half-started state. Restart manually after edits.
    socketio.run(app, debug=True, port=5000, use_reloader=False)
