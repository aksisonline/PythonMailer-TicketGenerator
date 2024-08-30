from concurrent.futures import ThreadPoolExecutor, as_completed
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.image import MIMEImage
import os
import argparse
from jinja2 import Environment, FileSystemLoader
from dotenv import load_dotenv
import hashlib
import psycopg2
from email_sender import EmailSender
from ssh_tunnel_manager import SSHTunnelManager
from variables_mapping import column_mapping
from qr_generator import generate_qr_code
from ticket_editor import qr_barbie
from uid_generator import encrypter
import logging
from tqdm import tqdm
from halo import Halo

# Load environment variables from .env file
load_dotenv()

# Create a logger
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# Create a file handler and set the log file path
log_file = "email_logs.log"
file_handler = logging.FileHandler(log_file)

# Create a formatter and set the format of log messages
formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
file_handler.setFormatter(formatter)

# Add the file handler to the logger
logger.addHandler(file_handler)

# SMTP server configuration
smtp_server = os.getenv("server")
smtp_port = int(os.getenv("port"))
sender_email = os.getenv("sender_email")
sender_password = os.getenv("password")

# SSH tunnel configuration
use_ssh_tunnel = os.getenv('USE_SSH_TUNNEL', 'false').lower() == 'true'
ssh_host = os.getenv("SSH_HOST")
ssh_port = int(os.getenv("SSH_PORT"))
ssh_username = os.getenv("SSH_USERNAME")
ssh_password = os.getenv("SSH_PASSWORD")

# PostgreSQL server configuration
db_host = os.getenv("DB_HOST")
db_port = int(os.getenv("DB_PORT"))
db_user = os.getenv("DB_USER")
db_password = os.getenv("DB_PASSWORD")
db_name = os.getenv("DB_NAME")
table_name = os.getenv("TABLE_NAME")

# Other Info
subject = os.getenv("SUBJECT")

def send_email_to_recipient(recipient_data, template, conn, cur, sent_emails):
    # Prepare email sender
    email_sender = EmailSender(smtp_server, smtp_port, sender_email, sender_password)
    
    try:
        # Encrypt email using encrypter.py
        hash_data = encrypter(recipient_data["recipient_email"])

        # Update the 'hash_data' column in the specified table
        cur.execute(f"UPDATE {table_name} SET hash_data = %s WHERE email = %s", (hash_data, recipient_data["recipient_email"]))
        conn.commit()

        # Render the HTML template with the recipient's data
        html_content = template.render(**{k: recipient_data[column_mapping[k]] for k in column_mapping})

        # Create message container
        msg = MIMEMultipart()
        msg["Subject"] = subject
        msg["To"] = recipient_data["recipient_email"]

        # Attach the HTML content
        msg.attach(MIMEText(html_content, "html"))

        # Generate QR code image
        qr_img_path = f"qr_code.png"
        generate_qr_code(hash_data, qr_img_path)

        qr_ticket = qr_barbie(qr_img_path)

        # Attach the QR code image as File
        with open(qr_ticket, "rb") as f:
            qr_code = MIMEImage(f.read())
            qr_code.add_header("Content-Disposition", "attachment", filename=f"Esp_Ticket_{recipient_data['recipient_name']}.png")
            msg.attach(qr_code)

        # Attach the image as Embed
        with open(qr_ticket, "rb") as f:
            image_data = f.read()
            image = MIMEImage(image_data)
            image.add_header("Content-ID", "<template>")
            image.add_header("Content-Disposition", "inline", filename=os.path.basename(qr_ticket))
            msg.attach(image)

        # # Attach PDF File
        # pdf_file_path = "guidelines_c.pdf"

        # with open(pdf_file_path, "rb") as pdf_file:
        #     pdf_attachment = MIMEApplication(pdf_file.read())
        #     pdf_attachment.add_header("Content-Disposition", "attachment", filename="Guidelines.pdf")
        #     msg.attach(pdf_attachment)

        # Send email
        email_sender.send_email(recipient_data["recipient_email"], msg)

        # Log the message
        logger.info("Mail sent to {}".format(recipient_data["recipient_email"]))

        # Add the email to the sent_emails dictionary
        sent_emails[recipient_data["recipient_email"]] = hash_data
        cur.execute(f"UPDATE {table_name} SET comment = %s WHERE email = %s", ("Mail Sent", recipient_data["recipient_email"]))

    except Exception as e:
        print(f"Error sending mail to {recipient_data['recipient_email']}: {e}")

def send_bulk_emails():
    # Create an SSH tunnel to the PostgreSQL server
    if use_ssh_tunnel:
        ssh_tunnel_manager = SSHTunnelManager(ssh_host, ssh_port, ssh_username, ssh_password, db_host, db_port)
        ssh_tunnel_manager.create_tunnel()

    # Connect to the PostgreSQL database through the SSH tunnel
    conn = psycopg2.connect(
        database=db_name,
        user=db_user,
        password=db_password,
        host=db_host,
        port=db_port
    )

    # Create a cursor object using the connection
    cur = conn.cursor()

    # Load the template environment
    template_dir = os.path.dirname(__file__)
    env = Environment(loader=FileSystemLoader(template_dir))
    template = env.get_template(os.getenv("HTML_TEMPLATE"))

    # Create an empty dictionary to store emails and their hash_data
    sent_emails = {}

    # Execute a query to fetch columns from the specified table
    columns = ', '.join([f"{key} AS {value}" for key, value in column_mapping.items()])
    cur.execute(f"SELECT {columns} FROM {table_name} WHERE hash_data IS NULL")

    # Fetch all rows from the result set
    rows = cur.fetchall()

    # Use ThreadPoolExecutor to send emails concurrently
    with ThreadPoolExecutor(max_workers=5) as executor:
        # Initialize the progress bar
        with tqdm(total=len(rows), desc="Sending Emails", unit="email") as pbar:
            futures = []
            for row in rows:
                recipient_data = dict(zip(column_mapping.values(), row))
                future = executor.submit(send_email_to_recipient, recipient_data, template, conn, cur, sent_emails)
                futures.append(future)

            # Wait for all futures to complete and update progress bar
            for future in as_completed(futures):
                future.result()
                pbar.update(1)

    # Close the cursor and the connection
    cur.close()
    conn.close()
    print("Conn closed")

    # Print the sent_emails dictionary
    print("Sent Emails:", sent_emails)

    # Close the SSH tunnel
    if use_ssh_tunnel:
        ssh_tunnel_manager.close_tunnel()

def send_individual_email(name, email):
    # Load environment variables from .env file
    load_dotenv()

    # SMTP server configuration
    smtp_server = os.getenv("server")
    smtp_port = int(os.getenv("port"))
    sender_email = os.getenv("sender_email")
    sender_password = os.getenv("password")

    # Other Info
    subject = os.getenv("SUBJECT")

    # Connect to the PostgreSQL database
    conn = psycopg2.connect(
        database=os.getenv("DB_NAME"),
        user=os.getenv("DB_USER"),
        password=os.getenv("DB_PASSWORD"),
        host=os.getenv("DB_HOST"),
        port=int(os.getenv("DB_PORT"))
    )
    cur = conn.cursor()

    # Encrypt recipient_email using SHA-256
    hash_data = encrypter(email)

    # Insert a new row into the database
    cur.execute(f"INSERT INTO {table_name} (name, email, hash_data) VALUES (%s, %s, %s)", (name, email, hash_data))
    conn.commit()

    # Load the template environment
    template_dir = os.path.dirname(__file__)
    env = Environment(loader=FileSystemLoader(template_dir))
    template = env.get_template(os.getenv("HTML_TEMPLATE"))

    # Render the HTML template with the recipient's data
    html_content = template.render(name=name, email=email)

    # Create message container
    msg = MIMEMultipart()
    msg["Subject"] = subject
    msg["To"] = email

    # Attach the HTML content
    msg.attach(MIMEText(html_content, "html"))

    # Generate QR code image
    qr_img_path = f"qr_code.png"
    generate_qr_code(hash_data, qr_img_path)

    qr_ticket = qr_barbie(qr_img_path)

    # Attach the QR code image as File
    with open(qr_ticket, "rb") as f:
        qr_code = MIMEImage(f.read())
        qr_code.add_header("Content-Disposition", "attachment", filename=f"Esp_Ticket_{name}.png")
        msg.attach(qr_code)

    # Attach the image as Embed
    with open(qr_ticket, "rb") as f:
        image_data = f.read()
        image = MIMEImage(image_data)
        image.add_header("Content-ID", "<template>")
        image.add_header("Content-Disposition", "inline", filename=os.path.basename(qr_ticket))
        msg.attach(image)

    # # Attach PDF File
    # pdf_file_path = "guidelines_c.pdf"

    # with open(pdf_file_path, "rb") as pdf_file:
    #     pdf_attachment = MIMEApplication(pdf_file.read())
    #     pdf_attachment.add_header("Content-Disposition", "attachment", filename="Guidelines.pdf")
    #     msg.attach(pdf_attachment)

    # Send email
    with Halo(text='Sending email...', spinner='dots'):
        email_sender = EmailSender(smtp_server, smtp_port, sender_email, sender_password)
        email_sender.send_email(email, msg)

    # Close the cursor and the connection
    cur.close()
    conn.close()
    print(f"Email sent to {email}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Send bulk emails or individual email.")
    parser.add_argument("--send_bulk", action="store_true", help="Send bulk emails.")
    parser.add_argument("--name", type=str, help="Recipient name for individual email.")
    parser.add_argument("--email", type=str, help="Recipient email for individual email.")

    args = parser.parse_args()

    if args.send_bulk:
        send_bulk_emails()
    elif args.name and args.email:
        send_individual_email(args.name, args.email)
    else:
        print("Please specify either --send_bulk or both --name and --email.")