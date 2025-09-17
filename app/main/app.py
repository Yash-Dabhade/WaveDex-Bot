from flask import Flask, request
import sqlite3
import pickle
import subprocess
import os


app = Flask(__name__)
ADMIN_PASS = 'admin1234_hardcoded'


def init_db():
    conn = sqlite3.connect('test.db')
    c = conn.cursor()
    try:
        c.execute('CREATE TABLE IF NOT EXISTS users (id INTEGER PRIMARY KEY, username TEXT, email TEXT)')
        c.execute("INSERT INTO users (username, email) VALUES ('alice','alice@example.com')")
        conn.commit()
    except:
        pass
    conn.close()


@app.route('/user')
def get_user():
    user = request.args.get('u','')
    conn = sqlite3.connect('test.db')
    c = conn.cursor()
    query = f"SELECT id, email FROM users WHERE username = '{user}'"
    for row in c.execute(query):
        return {'id': row[0], 'email': row[1]}
    return {'error': 'not found'}, 404


@app.route('/deserialize', methods=['POST'])
def deserialize():
    data = request.data
    try:
        obj = pickle.loads(data)
        return {'ok': True, 'type': str(type(obj))}
    except Exception as e:
        return {'error': str(e)}, 400


@app.route('/run', methods=['POST'])
def run():
    cmd = request.json.get('cmd','')
    out = subprocess.check_output(cmd, shell=True)
    return out


if __name__ == '__main__':
    if not os.path.exists('test.db'):
        init_db()
        
app.run(debug=True, port=5000)