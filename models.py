from flask_sqlalchemy import SQLAlchemy
from datetime import date
db = SQLAlchemy()

class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password = db.Column(db.String(200), nullable=False)
    role = db.Column(db.String(20), nullable=False)  # 'admin' or 'staff'

class BarangayID(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    address = db.Column(db.String(300))
    registered_voter = db.Column(db.String(5))  # Yes/No
    nonreg_proof = db.Column(db.String(300))
    birthday = db.Column(db.Date)
    purpose = db.Column(db.String(300))
    status = db.Column(db.String(50))
    date_issued = db.Column(db.Date)

class Clearance(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    address = db.Column(db.String(300))
    birthday = db.Column(db.Date)
    birthplace = db.Column(db.String(200))
    gender = db.Column(db.String(20))
    civil_status = db.Column(db.String(50))
    purpose = db.Column(db.String(300))
    date_issued = db.Column(db.Date)
    status = db.Column(db.String(50))

class Indigency(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    address = db.Column(db.String(300))
    purpose = db.Column(db.String(300))
    status = db.Column(db.String(50))
    date_issued = db.Column(db.Date)

class GoodMoral(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    address = db.Column(db.String(300))
    date_of_birth = db.Column(db.Date)
    sex = db.Column(db.String(20))
    civil_status = db.Column(db.String(50))
    yrs_of_residency = db.Column(db.Integer)
    purpose = db.Column(db.String(300))
    status = db.Column(db.String(50))
    date_issued = db.Column(db.Date)

class FirstJobSeeker(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    address = db.Column(db.String(300))
    date_of_birth = db.Column(db.Date)
    yrs_of_residency = db.Column(db.Integer)
    date_issued = db.Column(db.Date)
