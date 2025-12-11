import os
import base64
import datetime
from pathlib import Path
from typing import Optional
import httpx
from pydantic import BaseModel
from cryptography.hazmat.primitives import serialization, hashes
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.hazmat.backends import default_backend
from cryptography.exceptions import InvalidSignature


class KalshiClient:
    """Client for interacting with Kalshi API"""
    
    def __init__(
        self,
        api_key_id: Optional[str] = None,
        private_key_path: Optional[str] = None,
        base_url: str = "https://demo-api.kalshi.co"
    ):
        """
        Initialize Kalshi API client
        
        Args:
            api_key_id: Kalshi API key ID (defaults to KALSHI_API_KEY_ID env var)
            private_key_path: Path to private key file (defaults to KALSHI_PRIVATE_KEY_PATH env var)
            base_url: Base URL for Kalshi API (demo or production)
        """
        self.api_key_id = api_key_id or os.getenv("KALSHI_API_KEY_ID")
        if not self.api_key_id:
            raise ValueError("KALSHI_API_KEY_ID must be provided or set as environment variable")
        
        # Default to kalshi_keys directory if path not provided
        if private_key_path is None:
            private_key_path = os.getenv(
                "KALSHI_PRIVATE_KEY_PATH",
                str(Path(__file__).parent / "kalshi_keys" / "gemini-demo.txt")
            )
        
        self.private_key_path = private_key_path
        self.base_url = base_url.rstrip('/')
        self.private_key = self._load_private_key()
    
    def _load_private_key(self) -> rsa.RSAPrivateKey:
        """Load the RSA private key from file"""
        try:
            with open(self.private_key_path, "rb") as key_file:
                private_key = serialization.load_pem_private_key(
                    key_file.read(),
                    password=None,
                    backend=default_backend()
                )
            return private_key
        except FileNotFoundError:
            raise FileNotFoundError(f"Private key file not found at: {self.private_key_path}")
        except Exception as e:
            raise ValueError(f"Failed to load private key: {str(e)}")
    
    def _sign_message(self, message: str) -> str:
        """
        Sign a message using PSS padding with SHA256
        
        Args:
            message: The message string to sign
            
        Returns:
            Base64 encoded signature
        """
        message_bytes = message.encode('utf-8')
        try:
            signature = self.private_key.sign(
                message_bytes,
                padding.PSS(
                    mgf=padding.MGF1(hashes.SHA256()),
                    salt_length=padding.PSS.DIGEST_LENGTH
                ),
                hashes.SHA256()
            )
            return base64.b64encode(signature).decode('utf-8')
        except InvalidSignature as e:
            raise ValueError("RSA sign PSS failed") from e
    
    def _get_headers(self, method: str, path: str) -> dict:
        """
        Generate authentication headers for Kalshi API request
        
        Args:
            method: HTTP method (GET, POST, etc.)
            path: API endpoint path (without query parameters)
            
        Returns:
            Dictionary of headers
        """
        # Strip query parameters from path before signing
        path_without_query = path.split('?')[0]
        
        # Get current timestamp in milliseconds
        current_time = datetime.datetime.now()
        timestamp_ms = int(current_time.timestamp() * 1000)
        timestamp_str = str(timestamp_ms)
        
        # Create message to sign: timestamp + method + path
        message = timestamp_str + method + path_without_query
        signature = self._sign_message(message)
        
        return {
            'KALSHI-ACCESS-KEY': self.api_key_id,
            'KALSHI-ACCESS-SIGNATURE': signature,
            'KALSHI-ACCESS-TIMESTAMP': timestamp_str
        }
    
    async def get_balance(self) -> dict:
        """
        Get account balance from Kalshi API
        
        Returns:
            Dictionary containing balance information
            
        Example response:
            {
                "balance": 10000,
                "portfolio_value": 5000,
                "updated_ts": 1702500000000
            }
        """
        path = '/trade-api/v2/portfolio/balance'
        method = 'GET'
        headers = self._get_headers(method, path)
        
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{self.base_url}{path}",
                headers=headers
            )
            response.raise_for_status()
            return response.json()
    
    async def get_portfolio(self) -> dict:
        """
        Get full portfolio information including positions
        
        Returns:
            Dictionary containing portfolio information
        """
        path = '/trade-api/v2/portfolio'
        method = 'GET'
        headers = self._get_headers(method, path)
        
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{self.base_url}{path}",
                headers=headers
            )
            response.raise_for_status()
            return response.json()


# Response Models
class GetKalshiBalanceResponse(BaseModel):
    """Response model for Kalshi balance endpoint"""
    balance: int  # Member's available balance in cents
    portfolio_value: int  # Member's portfolio value in cents
    updated_ts: int  # Unix timestamp of the last update


# Convenience function for quick balance checks
async def get_account_balance(
    api_key_id: Optional[str] = None,
    private_key_path: Optional[str] = None,
    base_url: str = "https://demo-api.kalshi.co"
) -> dict:
    """
    Convenience function to get account balance
    
    Args:
        api_key_id: Kalshi API key ID (defaults to KALSHI_API_KEY_ID env var)
        private_key_path: Path to private key file (defaults to KALSHI_PRIVATE_KEY_PATH env var)
        base_url: Base URL for Kalshi API
        
    Returns:
        Dictionary containing balance information
    """
    client = KalshiClient(
        api_key_id=api_key_id,
        private_key_path=private_key_path,
        base_url=base_url
    )
    return await client.get_balance()


# Handler for FastAPI endpoint
async def get_kalshi_balance_handler() -> GetKalshiBalanceResponse:
    """
    Handler to get Kalshi account balance
    
    Returns:
        GetKalshiBalanceResponse with balance, portfolio_value, and updated_ts
    """
    client = KalshiClient()
    balance_data = await client.get_balance()
    return GetKalshiBalanceResponse(**balance_data)

