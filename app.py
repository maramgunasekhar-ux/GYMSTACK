from flask import Flask, render_template, request, redirect, session
import os
from dotenv import load_dotenv
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
import mysql.connector
import config
load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY")
UPLOAD_FOLDER = "static/uploads/clients"

app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER

ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "webp"}
def allowed_file(filename):
    return (
        "." in filename
        and filename.rsplit(".", 1)[1].lower()
        in ALLOWED_EXTENSIONS
    )

# Connect to MySQL
db = mysql.connector.connect(
    host=config.MYSQL_HOST,
    port=config.MYSQL_PORT,
    user=config.MYSQL_USER,
    password=config.MYSQL_PASSWORD,
    database=config.MYSQL_DATABASE,
    ssl_disabled=False
)
@app.route("/login", methods=["GET", "POST"])
def login():

    # If already logged in, go directly to Dashboard
    if "admin_id" in session:
        return redirect("/dashboard")

    if request.method == "POST":

        username = request.form.get("username", "").strip()
        password = request.form.get("password", "").strip()

        cursor = db.cursor()

        cursor.execute("""
            SELECT admin_id, password
            FROM admin
            WHERE username=%s
        """, (username,))

        admin = cursor.fetchone()

        cursor.close()

        if admin and check_password_hash(admin[1], password):

            session["admin_id"] = admin[0]
            session["username"] = username

            return redirect("/dashboard")

        return "Invalid username or password."

    return render_template("login.html")

@app.route("/logout")
def logout():

    session.clear()

    return redirect("/login")

@app.route("/")
def home():
    return render_template("home.html")
@app.route("/contact")
def contact():
    return render_template("contact.html")

@app.route("/dashboard")
def index():
    if "admin_id" not in session:
      return redirect("/login")

    cursor = db.cursor()

    # Total clients
    cursor.execute("""
        SELECT COUNT(*)
        FROM clients
    """)
    total_clients = cursor.fetchone()[0]

    # Active members
    cursor.execute("""
        SELECT COUNT(DISTINCT client_id)
        FROM memberships
        WHERE CURDATE() BETWEEN start_date AND end_date
    """)
    active_members = cursor.fetchone()[0]

    # Expiring soon (within next 7 days)
    cursor.execute("""
    SELECT COUNT(DISTINCT client_id)
    FROM memberships
    WHERE end_date BETWEEN CURDATE()
    AND DATE_ADD(CURDATE(), INTERVAL 7 DAY)
    """)
    expiring_soon = cursor.fetchone()[0]
    cursor.execute("""
    SELECT COUNT(DISTINCT client_id)
    FROM memberships
    WHERE end_date < CURDATE()
""")
    overdue_memberships = cursor.fetchone()[0]

    # Pending payments
    cursor.execute("""
    SELECT COUNT(DISTINCT client_id)
    FROM memberships
    WHERE payment_status IN ('Pending', 'Partial')
     """)
    pending_payments = cursor.fetchone()[0]

    # Total revenue
    cursor.execute("""
    SELECT COALESCE(SUM(amount), 0)
    FROM payments
""")
    total_revenue = cursor.fetchone()[0]

# Total pending amount
    cursor.execute("""
    SELECT COALESCE(SUM(
        GREATEST(
            memberships.amount -
            COALESCE(
                (
                    SELECT SUM(payments.amount)
                    FROM payments
                    WHERE payments.client_id = memberships.client_id
                ),
                0
            ),
            0
        )
    ), 0)
    FROM memberships
    WHERE memberships.payment_status IN ('Pending', 'Partial')
""")

    pending_amount = cursor.fetchone()[0]

         # Recent payments
    cursor.execute("""
        SELECT
            payments.payment_id,
            clients.name,
            payments.amount,
            payments.payment_date,
            payments.payment_method
        FROM payments
        JOIN clients
            ON payments.client_id = clients.client_id
        ORDER BY payments.payment_date DESC, payments.payment_id DESC
        LIMIT 5
    """)

    recent_payments = cursor.fetchall()
        # Recent payments count
    cursor.execute("""
        SELECT COUNT(*)
        FROM payments
    """)

    recent_payment_count = cursor.fetchone()[0]
    cursor.close()

    return render_template(
        "index.html",
        total_clients=total_clients,
        active_members=active_members,
        expiring_soon=expiring_soon,
        pending_payments=pending_payments,
        total_revenue=total_revenue,
        pending_amount=pending_amount,
        recent_payments=recent_payments,
        recent_payment_count=recent_payment_count,
        overdue_memberships=overdue_memberships,

    )


@app.route("/add-client", methods=["GET", "POST"])
def add_client():

    if request.method == "POST":

        full_name = request.form.get("full_name", "").strip()
        phone = request.form.get("phone", "").strip()
        date_of_birth = request.form.get("date_of_birth", "").strip()
        gender = request.form.get("gender", "").strip()
        joining_date = request.form.get("joining_date", "").strip()
        address = request.form.get("address", "").strip()
        emergency_contact = request.form.get("emergency_contact", "").strip()

        # Get uploaded photo
        photo = request.files.get("photo")
        photo_filename = None

        # Check required fields
        if not full_name or not phone or not joining_date:
            return "Please fill in all required fields."

        # Convert empty optional fields to NULL
        if date_of_birth == "":
            date_of_birth = None

        if gender == "":
            gender = None

        if address == "":
            address = None

        if emergency_contact == "":
            emergency_contact = None

        # Handle photo upload
        if photo and photo.filename:

            if not allowed_file(photo.filename):
                return "Invalid photo format. Please use JPG, JPEG, PNG or WEBP."

            original_name = secure_filename(photo.filename)

            extension = original_name.rsplit(".", 1)[1].lower()

            # Temporary unique filename
            import uuid

            photo_filename = (
                str(uuid.uuid4()) + "." + extension
            )

            photo.save(
                os.path.join(
                    app.config["UPLOAD_FOLDER"],
                    photo_filename
                )
            )

        cursor = db.cursor()

        query = """
            INSERT INTO clients
            (name, phone, date_of_birth, gender,
             joining_date, address, emergency_contact, photo)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        """

        values = (
            full_name,
            phone,
            date_of_birth,
            gender,
            joining_date,
            address,
            emergency_contact,
            photo_filename
        )

        cursor.execute(query, values)
        db.commit()

        cursor.close()

        return redirect("/dashboard")

    return render_template("add_client.html")

@app.route("/clients")
def clients():

    if "admin_id" not in session:
        return redirect("/login")

    search = request.args.get("search", "").strip()

    cursor = db.cursor()

    if search:

        cursor.execute("""
            SELECT
                client_id,
                name,
                phone,
                date_of_birth,
                gender,
                joining_date,
                address,
                emergency_contact,
                photo
            FROM clients
            WHERE name LIKE %s
               OR phone LIKE %s
            ORDER BY client_id DESC
        """, (
            "%" + search + "%",
            "%" + search + "%"
        ))

    else:

        cursor.execute("""
            SELECT
                client_id,
                name,
                phone,
                date_of_birth,
                gender,
                joining_date,
                address,
                emergency_contact,
                photo
            FROM clients
            ORDER BY client_id DESC
        """)

    clients = cursor.fetchall()

    cursor.close()

    return render_template(
        "clients.html",
        clients=clients,
        search=search
    )

@app.route("/client/<int:client_id>")
def client_details(client_id):

    cursor = db.cursor()

    cursor.execute("""
        SELECT client_id, name, phone, date_of_birth,
               gender, joining_date, address,
               emergency_contact, created_at, photo
        FROM clients
        WHERE client_id = %s
    """, (client_id,))

    client = cursor.fetchone()

    cursor.close()

    if client is None:
        return "Client not found", 404

    return render_template(
        "client_details.html",
        client=client
    )




@app.route("/edit-client/<int:client_id>", methods=["GET", "POST"])
def edit_client(client_id):

    cursor = db.cursor()

    # Update client when form is submitted
    if request.method == "POST":

        name = request.form.get("name", "").strip()
        phone = request.form.get("phone", "").strip()
        date_of_birth = request.form.get("date_of_birth", "").strip()
        gender = request.form.get("gender", "").strip()
        joining_date = request.form.get("joining_date", "").strip()
        address = request.form.get("address", "").strip()
        emergency_contact = request.form.get("emergency_contact", "").strip()

        # Get uploaded photo
        photo = request.files.get("photo")

        # Check required fields
        if not name or not phone or not joining_date:
            cursor.close()
            return "Please fill in all required fields."

        # Convert empty optional fields to NULL
        if date_of_birth == "":
            date_of_birth = None

        if gender == "":
            gender = None

        if address == "":
            address = None

        if emergency_contact == "":
            emergency_contact = None

        # Get current photo
        cursor.execute("""
            SELECT photo
            FROM clients
            WHERE client_id=%s
        """, (client_id,))

        current_client = cursor.fetchone()

        if current_client is None:
            cursor.close()
            return "Client not found", 404

        current_photo = current_client[0]

        # Default: keep existing photo
        photo_filename = current_photo

        # Handle new photo upload
        if photo and photo.filename:

            if not allowed_file(photo.filename):
                cursor.close()
                return "Invalid photo format. Please use JPG, JPEG, PNG or WEBP."

            original_name = secure_filename(photo.filename)

            extension = original_name.rsplit(".", 1)[1].lower()

            import uuid

            photo_filename = (
                str(uuid.uuid4()) + "." + extension
            )

            photo.save(
                os.path.join(
                    app.config["UPLOAD_FOLDER"],
                    photo_filename
                )
            )

        query = """
            UPDATE clients
            SET name=%s,
                phone=%s,
                date_of_birth=%s,
                gender=%s,
                joining_date=%s,
                address=%s,
                emergency_contact=%s,
                photo=%s
            WHERE client_id=%s
        """

        values = (
            name,
            phone,
            date_of_birth,
            gender,
            joining_date,
            address,
            emergency_contact,
            photo_filename,
            client_id
        )

        cursor.execute(query, values)
        db.commit()

        cursor.close()

        # Delete old photo after successful database update
        if (
            photo and photo.filename
            and current_photo
            and current_photo != photo_filename
        ):

            old_photo_path = os.path.join(
                app.config["UPLOAD_FOLDER"],
                current_photo
            )

            if os.path.exists(old_photo_path):
                os.remove(old_photo_path)

        return redirect(f"/client/{client_id}")

    # Get existing client information
    cursor.execute("""
        SELECT client_id, name, phone, date_of_birth,
               gender, joining_date, address,
               emergency_contact, photo
        FROM clients
        WHERE client_id=%s
    """, (client_id,))

    client = cursor.fetchone()

    cursor.close()

    if client is None:
        return "Client not found", 404

    return render_template(
        "edit_client.html",
        client=client
    )

@app.route("/delete-client/<int:client_id>", methods=["POST"])
def delete_client(client_id):

    # Check admin login
    if "admin_id" not in session:
        return redirect("/login")

    cursor = db.cursor()

    # Get the client's photo before deleting the client
    cursor.execute(
        "SELECT photo FROM clients WHERE client_id=%s",
        (client_id,)
    )

    client = cursor.fetchone()

    if client is None:
        cursor.close()
        return "Client not found", 404

    # Get photo filename
    photo_filename = client[0]

    # Delete the client from database
    cursor.execute(
        "DELETE FROM clients WHERE client_id=%s",
        (client_id,)
    )

    db.commit()

    cursor.close()

    # Delete the photo file if it exists
    if photo_filename:

        photo_path = os.path.join(
            app.config["UPLOAD_FOLDER"],
            photo_filename
        )

        if os.path.exists(photo_path):
            os.remove(photo_path)

    return redirect("/clients")


@app.route("/add-membership", methods=["GET", "POST"])
def add_membership():

    cursor = db.cursor()

    if request.method == "POST":

        client_id = request.form.get("client_id", "").strip()
        membership_type = request.form.get("membership_type", "").strip()
        start_date = request.form.get("start_date", "").strip()
        end_date = request.form.get("end_date", "").strip()
        amount = request.form.get("amount", "").strip()
        payment_status = request.form.get("payment_status", "").strip()

        # Check required fields
        if not client_id or not membership_type or not start_date or not end_date or not amount:
            cursor.close()
            return "Please fill in all required fields."

        query = """
            INSERT INTO memberships
            (client_id, membership_type, start_date,
             end_date, amount, payment_status)
            VALUES (%s, %s, %s, %s, %s, %s)
        """

        values = (
            client_id,
            membership_type,
            start_date,
            end_date,
            amount,
            payment_status
        )

        cursor.execute(query, values)
        db.commit()

        cursor.close()

        return redirect("/memberships")

    # Get clients for dropdown
    cursor.execute("""
        SELECT client_id, name
        FROM clients
        ORDER BY name
    """)

    clients = cursor.fetchall()

    cursor.close()

    return render_template(
        "add_membership.html",
        clients=clients
    )


@app.route("/memberships")
def memberships():

    if "admin_id" not in session:
        return redirect("/login")

    search = request.args.get("search", "").strip()
    status_filter = request.args.get("status", "all").strip().lower()

    # Date range
    start_date_filter = request.args.get("start_date", "").strip()
    end_date_filter = request.args.get("end_date", "").strip()

    cursor = db.cursor()

    # Get memberships
    if search:

        cursor.execute("""
            SELECT
                memberships.membership_id,
                memberships.client_id,
                clients.name,
                memberships.membership_type,
                memberships.start_date,
                memberships.end_date,
                memberships.amount,
                memberships.payment_status
            FROM memberships
            JOIN clients
                ON memberships.client_id = clients.client_id
            WHERE (
                    clients.name LIKE %s
                    OR CAST(memberships.client_id AS CHAR) LIKE %s
                    OR CAST(memberships.membership_id AS CHAR) LIKE %s
                    OR memberships.membership_type LIKE %s
                  )
            ORDER BY memberships.membership_id DESC
        """, (
            "%" + search + "%",
            "%" + search + "%",
            "%" + search + "%",
            "%" + search + "%"
        ))

    else:

        cursor.execute("""
            SELECT
                memberships.membership_id,
                memberships.client_id,
                clients.name,
                memberships.membership_type,
                memberships.start_date,
                memberships.end_date,
                memberships.amount,
                memberships.payment_status
            FROM memberships
            JOIN clients
                ON memberships.client_id = clients.client_id
            ORDER BY memberships.membership_id DESC
        """)

    memberships = cursor.fetchall()
    cursor.close()

    from datetime import date

    updated_memberships = []

    for membership in memberships:

        membership_id = membership[0]
        client_id = membership[1]
        client_name = membership[2]
        membership_type = membership[3]
        membership_start_date = membership[4]
        membership_end_date = membership[5]
        amount = membership[6]
        payment_status = membership[7]

        # Date range filter
        if start_date_filter:
            if membership_start_date < date.fromisoformat(start_date_filter):
                continue

        if end_date_filter:
            if membership_start_date > date.fromisoformat(end_date_filter):
                continue

        # Membership status
        days_remaining = (
            membership_end_date - date.today()
        ).days

        if days_remaining < 0:
            membership_status = "Expired"

        elif days_remaining <= 7:
            membership_status = "Expiring Soon"

        else:
            membership_status = "Active"

        # Status filter
        if status_filter == "active":

            if membership_status != "Active":
                continue

        elif status_filter == "expiring":

            if membership_status != "Expiring Soon":
                continue

        elif status_filter == "expired":

            if membership_status != "Expired":
                continue

        elif status_filter == "pending":

            if payment_status not in ("Pending", "Partial"):
                continue

        updated_memberships.append((
            membership_id,
            client_id,
            client_name,
            membership_type,
            membership_start_date,
            membership_end_date,
            amount,
            payment_status,
            membership_status,
            days_remaining
        ))

    return render_template(
        "memberships.html",
        memberships=updated_memberships,
        search=search,
        status_filter=status_filter,
        start_date_filter=start_date_filter,
        end_date_filter=end_date_filter
    )

@app.route("/active-members")
def active_members():

    if "admin_id" not in session:
        return redirect("/login")
    from datetime import date

    cursor = db.cursor()

    cursor.execute("""
        SELECT
            memberships.client_id,
            clients.name,
            clients.phone,
            memberships.membership_type,
            memberships.start_date,
            memberships.end_date,
            memberships.amount,
            memberships.payment_status
        FROM memberships
        JOIN clients
            ON memberships.client_id = clients.client_id
        WHERE memberships.end_date >= CURDATE()
        ORDER BY memberships.end_date ASC
    """)

    memberships = cursor.fetchall()

    cursor.close()

    return render_template(
        "active_members.html",
        memberships=memberships,
        current_date=date.today()
    )

@app.route("/edit-membership/<int:client_id>/<start_date>", methods=["GET", "POST"])
def edit_membership(client_id, start_date):

    if request.method == "POST":

        membership_type = request.form.get("membership_type", "").strip()
        new_start_date = request.form.get("start_date", "").strip()
        end_date = request.form.get("end_date", "").strip()
        amount = request.form.get("amount", "").strip()
        payment_status = request.form.get("payment_status", "").strip()

        if not membership_type or not new_start_date or not end_date or not amount:
            return "Please fill in all required fields."

        cursor = db.cursor()

        query = """
            UPDATE memberships
            SET membership_type=%s,
                start_date=%s,
                end_date=%s,
                amount=%s,
                payment_status=%s
            WHERE client_id=%s
              AND start_date=%s
        """

        values = (
            membership_type,
            new_start_date,
            end_date,
            amount,
            payment_status,
            client_id,
            start_date
        )

        cursor.execute(query, values)
        db.commit()
        cursor.close()

        return redirect("/memberships")

    # GET request

    cursor = db.cursor()

    cursor.execute("""
        SELECT
            memberships.client_id,
            clients.name,
            memberships.membership_type,
            memberships.start_date,
            memberships.end_date,
            memberships.amount,
            memberships.payment_status
        FROM memberships
        JOIN clients
            ON memberships.client_id = clients.client_id
        WHERE memberships.client_id=%s
          AND memberships.start_date=%s
    """, (client_id, start_date))

    membership = cursor.fetchone()

    # IMPORTANT: consume any remaining result
    cursor.fetchall()

    cursor.close()

    if membership is None:
        return "Membership not found", 404

    return render_template(
        "edit_membership.html",
        membership=membership
    )




@app.route("/delete-membership/<int:client_id>/<start_date>", methods=["POST"])
def delete_membership(client_id, start_date):

    cursor = db.cursor()

    cursor.execute("""
        DELETE FROM memberships
        WHERE client_id=%s
          AND start_date=%s
    """, (client_id, start_date))

    db.commit()

    cursor.close()

    return redirect("/memberships")



@app.route("/add-payment", methods=["GET", "POST"])
def add_payment():

    cursor = db.cursor()

    if request.method == "POST":

        client_id = request.form.get("client_id", "").strip()
        membership_id = request.form.get("membership_id", "").strip()
        amount = request.form.get("amount", "").strip()
        payment_date = request.form.get("payment_date", "").strip()
        payment_method = request.form.get("payment_method", "").strip()
        notes = request.form.get("notes", "").strip()

        if not client_id or not membership_id or not amount or not payment_date:
            cursor.close()
            return "Please fill in all required fields."

        # Verify that the membership belongs to the selected client
        cursor.execute("""
            SELECT amount
            FROM memberships
            WHERE membership_id=%s
              AND client_id=%s
        """, (membership_id, client_id))

        membership = cursor.fetchone()

        if not membership:
            cursor.close()
            return "Invalid membership selected."

        membership_amount = float(membership[0])

        # Insert payment for this specific membership
        query = """
            INSERT INTO payments
            (client_id, membership_id, amount, payment_date,
             payment_method, notes)
            VALUES (%s, %s, %s, %s, %s, %s)
        """

        values = (
            client_id,
            membership_id,
            amount,
            payment_date,
            payment_method,
            notes
        )

        cursor.execute(query, values)
        db.commit()

        # Calculate total payments for THIS membership only
        cursor.execute("""
            SELECT COALESCE(SUM(amount), 0)
            FROM payments
            WHERE membership_id=%s
        """, (membership_id,))

        total_paid = float(cursor.fetchone()[0])

        # Determine payment status
        if total_paid >= membership_amount:
            status = "Paid"
        elif total_paid > 0:
            status = "Partial"
        else:
            status = "Pending"

        # Update payment status for THIS membership only
        cursor.execute("""
            UPDATE memberships
            SET payment_status=%s
            WHERE membership_id=%s
        """, (status, membership_id))

        db.commit()

        cursor.close()

        return redirect("/payments")

    # GET request
    cursor.execute("""
        SELECT client_id, name
        FROM clients
        ORDER BY name
    """)

    clients = cursor.fetchall()

    cursor.close()

    # Get values when coming from Pending Payments
    selected_client_id = request.args.get("client_id", "")
    selected_membership_id = request.args.get("membership_id", "")

    return render_template(
        "add_payment.html",
        clients=clients,
        selected_client_id=selected_client_id,
        selected_membership_id=selected_membership_id
    )

@app.route("/payments")
def payments():

    if "admin_id" not in session:
        return redirect("/login")

    search = request.args.get("search", "").strip()

    # Date range filters
    start_date_filter = request.args.get("start_date", "").strip()
    end_date_filter = request.args.get("end_date", "").strip()

    # Payment status filter
    status_filter = request.args.get("status", "all").strip().lower()

    cursor = db.cursor()

    if search:

        cursor.execute("""
            SELECT
                payments.payment_id,
                payments.client_id,
                clients.name,
                payments.amount,
                payments.payment_date,
                payments.payment_method,
                payments.notes,
                memberships.payment_status
            FROM payments
            JOIN clients
                ON payments.client_id = clients.client_id
            JOIN memberships
                ON payments.membership_id = memberships.membership_id
            WHERE (
                clients.name LIKE %s
                OR CAST(payments.client_id AS CHAR) LIKE %s
                OR CAST(payments.payment_id AS CHAR) LIKE %s
                OR payments.payment_method LIKE %s
            )
            ORDER BY payments.payment_date DESC
        """, (
            "%" + search + "%",
            "%" + search + "%",
            "%" + search + "%",
            "%" + search + "%"
        ))

    else:

        cursor.execute("""
            SELECT
                payments.payment_id,
                payments.client_id,
                clients.name,
                payments.amount,
                payments.payment_date,
                payments.payment_method,
                payments.notes,
                memberships.payment_status
            FROM payments
            JOIN clients
                ON payments.client_id = clients.client_id
            JOIN memberships
                ON payments.membership_id = memberships.membership_id
            ORDER BY payments.payment_date DESC
        """)

    payments = cursor.fetchall()
    cursor.close()

    from datetime import date

    filtered_payments = []

    for payment in payments:

        # payment[4] = Payment Date
        payment_date = payment[4]

        # payment[7] = Membership Payment Status
        payment_status = payment[7]

        # From date
        if start_date_filter:
            if payment_date < date.fromisoformat(start_date_filter):
                continue

        # To date
        if end_date_filter:
            if payment_date > date.fromisoformat(end_date_filter):
                continue

        # Status filter
        if status_filter != "all":

            if payment_status.lower() != status_filter:
                continue

        # Keep original 7-column structure for HTML
        filtered_payments.append(payment[:7])

    return render_template(
        "payments.html",
        payments=filtered_payments,
        search=search,
        start_date_filter=start_date_filter,
        end_date_filter=end_date_filter,
        status_filter=status_filter
    )
@app.route("/revenue")
def revenue():

    if "admin_id" not in session:
        return redirect("/login")

    start_date = request.args.get("start_date", "").strip()
    end_date = request.args.get("end_date", "").strip()

    cursor = db.cursor()

    if start_date and end_date:

        cursor.execute("""
            SELECT
                payment_date,
                SUM(amount) AS total_revenue
            FROM payments
            WHERE payment_date BETWEEN %s AND %s
            GROUP BY payment_date
            ORDER BY payment_date DESC
        """, (
            start_date,
            end_date
        ))

    else:

        cursor.execute("""
            SELECT
                payment_date,
                SUM(amount) AS total_revenue
            FROM payments
            GROUP BY payment_date
            ORDER BY payment_date DESC
        """)

    revenue_data = cursor.fetchall()

    cursor.close()

    return render_template(
        "revenue.html",
        revenue_data=revenue_data,
        start_date=start_date,
        end_date=end_date
    )

@app.route("/edit-payment/<int:payment_id>", methods=["GET", "POST"])
def edit_payment(payment_id):

    if request.method == "POST":

        amount = request.form.get("amount", "").strip()
        payment_date = request.form.get("payment_date", "").strip()
        payment_method = request.form.get("payment_method", "").strip()
        notes = request.form.get("notes", "").strip()

        if not amount or not payment_date:
            return "Please fill in all required fields."

        cursor = db.cursor()

        # Get the client ID for this payment
        cursor.execute("""
            SELECT client_id
            FROM payments
            WHERE payment_id=%s
        """, (payment_id,))

        payment_info = cursor.fetchone()

        if payment_info is None:
            cursor.close()
            return "Payment not found", 404

        client_id = payment_info[0]

        # Update payment
        cursor.execute("""
            UPDATE payments
            SET amount=%s,
                payment_date=%s,
                payment_method=%s,
                notes=%s
            WHERE payment_id=%s
        """, (
            amount,
            payment_date,
            payment_method,
            notes,
            payment_id
        ))

        db.commit()

        # Get the client's current membership amount
        cursor.execute("""
            SELECT amount
            FROM memberships
            WHERE client_id=%s
            ORDER BY end_date DESC
            LIMIT 1
        """, (client_id,))

        membership = cursor.fetchone()

        if membership:

            membership_amount = float(membership[0])

            # Calculate total payments after editing
            cursor.execute("""
                SELECT COALESCE(SUM(amount), 0)
                FROM payments
                WHERE client_id=%s
            """, (client_id,))

            total_paid = float(cursor.fetchone()[0])

            # Recalculate payment status
            if total_paid >= membership_amount:
                status = "Paid"
            elif total_paid > 0:
                status = "Partial"
            else:
                status = "Pending"

            # Update membership status
            cursor.execute("""
                UPDATE memberships
                SET payment_status=%s
                WHERE client_id=%s
            """, (status, client_id))

            db.commit()

        cursor.close()

        return redirect("/payments")

    # GET request
    cursor = db.cursor()

    cursor.execute("""
        SELECT
            payments.payment_id,
            payments.client_id,
            clients.name,
            payments.amount,
            payments.payment_date,
            payments.payment_method,
            payments.notes
        FROM payments
        JOIN clients
            ON payments.client_id = clients.client_id
        WHERE payments.payment_id=%s
    """, (payment_id,))

    payment = cursor.fetchone()

    cursor.fetchall()
    cursor.close()

    if payment is None:
        return "Payment not found", 404

    return render_template(
        "edit_payment.html",
        payment=payment
    )


@app.route("/delete-payment/<int:payment_id>", methods=["POST"])
def delete_payment(payment_id):

    cursor = db.cursor()

    # Get the client ID before deleting the payment
    cursor.execute("""
        SELECT client_id
        FROM payments
        WHERE payment_id=%s
    """, (payment_id,))

    payment_info = cursor.fetchone()

    if payment_info is None:
        cursor.close()
        return "Payment not found", 404

    client_id = payment_info[0]

    # Delete the payment
    cursor.execute("""
        DELETE FROM payments
        WHERE payment_id=%s
    """, (payment_id,))

    db.commit()

    # Get the client's current membership amount
    cursor.execute("""
        SELECT amount
        FROM memberships
        WHERE client_id=%s
        ORDER BY end_date DESC
        LIMIT 1
    """, (client_id,))

    membership = cursor.fetchone()

    if membership:

        membership_amount = float(membership[0])

        # Calculate remaining payments
        cursor.execute("""
            SELECT COALESCE(SUM(amount), 0)
            FROM payments
            WHERE client_id=%s
        """, (client_id,))

        total_paid = float(cursor.fetchone()[0])

        # Recalculate payment status
        if total_paid >= membership_amount:
            status = "Paid"
        elif total_paid > 0:
            status = "Partial"
        else:
            status = "Pending"

        # Update membership status
        cursor.execute("""
            UPDATE memberships
            SET payment_status=%s
            WHERE client_id=%s
        """, (status, client_id))

        db.commit()

    cursor.close()

    return redirect("/payments")

@app.route("/pending-payments")
def pending_payments():
    if "admin_id" not in session:
        return redirect("/login")

    cursor = db.cursor()

    cursor.execute("""
        SELECT
            memberships.client_id,
            clients.name,
            memberships.membership_type,
            memberships.amount,
            COALESCE(SUM(payments.amount), 0) AS total_paid,
            memberships.payment_status,
            memberships.start_date,
            memberships.end_date,
            memberships.membership_id
        FROM memberships
        JOIN clients
            ON memberships.client_id = clients.client_id
        LEFT JOIN payments
            ON memberships.membership_id = payments.membership_id
        WHERE memberships.payment_status IN ('Pending', 'Partial')
        GROUP BY
            memberships.client_id,
            clients.name,
            memberships.membership_type,
            memberships.amount,
            memberships.payment_status,
            memberships.start_date,
            memberships.end_date,
            memberships.membership_id
        ORDER BY memberships.end_date ASC
    """)

    pending_payments = cursor.fetchall()

    cursor.close()

    return render_template(
        "pending_payments.html",
        pending_payments=pending_payments
    )
@app.route("/recent-payments")
def recent_payments():

    if "admin_id" not in session:
        return redirect("/login")

    cursor = db.cursor()

    cursor.execute("""
        SELECT
            payments.payment_id,
            clients.name,
            payments.amount,
            payments.payment_date,
            payments.payment_method
        FROM payments
        JOIN clients
            ON payments.client_id = clients.client_id
        ORDER BY payments.payment_date DESC,
                 payments.payment_id DESC
        LIMIT 3
    """)

    recent_payments = cursor.fetchall()

    cursor.close()

    return render_template(
        "recent_payments.html",
        recent_payments=recent_payments
    )
@app.route("/expiring-memberships")
def expiring_memberships():

    if "admin_id" not in session:
        return redirect("/login")

    cursor = db.cursor()

    cursor.execute("""
        SELECT
            memberships.client_id,
            clients.name,
            clients.phone,
            memberships.membership_type,
            memberships.start_date,
            memberships.end_date,
            memberships.amount,
            memberships.payment_status
        FROM memberships
        JOIN clients
            ON memberships.client_id = clients.client_id
        WHERE memberships.end_date
              BETWEEN CURDATE()
              AND DATE_ADD(CURDATE(), INTERVAL 7 DAY)
        ORDER BY memberships.end_date ASC
    """)

    memberships = cursor.fetchall()

    cursor.close()

    return render_template(
        "expiring_memberships.html",
        memberships=memberships
    )
@app.route("/overdue-memberships")
def overdue_memberships():

    if "admin_id" not in session:
        return redirect("/login")

    cursor = db.cursor()

    cursor.execute("""
        SELECT
            memberships.client_id,
            clients.name,
            clients.phone,
            memberships.membership_type,
            memberships.start_date,
            memberships.end_date,
            memberships.amount,
            memberships.payment_status
        FROM memberships
        JOIN clients
            ON memberships.client_id = clients.client_id
        WHERE memberships.end_date < CURDATE()
        ORDER BY memberships.end_date ASC
    """)

    memberships = cursor.fetchall()

    cursor.close()

    return render_template(
        "overdue_memberships.html",
        memberships=memberships
    )

if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5001, debug=False)