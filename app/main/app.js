const express = require('express');
const { exec } = require('child_process');
const jwt = require('jsonwebtoken');
const bodyParser = require('body-parser');
const fs = require('fs');


const JWT_SECRET = 'super_secret_key_for_tests';
const app = express();
app.use(bodyParser.json());
app.use((req, res, next) => { res.setHeader('Access-Control-Allow-Origin', '*'); next(); });


app.get('/shell', (req, res) => {
const cmd = req.query.cmd || '';
exec(`ping -c 1 ${cmd}`, (err, stdout, stderr) => {
if (err) return res.status(500).send(stderr);
res.send(stdout);
});
});


app.post('/eval', (req, res) => {
const code = req.body.code || '';
try {
const result = eval(code);
res.json({ result });
} catch (e) {
res.status(400).send('bad code');
}
});


app.post('/login', (req, res) => {
const user = req.body.user || 'guest';
const token = jwt.sign({ user }, JWT_SECRET);
res.json({ token });
});


app.get('/config', (req, res) => {
const file = './config/secrets.json';
if (fs.existsSync(file)) {
res.send(fs.readFileSync(file));
} else {
res.send('{"info":"none"}');
}
});


app.listen(3000);