from cryptography.fernet import Fernet

def generate_key():
    return Fernet.generate_key()

def encrypt_file(data, key):
    fernet = Fernet(key)
    return fernet.encrypt(data)

def decrypt_file(data, key):
    fernet = Fernet(key)
    return fernet.decrypt(data)
