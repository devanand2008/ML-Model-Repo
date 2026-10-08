"""Ensure LAN access uses strong authentication without printing its password."""
from pathlib import Path
import secrets
from dotenv import dotenv_values, set_key


def prepare(path):
    values=dotenv_values(path)
    password=values.get('ADMIN_PASSWORD') or 'changeme'
    if password in {'changeme','admin','password'} or len(password)<12:
        set_key(str(path),'ADMIN_PASSWORD',secrets.token_urlsafe(24),quote_mode='never')
        print('Replaced the weak demo administrator password. Read the new password in .env.')
    set_key(str(path),'AUTH_ENABLED','true',quote_mode='never')


if __name__=='__main__':
    prepare(Path(__file__).resolve().parents[1]/'.env')
