from flask import Flask, render_template, request, redirect, url_for, flash, session, make_response
import os, csv
from datetime import datetime, timedelta, timezone
from werkzeug.security import generate_password_hash
from sqlalchemy import or_
from models import db, BarangayID, Clearance, Indigency, GoodMoral, FirstJobSeeker, User, ActivityLog
from auth import bp as auth_bp
from config import Config

# ---------------------------------------------------
# HELPERS
# ---------------------------------------------------
def column_is_date(col):
    return "DATE" in str(col.type).upper() or col.type.__class__.__name__.lower().startswith("date")

def column_is_numeric(col):
    return col.type.__class__.__name__.lower() in ("integer", "bigint", "smallint", "numeric", "float", "decimal")

def model_columns(Model):
    return [c for c in Model.__table__.columns]

def model_headers(Model):
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

        options = None
        if c.name == "gender":
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
    out = {}
    for c in model_columns(Model):
        val = getattr(row, c.name)
        if isinstance(val, datetime):
            out[c.name] = val.date().isoformat()
        elif hasattr(val, "isoformat") and column_is_date(c) and val is not None:
            try:
                out[c.name] = val.isoformat()
            except:
                out[c.name] = str(val)
        else:
            out[c.name] = val
    return out

def log_activity(user, action, table_name, record_id=None):
    who = user or session.get("username") or "system"
    log = ActivityLog(user=who, action=action, table_name=table_name, record_id=record_id)
    db.session.add(log)
    db.session.commit()

def init_db(app):
    with app.app_context():
        db.create_all()

        if not User.query.filter_by(username="captain").first():
            db.session.add(User(
                username="captain",
                password=generate_password_hash("captain123"),
                role="admin"
            ))
            db.session.commit()

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

    app.jinja_env.globals["getattr"] = getattr
    app.register_blueprint(auth_bp)

    # ---------------------------
    # ROUTES
    # ---------------------------
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

    # ---------------------------
    # REGISTER MODULE ROUTES
    # ---------------------------
    def register_routes(prefix, Model, template, title):
        endpoint_name = f"view_{prefix}"

        def view_func():
            if request.method == "POST":
                required_fields = [c.name for c in Model.__table__.columns if not c.nullable and c.name != "id"]
                for rf in required_fields:
                    if not request.form.get(rf):
                        flash(f"'{rf.replace('_',' ').title()}' is required!", "danger")
                        return redirect(request.url)

                name = request.form.get("name")
                if name:
                    existing = Model.query.filter_by(name=name).first()
                    if existing:
                        flash("This person already exists in the records!", "danger")
                        return redirect(request.url)

                obj = Model()
                data = request.form.to_dict()

                for col in Model.__table__.columns:
                    colname = col.name
                    if colname == "id":
                        continue
                    val = data.get(colname)

                    if val and column_is_date(col):
                        try:
                            val = datetime.strptime(val, "%Y-%m-%d").date()
                        except:
                            try:
                                val = datetime.fromisoformat(val)
                            except:
                                val = None

                    if val and column_is_numeric(col):
                        try:
                            if col.type.__class__.__name__.lower() in ("integer","bigint","smallint"):
                                val = int(val)
                            else:
                                val = float(val)
                        except:
                            pass

                    setattr(obj, colname, val)

                if hasattr(obj, "status") and not obj.status:
                    obj.status = "Valid"

                db.session.add(obj)
                db.session.commit()
                log_activity(session.get("username"), "CREATE", Model.__tablename__ or prefix, getattr(obj, "id", None))
                flash(f"{title} created!", "success")
                return redirect(request.url)

            q = request.args.get("q", "").strip()
            month = request.args.get("month", "")
            year = request.args.get("year", "")

            qry = Model.query
            if q:
                like = f"%{q}%"
                text_cols = [getattr(Model, c.name) for c in Model.__table__.columns if hasattr(c.type,"length") or c.type.__class__.__name__.lower() in ("text","varchar","string")]
                if text_cols:
                    qry = qry.filter(or_(*[col.ilike(like) for col in text_cols]))

            if month and year and "date_issued" in Model.__table__.columns.keys():
                qry = qry.filter(
                    db.func.strftime("%m", Model.date_issued) == f"{int(month):02d}",
                    db.func.strftime("%Y", Model.date_issued) == year
                )

            records_orm = qry.order_by(Model.id.desc()).all()
            today = datetime.utcnow().date()
            for r in records_orm:
                if hasattr(r,"date_issued") and r.date_issued:
                    months = 12 if "business" in (getattr(r,"purpose","") or "").lower() else 6
                    expiry = r.date_issued + timedelta(days=30*months)
                    if hasattr(r,"status"):
                        r.status = "Expired" if today>expiry else "Valid"

            records = [row_to_dict(r, Model) for r in records_orm]
            headers = model_headers(Model)
            fields = make_fields_from_model(Model)

            return render_template(template, title=title, records=records, q=q, month=month, year=year, route_name=prefix, headers=headers, fields=fields)

        app.add_url_rule(f"/{prefix}", endpoint=endpoint_name, view_func=view_func, methods=["GET","POST"])

    # REGISTER ALL MODULES
    register_routes("barangay_id", BarangayID, "barangay_id.html", "Barangay ID")
    register_routes("clearance", Clearance, "clearance.html", "Clearance")
    register_routes("indigency", Indigency, "indigency.html", "Indigency")
    register_routes("goodmoral", GoodMoral, "good_moral.html", "Good Moral")
    register_routes("firstjob", FirstJobSeeker, "job_seeker.html", "First Job Seeker")

    # ---------------------------
    # EDIT / DELETE / PRINT / ACTIVITY LOG
    # ---------------------------
    @app.route("/<rtype>/edit/<int:id>", methods=["GET","POST"])
    def edit_record(rtype,id):
        mapping = {"barangay_id":BarangayID,"clearance":Clearance,"indigency":Indigency,"goodmoral":GoodMoral,"firstjob":FirstJobSeeker}
        Model = mapping.get(rtype)
        if not Model:
            flash("Invalid type","danger")
            return redirect(url_for("index"))
        record = Model.query.get_or_404(id)
        if request.method=="POST":
            for col in Model.__table__.columns:
                if col.name=="id": continue
                val = request.form.get(col.name)
                if val and column_is_date(col):
                    try: val=datetime.strptime(val,"%Y-%m-%d").date()
                    except: pass
                if val and column_is_numeric(col):
                    try:
                        if col.type.__class__.__name__.lower() in ("integer","bigint","smallint"): val=int(val)
                        else: val=float(val)
                    except: pass
                setattr(record,col.name,val)
            db.session.commit()
            log_activity(session.get("username"),"UPDATE",Model.__tablename__ or rtype,id)
            flash("Updated successfully!","success")
            return redirect(url_for(f"view_{rtype}"))
        record_dict=row_to_dict(record,Model)
        columns=model_columns(Model)
        headers=model_headers(Model)
        fields=make_fields_from_model(Model)
        return render_template("edit_generic.html",record=record_dict,columns=columns,rtype=rtype,headers=headers,fields=fields)

    @app.route("/<rtype>/delete/<int:id>", methods=["POST"])
    def delete_record(rtype,id):
        mapping = {"barangay_id":BarangayID,"clearance":Clearance,"indigency":Indigency,"goodmoral":GoodMoral,"firstjob":FirstJobSeeker}
        Model = mapping.get(rtype)
        if not Model:
            flash("Invalid type","danger")
            return redirect(url_for("index"))
        record = Model.query.get_or_404(id)
        db.session.delete(record)
        db.session.commit()
        log_activity(session.get("username"),"DELETE",Model.__tablename__ or rtype,id)
        flash("Record deleted!","success")
        return redirect(url_for(f"view_{rtype}"))

    @app.route("/print")
    def print_view():
        rtype = request.args.get("rtype")
        month = request.args.get("month")
        year = request.args.get("year")
        mapping = {"barangay_id":(BarangayID,"Barangay ID"),"clearance":(Clearance,"Clearance"),"indigency":(Indigency,"Indigency"),"goodmoral":(GoodMoral,"Good Moral"),"firstjob":(FirstJobSeeker,"First Job Seeker")}
        if rtype not in mapping:
            flash("Invalid print type","danger")
            return redirect(url_for("index"))
        Model,title = mapping[rtype]
        qry = Model.query
        if month and year and "date_issued" in Model.__table__.columns.keys():
            qry = qry.filter(db.func.strftime("%m",Model.date_issued)==f"{int(month):02d}",db.func.strftime("%Y",Model.date_issued)==year)
        records_orm = qry.order_by(Model.id.asc()).all()
        today=datetime.utcnow().date()
        for r in records_orm:
            if hasattr(r,"date_issued") and r.date_issued:
                months=12 if "business" in (getattr(r,"purpose","") or "").lower() else 6
                expiry=r.date_issued + timedelta(days=30*months)
                if hasattr(r,"status"): r.status="Expired" if today>expiry else "Valid"
        records=[row_to_dict(r,Model) for r in records_orm]

        if request.args.get("export")=="csv":
            import io
            si=io.StringIO()
            writer=csv.writer(si)
            cols=[c.name for c in Model.__table__.columns]
            writer.writerow(cols)
            for r in records:
                row_vals=[]
                for c in cols:
                    v=r.get(c)
                    if isinstance(v,(datetime,)):
                        row_vals.append(v.date().isoformat())
                    else:
                        row_vals.append("" if v is None else str(v))
                writer.writerow(row_vals)
            resp=make_response(si.getvalue())
            resp.headers["Content-Disposition"]=f"attachment; filename={rtype}_{month or 'all'}_{year or 'all'}.csv"
            resp.headers["Content-Type"]="text/csv"
            return resp

        return render_template("printable.html",records=records,title=title,month=month,year=year)

    @app.route("/activity_log")
    def activity_log_view():
        if session.get("role") not in ("admin", "staff"):
            return redirect(url_for("auth.login"))

        logs = ActivityLog.query.order_by(ActivityLog.timestamp.desc()).all()
        gmt8 = timezone(timedelta(hours=8))

        table_map = {
            "barangay_id": BarangayID,
            "clearance": Clearance,
            "indigency": Indigency,
            "good_moral": GoodMoral,
            "first_job_seeker": FirstJobSeeker
        }

        for log in logs:
            if log.timestamp:
                # Kung naive datetime, i-assume UTC
                if log.timestamp.tzinfo is None:
                    log.timestamp = log.timestamp.replace(tzinfo=timezone.utc)
                # Convert sa UTC+8
                log.timestamp = log.timestamp.astimezone(gmt8)

            Model = table_map.get(log.table_name)
            if Model and log.record_id:
                record = Model.query.get(log.record_id)
                log.record_name = record.name if record else "Record not found"
            else:
                log.record_name = "Record not found"

        return render_template("activity_log.html", logs=logs)


    return app

# ---------------------------
# RUN APP
# ---------------------------
if __name__=="__main__":
    os.makedirs("database",exist_ok=True)
    app=create_app()
    app.run(debug=True)
