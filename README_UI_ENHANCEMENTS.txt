UI/UX Enhancements added (no backend logic changed).

Files added/updated (frontend only):
- templates/base_telone.html            (new base template)
- templates/status_telone.html          (student status/dashboard view)
- templates/payment_telone.html         (simulated QR payment page)
- static/css/telone.css                 (new stylesheet)
- static/js/telone.js                   (small JS helpers for QR & simulation)

How to integrate (Flask):
1. In your Flask app, render the new templates where appropriate. Example:
   from flask import render_template, request
   @app.route('/status')
   def status():
       # load student object/dict from your DB/session
       student = {...}  # your existing student object
       return render_template('status_telone.html', student=student, amount_due='50.00')

   @app.route('/payment')
   def payment():
       student = {...}
       return render_template('payment_telone.html', student=student, amount_due='50.00')

   @app.route('/confirm_payment', methods=['POST'])
   def confirm_payment():
       # your existing payment confirmation logic should handle POST 'reg' and 'amount' fields
       reg = request.form.get('reg')
       amount = request.form.get('amount')
       # set payment status accordingly in your existing DB, then redirect or flash message
       return redirect(url_for('status'))

2. If you already have a base.html, you can either extend it or replace the existing base with the new base_telone.html.
3. All templates were written to use common variable names (student.fullname / student.name / student.reg_no / student.regno)
4. No Python files were modified to avoid changing your backend logic.

If you want, I can automatically inject minimal route handlers into your app.py — but you said 'don't alter my information', so I left backend integration manual.