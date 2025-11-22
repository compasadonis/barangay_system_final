from flask import Flask, render_template, request, redirect, url_for, flash, session, make_response
import os, csv
from datetime import datetime, timedelta
from werkzeug.security import generate_password_hash
from sqlalchemy import or_, inspect

from models import db, BarangayID, Clearance, Indigency, GoodMoral, FirstJobSeeker, User
from auth import bp as auth_bp
from config import Config


# ---------------------------------------------------
# HELPERS
# ---------------------------------------------------
def column_is_date(col):
    # crude but works for common SQLAlchemy column types repr
    return "DATE" in str(col.type).upper() or col.type.__class__.__name__.lower().startswith("date")


def column_is_numeric(col):
    return col.type.__class__.__name__.lower() in ("integer", "bigint", "smallint", "numeric", "float", "decimal")


def model_columns(Model):
    return [c for c in Model.__table__.columns]


def model_headers(Model):
    # list of column names in order
    return [c.name for c in model_columns(Model)]


def make_fields_from_model(Model):
    fields = []
    for c in model_columns(Model):
        if c.name == "id":
            continue

        if column_is_date(c):
            itype = "date"
            default = datetime.utcnow().date().isoformat()
        elif column_is_numeric(c):
            itype = "number"
            default = ""
        else:
            itype = "text"
            default = ""

        # Dropdowns
        options = None
        if c.name == "gender":  # display as Gender
            itype = "select"
            options = ["Male", "Female", "Other"]
        elif c.name == "civil_status":
            itype = "select"
            options = ["Single", "Married", "Widowed", "Divorced", "Separated"]
        elif c.name == "years_of_residency":
            itype = "select"
            options = [str(i) for i in range(1, 51)]

        fd = {
            "name": c.name,
            "type": itype,
            "placeholder": c.name.replace("_", " ").title(),
            "required": not c.nullable and not c.default,
            "col": "col-md-4",
            "options": options,
            "default": default
        }
        fields.append(fd)
    return fields


def row_to_dict(row, Model):
    """
    Convert SQLAlchemy model instance to serializable dict for templates.
    Convert dates to ISO strings so inputs can use them directly.
    """
    out = {}
    for c in model_columns(Model):
        val = getattr(row, c.name)
        if isinstance(val, datetime):
            out[c.name] = val.date().isoformat()
        elif hasattr(val, "isoformat") and column_is_date(c) and val is not None:
            # val might be date
            try:
                out[c.name] = val.isoformat()
            except:
                out[c.name] = str(val)
        else:
            out[c.name] = val
    return out


# ---------------------------------------------------
# INITIALIZE DATABASE
# ---------------------------------------------------
def init_db(app):
    with app.app_context():
        db.create_all()

        # Default admin + staff
        if not User.query.filter_by(username="captain").first():
            db.session.add(User(
                username="captain",
                password=generate_password_hash("captain123"),
                role="admin"
            ))

        if not User.query.filter_by(username="secretary").first():
            db.session.add(User(
                username="secretary",
                password=generate_password_hash("secretary123"),
                role="staff"
            ))

        db.session.commit()


# ---------------------------------------------------
# CREATE APP
# ---------------------------------------------------
def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)

    db.init_app(app)
    init_db(app)

    # Allow getattr in Jinja
    app.jinja_env.globals["getattr"] = getattr

    # Login blueprint
    app.register_blueprint(auth_bp)

    # ---------------------------------------------------
    # DASHBOARD ROUTES
    # ---------------------------------------------------
    @app.route("/")
    def index():
        role = session.get("role")
        if role == "admin":
            return redirect(url_for("admin_dashboard"))
        if role == "staff":
            return redirect(url_for("staff_dashboard"))
        return redirect(url_for("auth.login"))

    @app.route("/admin")
    def admin_dashboard():
        if session.get("role") != "admin":
            return redirect(url_for("auth.login"))

        counts = {
            "barangay_id": BarangayID.query.count(),
            "clearance": Clearance.query.count(),
            "indigency": Indigency.query.count(),
            "goodmoral": GoodMoral.query.count(),
            "firstjob": FirstJobSeeker.query.count()
        }

        return render_template("dashboard_admin.html", counts=counts)

    @app.route("/staff")
    def staff_dashboard():
        if session.get("role") != "staff":
            return redirect(url_for("auth.login"))
        return render_template("dashboard_secretary.html")

    # ---------------------------------------------------
    # REGISTER UNIVERSAL LIST + CREATE ROUTES
    # ---------------------------------------------------
    def register_routes(prefix, Model, template, title):

        endpoint_name = f"view_{prefix}"

        # ---------------------------
        # MAIN VIEW FUNCTION
        # ---------------------------
        def view_func():

            # ============================================
            # CREATE RECORD
            # ============================================
            if request.method == "POST":

                # Required field validation (blank check)
                required_fields = [c.name for c in Model.__table__.columns if not c.nullable and c.name != "id"]
                for rf in required_fields:
                    if not request.form.get(rf):
                        flash(f"'{rf.replace('_',' ').title()}' is required!", "danger")
                        return redirect(request.url)

                # Duplicate name check
                name = request.form.get("name")
                if name:
                    existing = Model.query.filter_by(name=name).first()
                    if existing:
                        flash("This person already exists in the records!", "danger")
                        return redirect(request.url)

                # Continue saving
                obj = Model()
                data = request.form.to_dict()

                for col in Model.__table__.columns:
                    colname = col.name
                    if colname == "id":
                        continue

                    val = data.get(colname)

                    # Date parser
                    if val and column_is_date(col):
                        try:
                            val = datetime.strptime(val, "%Y-%m-%d").date()
                        except:
                            try:
                                val = datetime.fromisoformat(val)
                            except:
                                val = None

                    # Numeric parser
                    if val and column_is_numeric(col):
                        try:
                            if col.type.__class__.__name__.lower() in ("integer", "bigint", "smallint"):
                                val = int(val)
                            else:
                                val = float(val)
                        except:
                            pass

                    setattr(obj, colname, val)

                # Default Status
                if hasattr(obj, "status") and not obj.status:
                    obj.status = "Valid"

                db.session.add(obj)
                db.session.commit()
                flash(f"{title} created!", "success")
                return redirect(request.url)

            # ============================================
            # LIST / SEARCH
            # ============================================
            q = request.args.get("q", "").strip()
            month = request.args.get("month", "")
            year = request.args.get("year", "")

            qry = Model.query

            # Text search
            if q:
                like = f"%{q}%"
                text_cols = []
                for c in Model.__table__.columns:
                    if hasattr(c.type, "length") or c.type.__class__.__name__.lower() in ("text", "varchar", "string"):
                        text_cols.append(getattr(Model, c.name))
                if text_cols:
                    qry = qry.filter(or_(*[col.ilike(like) for col in text_cols]))

            # Date filters
            if month and year and "date_issued" in Model.__table__.columns.keys():
                qry = qry.filter(
                    db.func.strftime("%m", Model.date_issued) == f"{int(month):02d}",
                    db.func.strftime("%Y", Model.date_issued) == year
                )

            records_orm = qry.order_by(Model.id.desc()).all()

            # Status auto-update
            today = datetime.utcnow().date()
            for r in records_orm:
                if hasattr(r, "date_issued") and r.date_issued:
                    months = 12 if "business" in (getattr(r, "purpose", "") or "").lower() else 6
                    expiry = r.date_issued + timedelta(days=30 * months)
                    if hasattr(r, "status"):
                        r.status = "Expired" if today > expiry else "Valid"

            # Convert to dict
            records = [row_to_dict(r, Model) for r in records_orm]

            headers = model_headers(Model)
            fields = make_fields_from_model(Model)

            return render_template(
                template,
                title=title,
                records=records,
                q=q,
                month=month,
                year=year,
                route_name=prefix,
                headers=headers,
                fields=fields
            )

        # REGISTER URL (IMPORTANT: NO 'app =' HERE)
        app.add_url_rule(
            f"/{prefix}",
            endpoint=endpoint_name,
            view_func=view_func,
            methods=["GET", "POST"]
        )

    # REGISTER MODULES
    register_routes("barangay_id", BarangayID, "barangay_id.html", "Barangay ID")
    register_routes("clearance", Clearance, "clearance.html", "Clearance")
    register_routes("indigency", Indigency, "indigency.html", "Indigency")
    register_routes("goodmoral", GoodMoral, "good_moral.html", "Good Moral")
    register_routes("firstjob", FirstJobSeeker, "job_seeker.html", "First Job Seeker")

    # ---------------------------------------------------
    # UNIVERSAL EDIT
    # ---------------------------------------------------
    @app.route("/<rtype>/edit/<int:id>", methods=["GET", "POST"])
    def edit_record(rtype, id):
        mapping = {
            "barangay_id": BarangayID,
            "clearance": Clearance,
            "indigency": Indigency,
            "goodmoral": GoodMoral,
            "firstjob": FirstJobSeeker
        }

        Model = mapping.get(rtype)
        if not Model:
            flash("Invalid type", "danger")
            return redirect(url_for("index"))

        record = Model.query.get_or_404(id)

        if request.method == "POST":
            for col in Model.__table__.columns:
                if col.name == "id":
                    continue

                val = request.form.get(col.name)

                if val and column_is_date(col):
                    try:
                        val = datetime.strptime(val, "%Y-%m-%d").date()
                    except:
                        pass

                if val and column_is_numeric(col):
                    try:
                        if col.type.__class__.__name__.lower() in ("integer", "bigint", "smallint"):
                            val = int(val)
                        else:
                            val = float(val)
                    except:
                        pass

                setattr(record, col.name, val)

            db.session.commit()
            flash("Updated successfully!", "success")
            return redirect(url_for(f"view_{rtype}"))

        # Convert to dict for template usage and prepare fields/headers
        record_dict = row_to_dict(record, Model)
        columns = model_columns(Model)
        headers = model_headers(Model)
        fields = make_fields_from_model(Model)

        return render_template("edit_generic.html",
                               record=record_dict,
                               columns=columns,
                               rtype=rtype,
                               headers=headers,
                               fields=fields)

    # ---------------------------------------------------
    # UNIVERSAL DELETE
    # ---------------------------------------------------
    @app.route("/<rtype>/delete/<int:id>", methods=["POST"])
    def delete_record(rtype, id):
        mapping = {
            "barangay_id": BarangayID,
            "clearance": Clearance,
            "indigency": Indigency,
            "goodmoral": GoodMoral,
            "firstjob": FirstJobSeeker
        }

        Model = mapping.get(rtype)
        if not Model:
            flash("Invalid type", "danger")
            return redirect(url_for("index"))

        record = Model.query.get_or_404(id)
        db.session.delete(record)
        db.session.commit()
        flash("Record deleted!", "success")

        return redirect(url_for(f"view_{rtype}"))

    # ---------------------------------------------------
    # PRINT + CSV EXPORT
    # ---------------------------------------------------
    @app.route("/print")
    def print_view():
        rtype = request.args.get("rtype")
        month = request.args.get("month")
        year = request.args.get("year")

        mapping = {
            "barangay_id": (BarangayID, "Barangay ID"),
            "clearance": (Clearance, "Clearance"),
            "indigency": (Indigency, "Indigency"),
            "goodmoral": (GoodMoral, "Good Moral"),
            "firstjob": (FirstJobSeeker, "First Job Seeker")
        }

        if rtype not in mapping:
            flash("Invalid print type", "danger")
            return redirect(url_for("index"))

        Model, title = mapping[rtype]

        qry = Model.query
        if month and year and "date_issued" in Model.__table__.columns.keys():
            qry = qry.filter(
                db.func.strftime("%m", Model.date_issued) == f"{int(month):02d}",
                db.func.strftime("%Y", Model.date_issued) == year
            )

        records_orm = qry.order_by(Model.id.asc()).all()

        # compute status
        today = datetime.utcnow().date()
        for r in records_orm:
            if hasattr(r, "date_issued") and r.date_issued:
                months = 12 if "business" in (getattr(r, "purpose", "") or "").lower() else 6
                expiry = r.date_issued + timedelta(days=30 * months)
                if hasattr(r, "status"):
                    r.status = "Expired" if today > expiry else "Valid"

        records = [row_to_dict(r, Model) for r in records_orm]

        # CSV EXPORT
        if request.args.get("export") == "csv":
            import csv, io
            si = io.StringIO()
            writer = csv.writer(si)
            cols = [c.name for c in Model.__table__.columns]
            writer.writerow(cols)
            for r in records:
                row_vals = []
                for c in cols:
                    v = r.get(c)
                    if isinstance(v, (datetime,)):
                        row_vals.append(v.date().isoformat())
                    else:
                        row_vals.append("" if v is None else str(v))
                writer.writerow(row_vals)

            resp = make_response(si.getvalue())
            resp.headers["Content-Disposition"] = f"attachment; filename={rtype}_{month or 'all'}_{year or 'all'}.csv"
            resp.headers["Content-Type"] = "text/csv"
            return resp

        return render_template("printable.html",
                               records=records,
                               title=title,
                               month=month,
                               year=year)

    # Return the app instance
    return app


# ---------------------------------------------------
# RUN
# ---------------------------------------------------
if __name__ == "__main__":
    app = create_app()
    os.makedirs("database", exist_ok=True)
    app.run(debug=True)
