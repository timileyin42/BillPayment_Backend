import hmac
import hashlib
import json
import time
from typing import Dict, Any, Optional, Callable, List, Union
from fastapi import Request, HTTPException, status
from pydantic import BaseModel, Field

from app.core.config import settings
from app.core.errors import WebhookValidationError


class WebhookPayload(BaseModel):
    """Base model for webhook payloads."""
    event_type: str
    timestamp: float = Field(default_factory=lambda: time.time())
    data: Dict[str, Any]


class WebhookSignature:
    """Utility for signing and verifying webhook payloads."""
    
    def __init__(self, secret_key: str):
        """
        Initialize webhook signature utility.
        
        Args:
            secret_key: Secret key for signing
        """
        self.secret_key = secret_key
    
    def generate_signature(self, payload: Union[str, bytes, Dict[str, Any]]) -> str:
        """
        Generate signature for webhook payload.
        
        Args:
            payload: Webhook payload (string, bytes, or dict)
            
        Returns:
            str: Signature hash
        """
        if isinstance(payload, dict):
            payload = json.dumps(payload, separators=(',', ':')).encode()
        elif isinstance(payload, str):
            payload = payload.encode()
        
        return hmac.new(
            key=self.secret_key.encode(),
            msg=payload,
            digestmod=hashlib.sha256
        ).hexdigest()
    
    def verify_signature(self, payload: Union[str, bytes, Dict[str, Any]], signature: str) -> bool:
        """
        Verify webhook signature.
        
        Args:
            payload: Webhook payload
            signature: Signature to verify
            
        Returns:
            bool: True if signature is valid
        """
        expected_signature = self.generate_signature(payload)
        return hmac.compare_digest(expected_signature, signature)


class WebhookDispatcher:
    """Dispatcher for sending webhook events to subscribers."""
    
    def __init__(self, default_secret_key: Optional[str] = None):
        """
        Initialize webhook dispatcher.
        
        Args:
            default_secret_key: Default secret key for signing
        """
        self.default_secret_key = default_secret_key or settings.webhook_secret_key
        self.subscribers: Dict[str, List[Dict[str, Any]]] = {}
    
    def register_subscriber(
        self,
        event_type: str,
        callback_url: str,
        secret_key: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None
    ) -> None:
        """
        Register a subscriber for an event type.
        
        Args:
            event_type: Event type to subscribe to
            callback_url: URL to send webhook to
            secret_key: Secret key for signing (optional)
            metadata: Additional metadata for subscriber
        """
        if event_type not in self.subscribers:
            self.subscribers[event_type] = []
        
        self.subscribers[event_type].append({
            "callback_url": callback_url,
            "secret_key": secret_key or self.default_secret_key,
            "metadata": metadata or {}
        })
    
    def unregister_subscriber(self, event_type: str, callback_url: str) -> bool:
        """
        Unregister a subscriber.
        
        Args:
            event_type: Event type
            callback_url: Callback URL to unregister
            
        Returns:
            bool: True if subscriber was removed
        """
        if event_type not in self.subscribers:
            return False
        
        initial_count = len(self.subscribers[event_type])
        self.subscribers[event_type] = [
            sub for sub in self.subscribers[event_type]
            if sub["callback_url"] != callback_url
        ]
        
        return len(self.subscribers[event_type]) < initial_count
    
    async def dispatch_event(
        self,
        event_type: str,
        data: Dict[str, Any],
        timestamp: Optional[float] = None
    ) -> List[Dict[str, Any]]:
        """
        Dispatch an event to all subscribers.
        
        Args:
            event_type: Event type
            data: Event data
            timestamp: Event timestamp (optional)
            
        Returns:
            List[Dict[str, Any]]: List of dispatch results
        """
        if event_type not in self.subscribers:
            return []
        
        payload = WebhookPayload(
            event_type=event_type,
            timestamp=timestamp or time.time(),
            data=data
        )
        
        results = []
        for subscriber in self.subscribers[event_type]:
            result = await self._send_webhook(
                payload=payload,
                subscriber=subscriber
            )
            results.append(result)
        
        return results
    
    async def _send_webhook(
        self,
        payload: WebhookPayload,
        subscriber: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Send webhook to a subscriber.
        
        Args:
            payload: Webhook payload
            subscriber: Subscriber information
            
        Returns:
            Dict[str, Any]: Result of webhook dispatch
        """
        import httpx
        
        callback_url = subscriber["callback_url"]
        secret_key = subscriber["secret_key"]
        
        payload_dict = payload.dict()
        payload_json = json.dumps(payload_dict, separators=(',', ':'))
        
        signature = WebhookSignature(secret_key).generate_signature(payload_json)
        
        headers = {
            "Content-Type": "application/json",
            "X-Webhook-Signature": signature,
            "X-Webhook-Event": payload.event_type
        }
        
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.post(
                    callback_url,
                    headers=headers,
                    content=payload_json
                )
                
                return {
                    "subscriber": subscriber,
                    "success": 200 <= response.status_code < 300,
                    "status_code": response.status_code,
                    "response": response.text
                }
                
        except Exception as e:
            return {
                "subscriber": subscriber,
                "success": False,
                "error": str(e)
            }


async def verify_webhook_signature(request: Request) -> Dict[str, Any]:
    """
    Verify webhook signature from request.
    
    Args:
        request: FastAPI request
        
    Returns:
        Dict[str, Any]: Verified webhook payload
        
    Raises:
        WebhookValidationError: If signature is invalid
    """
    signature = request.headers.get("X-Webhook-Signature")
    if not signature:
        raise WebhookValidationError("Missing webhook signature")
    
    body = await request.body()
    payload_text = body.decode()
    
    webhook_signature = WebhookSignature(settings.webhook_secret_key)
    if not webhook_signature.verify_signature(payload_text, signature):
        raise WebhookValidationError("Invalid webhook signature")
    
    try:
        payload = json.loads(payload_text)
        return payload
    except json.JSONDecodeError:
        raise WebhookValidationError("Invalid JSON payload")


# Global webhook dispatcher instance
_webhook_dispatcher: Optional[WebhookDispatcher] = None


def get_webhook_dispatcher() -> WebhookDispatcher:
    """
    Get global webhook dispatcher instance.
    
    Returns:
        WebhookDispatcher: Global webhook dispatcher
    """
    global _webhook_dispatcher
    if _webhook_dispatcher is None:
        _webhook_dispatcher = WebhookDispatcher()
    return _webhook_dispatcher


async def dispatch_event(
    event_type: str,
    data: Dict[str, Any],
    timestamp: Optional[float] = None
) -> List[Dict[str, Any]]:
    """
    Dispatch an event using global webhook dispatcher.
    
    Args:
        event_type: Event type
        data: Event data
        timestamp: Event timestamp (optional)
        
    Returns:
        List[Dict[str, Any]]: List of dispatch results
    """
    dispatcher = get_webhook_dispatcher()
    return await dispatcher.dispatch_event(event_type, data, timestamp)


# Common event types
class EventTypes:
    """Common webhook event types."""
    PAYMENT_SUCCESSFUL = "payment.successful"
    PAYMENT_FAILED = "payment.failed"
    WALLET_FUNDED = "wallet.funded"
    CASHBACK_AWARDED = "cashback.awarded"
    USER_REGISTERED = "user.registered"
    USER_VERIFIED = "user.verified"
    RECURRING_PAYMENT_CREATED = "recurring_payment.created"
    RECURRING_PAYMENT_EXECUTED = "recurring_payment.executed"
    RECURRING_PAYMENT_FAILED = "recurring_payment.failed"
    BILLER_STATUS_CHANGED = "biller.status_changed"