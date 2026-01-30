from flask import Flask, render_template, request, redirect, session, url_for, g
import sqlite3
from datetime import datetime, timedelta

app = Flask(__name__)
app.secret_key = 'super_secret_final_key'
DATABASE = 'expense_tracker_final.db'

# --- Database Setup ---
def get_db():
    db = getattr(g, '_database', None)
    if db is None:
        db = g._database = sqlite3.connect(DATABASE)
        db.row_factory = sqlite3.Row
    return db

@app.teardown_appcontext
def close_connection(exception):
    db = getattr(g, '_database', None)
    if db is not None:
        db.close()

def init_db():
    with app.app_context():
        db = get_db()
        db.execute('''
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                email TEXT UNIQUE NOT NULL,
                password TEXT NOT NULL,
                role TEXT NOT NULL,
                budget REAL NOT NULL
            )
        ''')
        db.execute('''
            CREATE TABLE IF NOT EXISTS expenses (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                category TEXT NOT NULL,
                amount REAL NOT NULL,
                date TEXT NOT NULL,
                description TEXT,
                user_id INTEGER NOT NULL,
                FOREIGN KEY (user_id) REFERENCES users (id)
            )
        ''')
        db.commit()

# --- Helper Functions ---
def format_money(amount):
    try:
        currency = session.get('currency', '₹')
    except RuntimeError: 
        currency = '₹'
        
    if amount is None: amount = 0
    
    if currency == '$':
        converted = amount / 87
        return f"${converted:,.2f}"
    else:
        return f"₹{amount:,.2f}"

@app.context_processor
def utility_processor():
    return dict(format_money=format_money, currency=session.get('currency', '₹'))

# --- ROUTES ---

@app.route('/')
def home():
    if 'user_id' in session:
        return redirect(url_for('dashboard'))
    return redirect(url_for('login'))

@app.route('/toggle_currency')
def toggle_currency():
    session['currency'] = '₹' if session.get('currency', '₹') == '$' else '$'
    return redirect(request.referrer or url_for('dashboard'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    error = None
    if request.method == 'POST':
        email = request.form['email']
        password = request.form['password']
        
        db = get_db()
        user = db.execute('SELECT * FROM users WHERE email = ?', (email,)).fetchone()
        
        if user is None:
            error = "User does not exist. Please register."
        elif user['password'] != password:
            error = "Incorrect password."
        else:
            session.clear()
            session['user_id'] = user['id']
            session['user_name'] = user['email'].split('@')[0]
            session['role'] = user['role']
            session['budget'] = user['budget']
            session['currency'] = '₹'
            return redirect(url_for('dashboard'))
            
    return render_template('login.html', error=error)

@app.route('/register', methods=['GET', 'POST'])
def register():
    error = None
    if request.method == 'POST':
        email = request.form['email']
        password = request.form['password']
        role = request.form['role']
        try:
            budget = float(request.form['budget'])
            if not email or not password or not role:
                error = "All fields are required."
            else:
                db = get_db()
                db.execute('INSERT INTO users (email, password, role, budget) VALUES (?, ?, ?, ?)',
                           (email, password, role, budget))
                db.commit()
                return redirect(url_for('login'))
        except ValueError:
            error = "Budget must be a number."
        except sqlite3.IntegrityError:
            error = f"User {email} is already registered."

    return render_template('register.html', error=error)

@app.route('/dashboard')
def dashboard():
    if 'user_id' not in session: return redirect(url_for('login'))
    
    period = request.args.get('period', 'month')
    db = get_db()
    
    today = datetime.now()
    if period == 'week':
        start_date = today - timedelta(days=7)
    elif period == 'year':
        start_date = today - timedelta(days=365)
    else: 
        start_date = today - timedelta(days=30)
        
    start_date_str = start_date.strftime('%Y-%m-%d')
    
    expenses = db.execute(
        'SELECT * FROM expenses WHERE user_id = ? AND date >= ? ORDER BY date ASC',
        (session['user_id'], start_date_str)
    ).fetchall()
    
    total_spent = 0
    cat_totals = {}
    date_totals = {}
    
    for e in expenses:
        amt = e['amount']
        total_spent += amt
        cat = e['category']
        cat_totals[cat] = cat_totals.get(cat, 0) + amt
        short_date = e['date'][5:] 
        date_totals[short_date] = date_totals.get(short_date, 0) + amt

    # Prepare raw lists for ChartJS
    chart_dates = list(date_totals.keys())
    chart_daily_amts = list(date_totals.values())
    chart_cats = list(cat_totals.keys())
    chart_cat_amts = list(cat_totals.values())

    # --- NEW: Prepare Top Categories Data for the List ---
    # Convert cat_totals dictionary to a list of dicts for the template loop
    # We sort them by amount to show the biggest spenders first
    top_categories = []
    sorted_cats = sorted(cat_totals.items(), key=lambda item: item[1], reverse=True)
    
    for cat, amount in sorted_cats:
        percentage = int((amount / total_spent) * 100) if total_spent > 0 else 0
        top_categories.append({
            'name': cat,
            'amount': amount,
            'percentage': percentage
        })

    user_budget = session.get('budget', 0)
    display_budget = user_budget
    if period == 'week': display_budget = user_budget / 4
    elif period == 'year': display_budget = user_budget * 12
    
    remaining = display_budget - total_spent
    
    savings_pct = 0
    if display_budget > 0:
        savings_pct = (remaining / display_budget) * 100
    if savings_pct < 0: savings_pct = 0

    return render_template('dashboard.html', 
                           username=session['user_name'], 
                           role=session.get('role', 'Student'),
                           expenses=expenses[::-1][:5], 
                           total_spent=total_spent,
                           budget=display_budget,
                           remaining=remaining,
                           period=period,
                           savings_pct=savings_pct, 
                           chart_dates=chart_dates,
                           chart_daily_amts=chart_daily_amts,
                           chart_cats=chart_cats,
                           chart_cat_amts=chart_cat_amts,
                           top_categories=top_categories) # Passed this new variable

@app.route('/expenses')
def expenses():
    if 'user_id' not in session: return redirect(url_for('login'))
    db = get_db()
    all_expenses = db.execute('SELECT * FROM expenses WHERE user_id = ? ORDER BY date DESC', (session['user_id'],)).fetchall()
    total = db.execute('SELECT SUM(amount) FROM expenses WHERE user_id = ?', (session['user_id'],)).fetchone()[0] or 0
    return render_template('expenses.html', expenses=all_expenses, total_spent=total)

@app.route('/add', methods=['GET', 'POST'])
def add():
    if 'user_id' not in session: return redirect(url_for('login'))
    if request.method == 'POST':
        try:
            category = request.form['category']
            amount = float(request.form['amount'])
            date = request.form['date']
            desc = request.form['description']
            
            db = get_db()
            db.execute('INSERT INTO expenses (category, amount, date, description, user_id) VALUES (?, ?, ?, ?, ?)',
                       (category, amount, date, desc, session['user_id']))
            db.commit()
            return redirect(url_for('expenses'))
        except ValueError:
            pass 
    return render_template('add.html')

# --- NEW ROUTE: DELETE EXPENSE ---
@app.route('/delete/<int:id>')
def delete_expense(id):
    if 'user_id' not in session: return redirect(url_for('login'))
    db = get_db()
    # Ensure user can only delete their own expenses
    db.execute('DELETE FROM expenses WHERE id = ? AND user_id = ?', (id, session['user_id']))
    db.commit()
    return redirect(url_for('expenses'))

@app.route('/ai_analysis')
def ai_analysis():
    if 'user_id' not in session: return redirect(url_for('login'))
    db = get_db()
    all_expenses = db.execute('SELECT * FROM expenses WHERE user_id = ?', (session['user_id'],)).fetchall()
    
    total = sum(e['amount'] for e in all_expenses)
    cat_totals = {}
    for e in all_expenses: cat_totals[e['category']] = cat_totals.get(e['category'], 0) + e['amount']
    
    insights = []
    if total > 0:
        top_cat = max(cat_totals, key=cat_totals.get)
        pct = int((cat_totals[top_cat]/total)*100)
        insights.append(f"📊 **Spending Pattern:** You spend most ({pct}%) on **{top_cat}**.")
        if session.get('role') == 'student' and cat_totals.get('Food', 0) > (total * 0.5):
            insights.append("🍔 **Student Tip:** Spending >50% on food? Try our meal plan optimizer.")
            
    return render_template('analysis.html', insights=insights)

@app.route('/budget_optimizer', methods=['GET', 'POST'])
def budget_optimizer():
    if 'user_id' not in session: return redirect(url_for('login'))
    optimized_plan = False
    advice_list = []
    comparison = {}

    if request.method == 'POST':
        try:
            total = float(request.form.get('total_budget', 0))
            cats = request.form.getlist('categories[]')
            amts = request.form.getlist('amounts[]')
            
            user_plan_total = 0
            user_cats = []
            user_amounts = []
            
            for i in range(len(cats)):
                if cats[i] and amts[i]:
                    val = float(amts[i])
                    user_cats.append(cats[i])
                    user_amounts.append(val)
                    user_plan_total += val

            target_savings = total * 0.20
            available_for_expenses = total * 0.80
            
            scaling_factor = 1.0
            if user_plan_total > available_for_expenses:
                scaling_factor = available_for_expenses / user_plan_total
                reduction_percent = int((1 - scaling_factor) * 100)
                advice_list.append(f"⚠️ Plan exceeded limit. Reduced categories by {reduction_percent}% to ensure savings.")
            
            for i in range(len(user_cats)):
                cat = user_cats[i]
                original = user_amounts[i]
                optimized = original * scaling_factor
                comparison[cat] = {'user': int(original), 'ai': int(optimized)}
                if scaling_factor < 1.0:
                    advice_list.append(f"📉 Reduce **{cat}** from {int(original)} to {int(optimized)}.")

            comparison['Savings'] = {'user': 0, 'ai': int(target_savings)}
            advice_list.append(f"✅ Secured **{format_money(target_savings)}** for your Savings.")
            optimized_plan = True
            
        except ValueError:
            advice_list.append("⚠️ Invalid input numbers.")

    return render_template('optimizer.html', optimized_plan=optimized_plan, advice_list=advice_list, comparison=comparison)

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

if __name__ == '__main__':
    init_db()
    app.run(debug=True)