import os
import sys
import csv
import io
from datetime import datetime, timedelta
from flask import Flask, render_template, request, redirect, url_for, flash, send_file, session, make_response
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy.orm import relationship
from flaskwebgui import FlaskUI
from weasyprint import HTML

# --- Függvény a helyes elérési út meghatározásához ---
def resource_path(relative_path):
    """ Abszolút elérési utat ad vissza, működik fejlesztői és PyInstaller környezetben is. """
    try:
        # A PyInstaller létrehoz egy ideiglenes mappát és a _MEIPASS változóban tárolja az elérési útját
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.abspath(".")

    return os.path.join(base_path, relative_path)

# --- App és kiegészítők inicializálása ---

# Megadjuk a Flask-nak a sablonok helyét a resource_path segítségével
template_folder = resource_path('templates')
app = Flask(__name__, template_folder=template_folder)

# 2. Beállítjuk az alkalmazás konfigurációját
# Az adatbázis elérési útját is a resource_path segítségével adjuk meg
db_path = resource_path('szamlazo.db')
app.config['SQLALCHEMY_DATABASE_URI'] = f'sqlite:///{db_path}'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SECRET_KEY'] = 'csereld-le-ezt-egy-eros-es-egyedi-titkos-kulcsra'

# 3. Hozzárendeljük a kiegészítőket az alkalmazáshoz
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
    currency = db.Column(db.String(10), default='EUR')
    items = relationship('InvoiceItem', backref='invoice', lazy='dynamic', cascade='all, delete-orphan')

    @property
    def total_amount(self):
        return sum(item.quantity * item.unit_price for item in self.items)

    def __repr__(self):
        return f'<Invoice {self.invoice_number}>'

class InvoiceItem(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    invoice_id = db.Column(db.Integer, db.ForeignKey('invoice.id'), nullable=False)
    description = db.Column(db.String(200), nullable=False)
    quantity = db.Column(db.Float, nullable=False, default=1)
    unit_price = db.Column(db.Float, nullable=False)

    @property
    def total(self):
        return self.quantity * self.unit_price

class OwnerCompany(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100))
    address = db.Column(db.String(200))
    tax_number = db.Column(db.String(20))
    bank_account = db.Column(db.String(50))
    email = db.Column(db.String(100))
    phone = db.Column(db.String(20))

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
            flash('Ogiltigt startdatumformat! Använd formatet ÅÅÅÅ-MM-DD.', 'danger')
            start_date_str = ''
    
    if end_date_str:
        try:
            end_date = datetime.strptime(end_date_str, '%Y-%m-%d')
            query = query.filter(Invoice.issue_date <= end_date + timedelta(days=1))
        except ValueError:
            flash('Ogiltigt slutdatumformat! Använd formatet ÅÅÅÅ-MM-DD.', 'danger')
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

@app.route('/szamlak/uj', methods=['POST'])
def add_invoice():
    try:
        new_invoice = Invoice(
            company_id=request.form['company_id'],
            invoice_number=request.form['invoice_number'],
            issue_date=datetime.strptime(request.form['issue_date'], '%Y-%m-%d'),
            due_date=datetime.strptime(request.form['due_date'], '%Y-%m-%d'),
            currency=request.form.get('currency', 'EUR')
        )
        db.session.add(new_invoice)

        descriptions = request.form.getlist('item_description')
        quantities = request.form.getlist('item_quantity')
        unit_prices = request.form.getlist('item_unit_price')

        if not descriptions or not any(d.strip() for d in descriptions):
             raise Exception("Minst en artikel med beskrivning måste anges.")

        for i in range(len(descriptions)):
            if descriptions[i].strip():
                item = InvoiceItem(
                    invoice=new_invoice,
                    description=descriptions[i],
                    quantity=float(quantities[i] or 0),
                    unit_price=float(unit_prices[i] or 0)
                )
                db.session.add(item)
        
        db.session.commit()
        flash('Fakturan har lagts till.', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Ett fel uppstod när fakturan skulle läggas till: {e}', 'danger')
    
    return redirect(url_for('invoices'))


@app.route('/szamlak/szerkeszt/<int:invoice_id>', methods=['GET', 'POST'])
def edit_invoice(invoice_id):
    invoice = db.session.get(Invoice, invoice_id)
    if not invoice:
        return "Invoice not found", 404
    companies = Company.query.all()

    if request.method == 'POST':
        try:
            invoice.company_id = request.form['company_id']
            invoice.invoice_number = request.form['invoice_number']
            invoice.issue_date = datetime.strptime(request.form['issue_date'], '%Y-%m-%d')
            invoice.due_date = datetime.strptime(request.form['due_date'], '%Y-%m-%d')
            invoice.currency = request.form.get('currency', 'EUR')

            for item in invoice.items:
                db.session.delete(item)

            descriptions = request.form.getlist('item_description')
            quantities = request.form.getlist('item_quantity')
            unit_prices = request.form.getlist('item_unit_price')

            if not descriptions or not any(d.strip() for d in descriptions):
                raise Exception("Minst en artikel med beskrivning måste anges.")

            for i in range(len(descriptions)):
                 if descriptions[i].strip():
                    item = InvoiceItem(
                        invoice_id=invoice.id,
                        description=descriptions[i],
                        quantity=float(quantities[i] or 0),
                        unit_price=float(unit_prices[i] or 0)
                    )
                    db.session.add(item)

            db.session.commit()
            flash('Fakturan har uppdaterats.', 'success')
            return redirect(url_for('invoices'))
        except Exception as e:
            db.session.rollback()
            flash(f'Ett fel uppstod när fakturan skulle redigeras: {e}', 'danger')
            return render_template('edit_invoice.html', invoice=invoice, companies=companies)
            
    return render_template('edit_invoice.html', invoice=invoice, companies=companies)

@app.route('/szamlak/torles/<int:invoice_id>', methods=['POST'])
def delete_invoice(invoice_id):
    invoice = db.session.get(Invoice, invoice_id)
    if not invoice:
        return "Invoice not found", 404
    try:
        db.session.delete(invoice)
        db.session.commit()
        flash('Fakturan har tagits bort.', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Ett fel uppstod när fakturan skulle tas bort: {e}', 'danger')
    return redirect(url_for('invoices'))

@app.route('/szamlak/pdf/<int:invoice_id>')
def generate_invoice_pdf(invoice_id):
    try:
        invoice = db.session.get(Invoice, invoice_id)
        if not invoice:
            return "Invoice not found", 404
        owner_company = OwnerCompany.query.first()
        
        rendered_html = render_template('invoice_pdf_sv.html', invoice=invoice, owner_company=owner_company)
        pdf_file = HTML(string=rendered_html).write_pdf()
        
        response = make_response(pdf_file)
        response.headers['Content-Type'] = 'application/pdf'
        response.headers['Content-Disposition'] = f'inline; filename=faktura_{invoice.invoice_number}.pdf'
        
        return response
    except Exception as e:
        flash(f'Ett fel uppstod vid generering av PDF: {e}', 'danger')
        return redirect(request.referrer or url_for('invoices'))

@app.route('/cegek')
def companies():
    companies = Company.query.all()
    return render_template('companies.html', companies=companies)

@app.route('/cegek/uj', methods=['GET', 'POST'])
def add_company():
    if request.method == 'POST':
        try:
            new_company = Company(
                name=request.form['name'],
                address=request.form['address'],
                tax_number=request.form['tax_number'],
                bank_account=request.form.get('bank_account', ''),
                contact_person=request.form.get('contact_person', ''),
                email=request.form.get('email', ''),
                phone=request.form.get('phone', '')
            )
            db.session.add(new_company)
            db.session.commit()
            flash('Företaget har lagts till.', 'success')
            return redirect(url_for('companies'))
        except Exception as e:
            db.session.rollback()
            flash(f'Ett fel uppstod när företaget skulle läggas till: {e}', 'danger')
            return redirect(url_for('add_company'))
    return render_template('add_company.html')

@app.route('/cegek/szerkeszt/<int:company_id>', methods=['GET', 'POST'])
def edit_company(company_id):
    company = db.session.get(Company, company_id)
    if not company:
        return "Company not found", 404
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
            flash('Företagsuppgifterna har uppdaterats.', 'success')
            return redirect(url_for('companies'))
        except Exception as e:
            db.session.rollback()
            flash(f'Ett fel uppstod när företaget skulle redigeras: {e}', 'danger')
    return render_template('edit_company.html', company=company)

@app.route('/cegek/torles/<int:company_id>', methods=['POST'])
def delete_company(company_id):
    company = db.session.get(Company, company_id)
    if not company:
        return "Company not found", 404
    try:
        db.session.delete(company)
        db.session.commit()
        flash('Företaget har tagits bort.', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Ett fel uppstod när företaget skulle tas bort: {e}', 'danger')
    return redirect(url_for('companies'))

@app.route('/cegek/import', methods=['GET', 'POST'])
def import_companies():
    if request.method == 'POST':
        if 'file' not in request.files:
            flash('Ingen fil har valts!', 'danger')
            return redirect(request.url)
        file = request.files['file']
        if file.filename == '':
            flash('Ingen fil har valts!', 'danger')
            return redirect(request.url)
        if file and file.filename.endswith('.csv'):
            try:
                stream = io.StringIO(file.stream.read().decode("UTF8"), newline=None)
                reader = csv.reader(stream)
                header = next(reader, None)
                expected_header = ['name', 'address', 'tax_number', 'bank_account', 'contact_person', 'email', 'phone']
                if header != expected_header:
                    header_str = ", ".join(expected_header)
                    flash(f'Ogiltigt CSV-format. Rubrikerna måste vara: {header_str}', 'danger')
                    return redirect(request.url)

                imported_count = 0
                for row in reader:
                    if len(row) == 7:
                        existing_company = Company.query.filter_by(tax_number=row[2]).first()
                        if existing_company:
                            continue

                        new_company = Company(
                            name=row[0], address=row[1], tax_number=row[2],
                            bank_account=row[3], contact_person=row[4],
                            email=row[5], phone=row[6]
                        )
                        db.session.add(new_company)
                        imported_count += 1
                db.session.commit()
                flash(f'{imported_count} företag har importerats.', 'success')
                return redirect(url_for('companies'))
            except Exception as e:
                db.session.rollback()
                flash(f'Ett fel uppstod vid bearbetning av CSV-filen: {e}', 'danger')
                return redirect(request.url)
        else:
            flash('Endast CSV-filer kan importeras!', 'danger')
            return redirect(request.url)
    return render_template('import_companies.html')


@app.route('/cegek/export')
def export_companies():
    si = io.StringIO()
    cw = csv.writer(si)
    header = ['Namn', 'Adress', 'Organisationsnummer', 'Bankkontonummer', 'Kontaktperson', 'E-post', 'Telefon']
    cw.writerow(header)
    companies = Company.query.all()
    for company in companies:
        cw.writerow([company.name, company.address, company.tax_number, company.bank_account, company.contact_person, company.email, company.phone])
    
    output = io.BytesIO(si.getvalue().encode('utf-8'))
    output.seek(0)
    
    return send_file(output, as_attachment=True, download_name='companies.csv', mimetype='text/csv')

@app.route('/sajat-cegem', methods=['GET', 'POST'])
def owner_company_details():
    company = OwnerCompany.query.first()
    
    if request.method == 'POST':
        try:
            if not company:
                company = OwnerCompany(id=1)
                db.session.add(company)

            company.name = request.form.get('name')
            company.address = request.form.get('address')
            company.tax_number = request.form.get('tax_number')
            company.bank_account = request.form.get('bank_account')
            company.email = request.form.get('email')
            company.phone = request.form.get('phone')
            
            db.session.commit()
            flash('Egna företagsuppgifter har uppdaterats.', 'success')
            return redirect(url_for('owner_company_details'))
        except Exception as e:
            db.session.rollback()
            flash(f'Ett fel uppstod vid sparande: {e}', 'danger')

    return render_template('owner_company.html', company=company)

@app.route('/statisztika')
def statistics():
    total_invoices_count = Invoice.query.count()
    
    total_amount_eur = 0
    invoices_eur = Invoice.query.filter_by(currency='EUR').all()
    for invoice in invoices_eur:
        total_amount_eur += invoice.total_amount

    monthly_stats_raw = db.session.query(
        db.func.strftime('%Y-%m', Invoice.issue_date).label('month'),
        Invoice.id
    ).filter(Invoice.currency == 'EUR').all()

    monthly_stats_dict = {}
    for month, invoice_id in monthly_stats_raw:
        invoice = db.session.get(Invoice, invoice_id)
        if month not in monthly_stats_dict:
            monthly_stats_dict[month] = {'invoice_count': 0, 'total_amount': 0}
        monthly_stats_dict[month]['invoice_count'] += 1
        monthly_stats_dict[month]['total_amount'] += invoice.total_amount
    
    monthly_stats = [{'month': k, **v} for k, v in sorted(monthly_stats_dict.items())]

    return render_template('statistics.html', 
                           total_invoices=total_invoices_count, 
                           total_amount_eur=total_amount_eur,
                           monthly_stats=monthly_stats)

if __name__ == '__main__':
    ui = FlaskUI(
        app=app,
        server="flask",
        width=1200,
        height=800,
        fullscreen=False,
        browser_path=None
    )
    ui.run()
