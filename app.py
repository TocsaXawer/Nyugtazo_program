from flask import Flask, render_template, request, redirect, url_for, flash, send_file, session, g
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime, timedelta
import os
import csv
import io

# Importáld a FlaskWebGUI-t
from flaskwebgui import FlaskUI

app = Flask(__name__)

# Adatbázis konfiguráció
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///szamlazo.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SECRET_KEY'] = 'e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855' # Ezt VALÓBAN cseréld le egy erős, véletlenszerű kulcsra!

db = SQLAlchemy(app)

# --- Adatbázis modellek ---

class Company(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    address = db.Column(db.String(200), nullable=False)
    tax_number = db.Column(db.String(20), unique=True, nullable=False)
    bank_account = db.Column(db.String(50))
    contact_person = db.Column(db.String(100))
    email = db.Column(db.String(100))
    phone = db.Column(db.String(20))
    invoices = db.relationship('Invoice', backref='company', lazy=True, cascade='all, delete-orphan')

    def __repr__(self):
        return f'<Company {self.name}>'

class Invoice(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    company_id = db.Column(db.Integer, db.ForeignKey('company.id'), nullable=False)
    invoice_number = db.Column(db.String(50), unique=True, nullable=False)
    issue_date = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    due_date = db.Column(db.DateTime, nullable=False)
    total_amount = db.Column(db.Float, nullable=False)
    currency = db.Column(db.String(10), default='HUF')
    description = db.Column(db.Text)

    def __repr__(self):
        return f'<Invoice {self.invoice_number}>'

# Adatbázis létrehozása az első futtatáskor
with app.app_context():
    db.create_all()

# --- Útvonalak ---

@app.route('/')
@app.route('/szamlak')
def invoices():
    companies = Company.query.all()
    query = Invoice.query.order_by(Invoice.issue_date.desc())

    search_company_name = request.args.get('search_company_name', '').strip()
    start_date_str = request.args.get('start_date', '').strip()
    end_date_str = request.args.get('end_date', '').strip()

    if search_company_name:
        query = query.join(Company).filter(Company.name.ilike(f'%{search_company_name}%'))

    if start_date_str:
        try:
            start_date = datetime.strptime(start_date_str, '%Y-%m-%d')
            query = query.filter(Invoice.issue_date >= start_date)
        except ValueError:
            flash('Érvénytelen kezdő dátum formátum! Használj ÉÉÉÉ-HH-NN formátumot.', 'danger')
            start_date_str = ''
    
    if end_date_str:
        try:
            end_date = datetime.strptime(end_date_str, '%Y-%m-%d')
            query = query.filter(Invoice.issue_date <= end_date + timedelta(days=1))
        except ValueError:
            flash('Érvénytelen befejező dátum formátum! Használj ÉÉÉÉ-HH-NN formátumot.', 'danger')
            end_date_str = ''

    invoices = query.all()
    
    today = datetime.now().strftime('%Y-%m-%d')
    due_date = (datetime.now() + timedelta(days=8)).strftime('%Y-%m-%d')

    return render_template('index.html', 
                           companies=companies, 
                           invoices=invoices, 
                           today=today, 
                           due_date=due_date,
                           search_company_name=search_company_name,
                           start_date=start_date_str,
                           end_date=end_date_str)

@app.route('/szamlak/uj', methods=['GET', 'POST'])
def add_invoice():
    if request.method == 'POST':
        try:
            company_id = request.form['company_id']
            invoice_number = request.form['invoice_number']
            issue_date_str = request.form['issue_date']
            due_date_str = request.form['due_date']
            total_amount = float(request.form['total_amount'])
            currency = request.form.get('currency', 'HUF')
            description = request.form.get('description', '')

            issue_date = datetime.strptime(issue_date_str, '%Y-%m-%d')
            due_date = datetime.strptime(due_date_str, '%Y-%m-%d')

            existing_invoice = Invoice.query.filter_by(invoice_number=invoice_number).first()
            if existing_invoice:
                flash(f'Hiba: A "{invoice_number}" számlaszám már létezik.', 'danger')
                companies = Company.query.all()
                today = datetime.now().strftime('%Y-%m-%d')
                due_date_default = (datetime.now() + timedelta(days=8)).strftime('%Y-%m-%d')
                return render_template('add_invoice.html', companies=companies, today=today, due_date=due_date_default)

            new_invoice = Invoice(
                company_id=company_id,
                invoice_number=invoice_number,
                issue_date=issue_date,
                due_date=due_date,
                total_amount=total_amount,
                currency=currency,
                description=description
            )
            db.session.add(new_invoice)
            db.session.commit()
            flash('Számla sikeresen hozzáadva!', 'success')
            return redirect(url_for('invoices'))
        except Exception as e:
            db.session.rollback()
            flash(f'Hiba történt a számla hozzáadása közben: {e}', 'danger')
            companies = Company.query.all()
            today = datetime.now().strftime('%Y-%m-%d')
            due_date_default = (datetime.now() + timedelta(days=8)).strftime('%Y-%m-%d')
            return render_template('add_invoice.html', companies=companies, today=today, due_date=due_date_default)
            
    companies = Company.query.all()
    today = datetime.now().strftime('%Y-%m-%d')
    due_date = (datetime.now() + timedelta(days=8)).strftime('%Y-%m-%d')
    return render_template('add_invoice.html', companies=companies, today=today, due_date=due_date)

@app.route('/szamlak/szerkeszt/<int:invoice_id>', methods=['GET', 'POST'])
def edit_invoice(invoice_id):
    invoice = Invoice.query.get_or_404(invoice_id)
    companies = Company.query.all()

    if request.method == 'POST':
        try:
            new_invoice_number = request.form['invoice_number']
            if new_invoice_number != invoice.invoice_number:
                existing_invoice = Invoice.query.filter_by(invoice_number=new_invoice_number).first()
                if existing_invoice:
                    flash(f'Hiba: A "{new_invoice_number}" számlaszám már létezik.', 'danger')
                    return render_template('edit_invoice.html', invoice=invoice, companies=companies)

            invoice.company_id = request.form['company_id']
            invoice.invoice_number = new_invoice_number
            invoice.issue_date = datetime.strptime(request.form['issue_date'], '%Y-%m-%d')
            invoice.due_date = datetime.strptime(request.form['due_date'], '%Y-%m-%d')
            invoice.total_amount = float(request.form['total_amount'])
            invoice.currency = request.form.get('currency', 'HUF')
            invoice.description = request.form.get('description', '')

            db.session.commit()
            flash('Számla sikeresen frissítve!', 'success')
            return redirect(url_for('invoices'))
        except Exception as e:
            db.session.rollback()
            flash(f'Hiba történt a számla szerkesztése közben: {e}', 'danger')
            return render_template('edit_invoice.html', invoice=invoice, companies=companies)
            
    return render_template('edit_invoice.html', invoice=invoice, companies=companies)

@app.route('/szamlak/torles/<int:invoice_id>', methods=['POST'])
def delete_invoice(invoice_id):
    invoice = Invoice.query.get_or_404(invoice_id)
    try:
        db.session.delete(invoice)
        db.session.commit()
        flash('Számla sikeresen törölve!', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Hiba történt a számla törlése közben: {e}', 'danger')
    return redirect(url_for('invoices'))


@app.route('/cegek')
def companies():
    companies = Company.query.all()
    return render_template('companies.html', companies=companies)

@app.route('/cegek/uj', methods=['GET', 'POST'])
def add_company():
    if request.method == 'POST':
        try:
            name = request.form['name']
            address = request.form['address']
            tax_number = request.form['tax_number']
            bank_account = request.form.get('bank_account', '')
            contact_person = request.form.get('contact_person', '')
            email = request.form.get('email', '')
            phone = request.form.get('phone', '')

            new_company = Company(
                name=name,
                address=address,
                tax_number=tax_number,
                bank_account=bank_account,
                contact_person=contact_person,
                email=email,
                phone=phone
            )
            db.session.add(new_company)
            db.session.commit()
            flash('Cég sikeresen hozzáadva!', 'success')
            return redirect(url_for('companies'))
        except Exception as e:
            db.session.rollback()
            flash(f'Hiba történt a cég hozzáadása közben: {e}', 'danger')
            return redirect(url_for('add_company'))
    return render_template('add_company.html')

@app.route('/cegek/szerkeszt/<int:company_id>', methods=['GET', 'POST'])
def edit_company(company_id):
    company = Company.query.get_or_404(company_id)
    if request.method == 'POST':
        try:
            company.name = request.form['name']
            company.address = request.form['address']
            company.tax_number = request.form['tax_number']
            company.bank_account = request.form.get('bank_account', '')
            company.contact_person = request.form.get('contact_person', '')
            company.email = request.form.get('email', '')
            company.phone = request.form.get('phone', '')
            db.session.commit()
            flash('Cég adatai sikeresen frissítve!', 'success')
            return redirect(url_for('companies'))
        except Exception as e:
            db.session.rollback()
            flash(f'Hiba történt a cég szerkesztése közben: {e}', 'danger')
    return render_template('edit_company.html', company=company)

@app.route('/cegek/torles/<int:company_id>', methods=['POST'])
def delete_company(company_id):
    company = Company.query.get_or_404(company_id)
    try:
        db.session.delete(company)
        db.session.commit()
        flash('Cég sikeresen törölve!', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Hiba történt a cég törlése közben: {e}', 'danger')
    return redirect(url_for('companies'))

@app.route('/cegek/import', methods=['GET', 'POST'])
def import_companies():
    if request.method == 'POST':
        if 'file' not in request.files:
            flash('Nincs kiválasztva fájl!', 'danger')
            return redirect(request.url)
        file = request.files['file']
        if file.filename == '':
            flash('Nincs kiválasztva fájl!', 'danger')
            return redirect(request.url)
        if file and file.filename.endswith('.csv'):
            stream = io.StringIO(file.stream.read().decode("UTF8"), newline=None)
            reader = csv.reader(stream)
            header = next(reader, None)
            expected_header = ['name', 'address', 'tax_number', 'bank_account', 'contact_person', 'email', 'phone']
            if header != expected_header:
                flash(f'Hibás CSV formátum. A fejléceknek a következőknek kell lenniük: {", ".join(expected_header)}', 'danger')
                return redirect(request.url)

            imported_count = 0
            for row in reader:
                if len(row) == 7:
                    try:
                        existing_company = Company.query.filter_by(tax_number=row[2]).first()
                        if existing_company:
                            flash(f'Figyelem: A(z) "{row[0]}" cég (adószám: {row[2]}) már létezik, kihagyva.', 'warning')
                            continue

                        new_company = Company(
                            name=row[0],
                            address=row[1],
                            tax_number=row[2],
                            bank_account=row[3],
                            contact_person=row[4],
                            email=row[5],
                            phone=row[6]
                        )
                        db.session.add(new_company)
                        imported_count += 1
                    except Exception as e:
                        db.session.rollback()
                        flash(f'Hiba történt a(z) "{row[0]}" cég importálásakor: {e}. Visszaállítás.', 'danger')
                        return redirect(request.url)
                else:
                    flash(f'Hibás sor a CSV fájlban: {row}. Kihagyva.', 'warning')
            db.session.commit()
            flash(f'{imported_count} cég sikeresen importálva!', 'success')
            return redirect(url_for('companies'))
        else:
            flash('Csak CSV fájlokat lehet importálni!', 'danger')
            return redirect(request.url)
    return render_template('import_companies.html')

@app.route('/cegek/export')
def export_companies():
    si = io.StringIO()
    cw = csv.writer(si)
    cw.writerow(['Név', 'Cím', 'Adószám', 'Bankszámlaszám', 'Kapcsolattartó', 'E-mail', 'Telefon'])
    companies = Company.query.all()
    for company in companies:
        cw.writerow([company.name, company.address, company.tax_number, company.bank_account, company.contact_person, company.email, company.phone])
    
    output = io.BytesIO(si.getvalue().encode('utf-8'))
    output.seek(0)
    
    return send_file(output, as_attachment=True, download_name='companies.csv', mimetype='text/csv')


@app.route('/statisztika')
def statistics():
    total_invoices = Invoice.query.count()
    total_amount_huf = db.session.query(db.func.sum(Invoice.total_amount)).filter(Invoice.currency == 'HUF').scalar() or 0
    
    monthly_stats = db.session.query(
        db.func.strftime('%Y-%m', Invoice.issue_date).label('month'),
        db.func.count(Invoice.id).label('invoice_count'),
        db.func.sum(Invoice.total_amount).label('total_amount')
    ).group_by('month').order_by('month').all()

    return render_template('statistics.html', 
                           total_invoices=total_invoices, 
                           total_amount_huf=total_amount_huf,
                           monthly_stats=monthly_stats)

if __name__ == '__main__':
    ui = FlaskUI(
        app=app,
        server="flask",
        width=1000,
        height=700
    )
    ui.run()