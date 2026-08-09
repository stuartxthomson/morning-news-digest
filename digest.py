import os
import smtplib
from email.message import EmailMessage

# Get our Gmail credentials from GitHub Secrets.
email_address = os.environ["EMAIL_ADDRESS"]
app_password = os.environ["EMAIL_APP_PASSWORD"]

# Create a simple test email.
message = EmailMessage()
message["Subject"] = "Morning News Digest — Test"
message["From"] = email_address
message["To"] = email_address

message.set_content(
    """This is a test email from your Morning News Digest.

If you're reading this, GitHub Actions can successfully send email through Gmail.

Next we'll connect this to the actual news digest.
"""
)

# Connect to Gmail's SMTP server.
with smtplib.SMTP_SSL("smtp.gmail.com", 465) as smtp:
    smtp.login(email_address, app_password)
    smtp.send_message(message)

print("Test email sent successfully!")
