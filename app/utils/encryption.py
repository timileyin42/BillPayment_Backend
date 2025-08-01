import base64
import hashlib
import secrets
from typing import Optional, Union, Dict, Any
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.hazmat.primitives.asymmetric import rsa, padding
from cryptography.hazmat.backends import default_backend
import json

from app.core.config import settings
from app.core.errors import EncryptionError, DecryptionError


class SymmetricEncryption:
    """Symmetric encryption using Fernet (AES 128)."""
    
    def __init__(self, key: Optional[bytes] = None):
        """
        Initialize symmetric encryption.
        
        Args:
            key: Encryption key (32 bytes). If None, uses app secret key.
        """
        if key is None:
            key = self._derive_key_from_secret(settings.secret_key)
        
        self.fernet = Fernet(key)
    
    @staticmethod
    def _derive_key_from_secret(secret: str, salt: Optional[bytes] = None) -> bytes:
        """Derive encryption key from secret string.
        
        Args:
            secret: Secret string
            salt: Salt bytes (if None, uses fixed salt)
            
        Returns:
            bytes: Derived key
        """
        if salt is None:
            # Use a fixed salt derived from the secret for consistency
            salt = hashlib.sha256(secret.encode()).digest()[:16]
        
        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=32,
            salt=salt,
            iterations=100000,
            backend=default_backend()
        )
        
        key = base64.urlsafe_b64encode(kdf.derive(secret.encode()))
        return key
    
    @staticmethod
    def generate_key() -> bytes:
        """Generate a new encryption key.
        
        Returns:
            bytes: New encryption key
        """
        return Fernet.generate_key()
    
    def encrypt(self, data: Union[str, bytes, Dict[str, Any]]) -> str:
        """Encrypt data.
        
        Args:
            data: Data to encrypt (string, bytes, or JSON-serializable dict)
            
        Returns:
            str: Base64-encoded encrypted data
            
        Raises:
            EncryptionError: If encryption fails
        """
        try:
            if isinstance(data, dict):
                data = json.dumps(data, separators=(',', ':'))
            
            if isinstance(data, str):
                data = data.encode('utf-8')
            
            encrypted_data = self.fernet.encrypt(data)
            return base64.urlsafe_b64encode(encrypted_data).decode('utf-8')
            
        except Exception as e:
            raise EncryptionError(f"Failed to encrypt data: {e}")
    
    def decrypt(self, encrypted_data: str, return_json: bool = False) -> Union[str, bytes, Dict[str, Any]]:
        """Decrypt data.
        
        Args:
            encrypted_data: Base64-encoded encrypted data
            return_json: Whether to parse result as JSON
            
        Returns:
            Union[str, bytes, Dict]: Decrypted data
            
        Raises:
            DecryptionError: If decryption fails
        """
        try:
            encrypted_bytes = base64.urlsafe_b64decode(encrypted_data.encode('utf-8'))
            decrypted_data = self.fernet.decrypt(encrypted_bytes)
            
            if return_json:
                return json.loads(decrypted_data.decode('utf-8'))
            
            try:
                return decrypted_data.decode('utf-8')
            except UnicodeDecodeError:
                return decrypted_data
                
        except Exception as e:
            raise DecryptionError(f"Failed to decrypt data: {e}")
    
    def encrypt_dict(self, data: Dict[str, Any]) -> str:
        """Encrypt dictionary data.
        
        Args:
            data: Dictionary to encrypt
            
        Returns:
            str: Encrypted data
        """
        return self.encrypt(data)
    
    def decrypt_dict(self, encrypted_data: str) -> Dict[str, Any]:
        """Decrypt dictionary data.
        
        Args:
            encrypted_data: Encrypted data
            
        Returns:
            Dict[str, Any]: Decrypted dictionary
        """
        return self.decrypt(encrypted_data, return_json=True)


class AsymmetricEncryption:
    """Asymmetric encryption using RSA."""
    
    def __init__(self, private_key: Optional[bytes] = None, public_key: Optional[bytes] = None):
        """
        Initialize asymmetric encryption.
        
        Args:
            private_key: Private key in PEM format
            public_key: Public key in PEM format
        """
        self.private_key = None
        self.public_key = None
        
        if private_key:
            self.private_key = serialization.load_pem_private_key(
                private_key,
                password=None,
                backend=default_backend()
            )
        
        if public_key:
            self.public_key = serialization.load_pem_public_key(
                public_key,
                backend=default_backend()
            )
    
    @staticmethod
    def generate_key_pair(key_size: int = 2048) -> tuple[bytes, bytes]:
        """Generate RSA key pair.
        
        Args:
            key_size: Key size in bits
            
        Returns:
            tuple: (private_key_pem, public_key_pem)
        """
        private_key = rsa.generate_private_key(
            public_exponent=65537,
            key_size=key_size,
            backend=default_backend()
        )
        
        private_pem = private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption()
        )
        
        public_key = private_key.public_key()
        public_pem = public_key.public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo
        )
        
        return private_pem, public_pem
    
    def encrypt_with_public_key(self, data: Union[str, bytes]) -> str:
        """Encrypt data with public key.
        
        Args:
            data: Data to encrypt
            
        Returns:
            str: Base64-encoded encrypted data
            
        Raises:
            EncryptionError: If encryption fails
        """
        if not self.public_key:
            raise EncryptionError("Public key not available")
        
        try:
            if isinstance(data, str):
                data = data.encode('utf-8')
            
            encrypted_data = self.public_key.encrypt(
                data,
                padding.OAEP(
                    mgf=padding.MGF1(algorithm=hashes.SHA256()),
                    algorithm=hashes.SHA256(),
                    label=None
                )
            )
            
            return base64.urlsafe_b64encode(encrypted_data).decode('utf-8')
            
        except Exception as e:
            raise EncryptionError(f"Failed to encrypt with public key: {e}")
    
    def decrypt_with_private_key(self, encrypted_data: str) -> str:
        """Decrypt data with private key.
        
        Args:
            encrypted_data: Base64-encoded encrypted data
            
        Returns:
            str: Decrypted data
            
        Raises:
            DecryptionError: If decryption fails
        """
        if not self.private_key:
            raise DecryptionError("Private key not available")
        
        try:
            encrypted_bytes = base64.urlsafe_b64decode(encrypted_data.encode('utf-8'))
            
            decrypted_data = self.private_key.decrypt(
                encrypted_bytes,
                padding.OAEP(
                    mgf=padding.MGF1(algorithm=hashes.SHA256()),
                    algorithm=hashes.SHA256(),
                    label=None
                )
            )
            
            return decrypted_data.decode('utf-8')
            
        except Exception as e:
            raise DecryptionError(f"Failed to decrypt with private key: {e}")


class FieldEncryption:
    """Utility for encrypting specific database fields."""
    
    def __init__(self, encryption_key: Optional[str] = None):
        """
        Initialize field encryption.
        
        Args:
            encryption_key: Encryption key (if None, uses app secret)
        """
        key = encryption_key or settings.secret_key
        self.symmetric = SymmetricEncryption(
            SymmetricEncryption._derive_key_from_secret(key)
        )
    
    def encrypt_pii(self, data: str) -> str:
        """Encrypt personally identifiable information.
        
        Args:
            data: PII data to encrypt
            
        Returns:
            str: Encrypted data
        """
        return self.symmetric.encrypt(data)
    
    def decrypt_pii(self, encrypted_data: str) -> str:
        """Decrypt personally identifiable information.
        
        Args:
            encrypted_data: Encrypted PII data
            
        Returns:
            str: Decrypted data
        """
        return self.symmetric.decrypt(encrypted_data)
    
    def encrypt_sensitive_data(self, data: Dict[str, Any]) -> str:
        """Encrypt sensitive data dictionary.
        
        Args:
            data: Sensitive data to encrypt
            
        Returns:
            str: Encrypted data
        """
        return self.symmetric.encrypt_dict(data)
    
    def decrypt_sensitive_data(self, encrypted_data: str) -> Dict[str, Any]:
        """Decrypt sensitive data dictionary.
        
        Args:
            encrypted_data: Encrypted sensitive data
            
        Returns:
            Dict[str, Any]: Decrypted data
        """
        return self.symmetric.decrypt_dict(encrypted_data)


class HashingUtility:
    """Utility for hashing and verification."""
    
    @staticmethod
    def hash_password(password: str, salt: Optional[bytes] = None) -> tuple[str, str]:
        """Hash password with salt.
        
        Args:
            password: Password to hash
            salt: Salt bytes (if None, generates new salt)
            
        Returns:
            tuple: (hashed_password, salt_base64)
        """
        if salt is None:
            salt = secrets.token_bytes(32)
        
        pwdhash = hashlib.pbkdf2_hmac(
            'sha256',
            password.encode('utf-8'),
            salt,
            100000
        )
        
        return (
            base64.urlsafe_b64encode(pwdhash).decode('utf-8'),
            base64.urlsafe_b64encode(salt).decode('utf-8')
        )
    
    @staticmethod
    def verify_password(password: str, hashed_password: str, salt: str) -> bool:
        """Verify password against hash.
        
        Args:
            password: Password to verify
            hashed_password: Stored password hash
            salt: Stored salt
            
        Returns:
            bool: True if password matches
        """
        try:
            salt_bytes = base64.urlsafe_b64decode(salt.encode('utf-8'))
            expected_hash, _ = HashingUtility.hash_password(password, salt_bytes)
            return secrets.compare_digest(expected_hash, hashed_password)
        except Exception:
            return False
    
    @staticmethod
    def hash_data(data: Union[str, bytes], algorithm: str = 'sha256') -> str:
        """Hash data using specified algorithm.
        
        Args:
            data: Data to hash
            algorithm: Hash algorithm ('sha256', 'sha512', 'md5')
            
        Returns:
            str: Hexadecimal hash
        """
        if isinstance(data, str):
            data = data.encode('utf-8')
        
        if algorithm == 'sha256':
            return hashlib.sha256(data).hexdigest()
        elif algorithm == 'sha512':
            return hashlib.sha512(data).hexdigest()
        elif algorithm == 'md5':
            return hashlib.md5(data).hexdigest()
        else:
            raise ValueError(f"Unsupported algorithm: {algorithm}")
    
    @staticmethod
    def generate_secure_token(length: int = 32) -> str:
        """Generate cryptographically secure random token.
        
        Args:
            length: Token length in bytes
            
        Returns:
            str: Base64-encoded token
        """
        return base64.urlsafe_b64encode(secrets.token_bytes(length)).decode('utf-8')
    
    @staticmethod
    def generate_api_key() -> str:
        """Generate API key.
        
        Returns:
            str: API key
        """
        return f"bp_{HashingUtility.generate_secure_token(24)}"


# Global instances
_symmetric_encryption: Optional[SymmetricEncryption] = None
_field_encryption: Optional[FieldEncryption] = None
_hashing_utility: Optional[HashingUtility] = None


def get_symmetric_encryption() -> SymmetricEncryption:
    """Get global symmetric encryption instance.
    
    Returns:
        SymmetricEncryption: Global instance
    """
    global _symmetric_encryption
    if _symmetric_encryption is None:
        _symmetric_encryption = SymmetricEncryption()
    return _symmetric_encryption


def get_field_encryption() -> FieldEncryption:
    """Get global field encryption instance.
    
    Returns:
        FieldEncryption: Global instance
    """
    global _field_encryption
    if _field_encryption is None:
        _field_encryption = FieldEncryption()
    return _field_encryption


def get_hashing_utility() -> HashingUtility:
    """Get global hashing utility instance.
    
    Returns:
        HashingUtility: Global instance
    """
    global _hashing_utility
    if _hashing_utility is None:
        _hashing_utility = HashingUtility()
    return _hashing_utility


# Convenience functions
def encrypt_data(data: Union[str, bytes, Dict[str, Any]]) -> str:
    """Encrypt data using global symmetric encryption.
    
    Args:
        data: Data to encrypt
        
    Returns:
        str: Encrypted data
    """
    return get_symmetric_encryption().encrypt(data)


def decrypt_data(encrypted_data: str, return_json: bool = False) -> Union[str, bytes, Dict[str, Any]]:
    """Decrypt data using global symmetric encryption.
    
    Args:
        encrypted_data: Encrypted data
        return_json: Whether to parse as JSON
        
    Returns:
        Union[str, bytes, Dict]: Decrypted data
    """
    return get_symmetric_encryption().decrypt(encrypted_data, return_json)


def encrypt_pii(data: str) -> str:
    """Encrypt PII data.
    
    Args:
        data: PII data
        
    Returns:
        str: Encrypted data
    """
    return get_field_encryption().encrypt_pii(data)


def decrypt_pii(encrypted_data: str) -> str:
    """Decrypt PII data.
    
    Args:
        encrypted_data: Encrypted PII data
        
    Returns:
        str: Decrypted data
    """
    return get_field_encryption().decrypt_pii(encrypted_data)


def hash_password(password: str) -> tuple[str, str]:
    """Hash password.
    
    Args:
        password: Password to hash
        
    Returns:
        tuple: (hashed_password, salt)
    """
    return get_hashing_utility().hash_password(password)


def verify_password(password: str, hashed_password: str, salt: str) -> bool:
    """Verify password.
    
    Args:
        password: Password to verify
        hashed_password: Stored hash
        salt: Stored salt
        
    Returns:
        bool: True if password matches
    """
    return get_hashing_utility().verify_password(password, hashed_password, salt)


def generate_secure_token(length: int = 32) -> str:
    """Generate secure token.
    
    Args:
        length: Token length
        
    Returns:
        str: Secure token
    """
    return get_hashing_utility().generate_secure_token(length)


def generate_api_key() -> str:
    """Generate API key.
    
    Returns:
        str: API key
    """
    return get_hashing_utility().generate_api_key()