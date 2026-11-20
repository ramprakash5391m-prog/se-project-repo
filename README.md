# Sports Shop Management System

Flask + SQLite. Logins: customer/cust123, staff/staff123, manager/mgr123, admin/admin123

## Run on your computer
1. Install Python 3 from python.org
2. Open a terminal in this folder
3. pip install -r requirements.txt
4. python app.py
5. Open http://127.0.0.1:5000

The database file (shop.db) is created automatically the first time.

## Put it online (PythonAnywhere, free)
1. Make an account at pythonanywhere.com
2. Files tab > Upload this zip > open a Bash console > unzip sports-shop.zip
3. Web tab > Add a new web app > Manual configuration > pick Python 3.10 or newer
4. Source code: /home/YOURNAME/sports-shop
5. In the console run: pip install --user flask
6. Click the WSGI configuration file link and replace everything with:
   import sys, os
   sys.path.insert(0, '/home/YOURNAME/sports-shop')
   os.environ['SECRET_KEY'] = 'type-any-long-random-text'
   from app import app as application
7. Press the green Reload button
8. Open YOURNAME.pythonanywhere.com

Before sharing the link, change the demo passwords.
