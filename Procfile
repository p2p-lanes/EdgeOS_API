web: gunicorn main:app --workers=2 --threads=3 --worker-class=uvicorn.workers.UvicornWorker --max-requests=1000 --max-requests-jitter=200
send_scheduled_emails: python app/processes/send_scheduled_emails.py
send_reminder_emails: python app/processes/send_reminder_emails.py
auto_approval: python app/processes/auto_approval.py
abandoned_cart: python app/processes/abandoned_cart.py
