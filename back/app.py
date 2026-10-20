import os
import secrets
from datetime import datetime, timezone
from functools import wraps
from pathlib import Path

import click
from flask import Flask, abort, flash, g, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash
from werkzeug.utils import secure_filename

from database.conexao import close_db, get_db
from database.init_db import init_db
from importador.pdf_importer import extract_candidates

BASE_DIR = Path(__file__).resolve().parent.parent
app = Flask(__name__,
            template_folder=str(BASE_DIR / 'front' / 'templates'),
            static_folder=str(BASE_DIR / 'front' / 'static'))
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY') or secrets.token_hex(32)
app.config['MAX_CONTENT_LENGTH'] = 8 * 1024 * 1024
app.teardown_appcontext(close_db)


@app.before_request
def load_user_and_csrf():
    g.user = None
    if 'user_id' in session:
        g.user = get_db().execute('SELECT id, username, is_admin FROM users WHERE id=?', (session['user_id'],)).fetchone()
    if '_csrf' not in session:
        session['_csrf'] = secrets.token_hex(24)
    if request.method == 'POST':
        token = request.form.get('_csrf', '')
        if not secrets.compare_digest(token, session['_csrf']):
            abort(400, 'Token de formulário inválido.')


@app.context_processor
def expose_csrf():
    return {'csrf': lambda: session.get('_csrf', '')}


def login_required(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        if g.user is None:
            return redirect(url_for('login'))
        return func(*args, **kwargs)
    return wrapper


def admin_required(func):
    @wraps(func)
    @login_required
    def wrapper(*args, **kwargs):
        if not g.user['is_admin']:
            abort(403)
        return func(*args, **kwargs)
    return wrapper


@app.get('/')
def index():
    return render_template('index.html')


@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form.get('username', '').strip().lower()
        password = request.form.get('password', '')
        if not 3 <= len(username) <= 40 or not 8 <= len(password) <= 128:
            flash('Usuário deve ter 3 a 40 caracteres e senha 8 a 128.', 'error')
        else:
            db = get_db()
            try:
                cursor = db.execute('INSERT INTO users (username, password_hash) VALUES (?, ?)',
                                    (username, generate_password_hash(password)))
                db.commit()
                session.clear()
                session['user_id'] = cursor.lastrowid
                return redirect(url_for('questions'))
            except __import__('sqlite3').IntegrityError:
                flash('Esse usuário já existe.', 'error')
    return render_template('auth.html', mode='register')


@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        user = get_db().execute('SELECT * FROM users WHERE username=?',
                                (request.form.get('username', '').strip().lower(),)).fetchone()
        if user and check_password_hash(user['password_hash'], request.form.get('password', '')):
            session.clear()
            session['user_id'] = user['id']
            return redirect(url_for('questions'))
        flash('Credenciais inválidas.', 'error')
    return render_template('auth.html', mode='login')


@app.post('/logout')
@login_required
def logout():
    session.clear()
    return redirect(url_for('index'))


@app.get('/questions')
@login_required
def questions():
    db = get_db()
    subjects = db.execute("SELECT DISTINCT subject FROM questions WHERE status='published' ORDER BY subject").fetchall()
    subject = request.args.get('subject', '').strip()
    query = "SELECT * FROM questions WHERE status='published'"
    params = []
    if subject:
        query += ' AND subject=?'
        params.append(subject)
    query += ' ORDER BY id LIMIT 100'
    rows = db.execute(query, params).fetchall()
    count = db.execute("SELECT COUNT(*) AS n FROM attempts WHERE user_id=? AND date(created_at)=date('now')", (g.user['id'],)).fetchone()['n']
    return render_template('questions.html', questions=rows, subjects=subjects, current_subject=subject, today=count)


@app.post('/answer/<int:question_id>')
@login_required
def answer(question_id):
    db = get_db()
    question = db.execute("SELECT * FROM questions WHERE id=? AND status='published'", (question_id,)).fetchone()
    if question is None:
        abort(404)
    selected = request.form.get('answer')
    if selected not in ('C', 'E', 'B'):
        abort(400)
    if not g.user['is_admin']:
        count = db.execute("SELECT COUNT(*) AS n FROM attempts WHERE user_id=? AND date(created_at)=date('now')", (g.user['id'],)).fetchone()['n']
        if count >= 20:
            flash('Você atingiu o limite diário demonstrativo de 20 respostas.', 'error')
            return redirect(url_for('questions'))
    correct = int(selected == question['answer']) if question['answer'] in ('C', 'E') else 0
    db.execute('INSERT INTO attempts (user_id, question_id, answer, correct) VALUES (?, ?, ?, ?)',
               (g.user['id'], question_id, selected, correct))
    db.commit()
    result = ('Questão anulada: não contabilize como erro.' if question['answer'] == 'A' else
              'Questão em branco.' if selected == 'B' else
              'Correto!' if correct else 'Incorreto.')
    flash(f"{result} Gabarito: {question['answer']} (C=Certo, E=Errado, A=Anulada).", 'info')
    return redirect(url_for('questions'))


@app.get('/history')
@login_required
def history():
    db = get_db()
    rows = db.execute('''SELECT q.subject, date(a.created_at) AS day, COUNT(*) AS total,
             SUM(a.correct) AS hits FROM attempts a JOIN questions q ON q.id=a.question_id
             WHERE a.user_id=? GROUP BY q.subject, date(a.created_at) ORDER BY day DESC, q.subject''',
             (g.user['id'],)).fetchall()
    return render_template('history.html', rows=rows)


@app.route('/admin', methods=['GET', 'POST'])
@admin_required
def admin():
    db = get_db()
    if request.method == 'POST':
        file = request.files.get('pdf')
        if not file or not file.filename.lower().endswith('.pdf'):
            flash('Selecione um PDF.', 'error')
        else:
            raw = file.read()
            if not raw.startswith(b'%PDF'):
                flash('Arquivo não parece ser um PDF.', 'error')
            else:
                try:
                    candidates = extract_candidates(raw)
                    source = request.form.get('source', '').strip()[:400]
                    for item in candidates:
                        db.execute('''INSERT INTO questions (exam, year, number, statement, source)
                                      VALUES (?, ?, ?, ?, ?)''',
                                   ('PRF', 2021, item['number'], item['statement'], source))
                    db.commit()
                    flash(f'{len(candidates)} candidatos importados. Revise antes de publicar.', 'info')
                except Exception:
                    app.logger.exception('Falha ao extrair PDF')
                    flash('Não foi possível extrair questões do PDF.', 'error')
    pending = db.execute("SELECT * FROM questions WHERE status='pending' ORDER BY id DESC LIMIT 100").fetchall()
    return render_template('admin.html', pending=pending)


@app.post('/admin/review/<int:question_id>')
@admin_required
def review(question_id):
    db = get_db()
    subject = request.form.get('subject', '').strip()[:100]
    statement = request.form.get('statement', '').strip()
    answer_value = request.form.get('answer')
    action = request.form.get('action')
    if not statement or not subject or answer_value not in ('C', 'E', 'A') or action not in ('save', 'publish'):
        abort(400, 'Preencha os dados e o gabarito antes de salvar.')
    db.execute('''UPDATE questions SET subject=?, statement=?, answer=?, status=?
                  WHERE id=? AND status='pending' ''',
               (subject, statement, answer_value, 'published' if action == 'publish' else 'pending', question_id))
    db.commit()
    flash('Questão atualizada.', 'info')
    return redirect(url_for('admin'))


@app.cli.command('init-db')
def init_db_command():
    init_db()
    click.echo('Banco inicializado.')


@app.cli.command('create-admin')
@click.argument('username')
@click.password_option()
def create_admin(username, password):
    db = get_db()
    db.execute('INSERT INTO users (username, password_hash, is_admin) VALUES (?, ?, 1)',
               (username.strip().lower(), generate_password_hash(password)))
    db.commit()
    click.echo('Administrador criado.')


if __name__ == '__main__':
    app.run(debug=os.getenv('FLASK_DEBUG') == '1')
