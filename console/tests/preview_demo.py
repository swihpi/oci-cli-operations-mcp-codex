"""Loopback-only fictional preview. This password never protects live data."""
import os
import tempfile
from werkzeug.security import generate_password_hash
from opsconsole.app import create_app

if __name__=='__main__':
    app=create_app({'MODE':'demo','DATABASE':os.path.join(tempfile.mkdtemp(prefix='oci-console-demo-'),'demo.db'),
                    'PASSWORD_HASH':generate_password_hash('demo-console-local'),
                    'SECURE_COOKIE':False,'ALLOWED_ORIGIN':'http://127.0.0.1:8765',
                    'ENABLE_WRITES':False,'START_SCHEDULER':False})
    app.run(host='127.0.0.1',port=8765,debug=False)
