from typing import Dict, Any, Type
from .abstract_biller import AbstractBiller
from .electricity import ElectricityBiller
from .internet import InternetBiller
from ..core.errors import ValidationError
from .abstract_biller import PaymentResponse
from .abstract_biller import CustomerInfo

class AirtimeBiller(AbstractBiller):
    """Simple airtime biller implementation for MTN, Airtel, Glo, 9mobile."""
    
    async def validate_customer(self, account_number: str):
        # For airtime, we just validate phone number format
        if not account_number.isdigit() or len(account_number) != 11:
            raise ValidationError("Invalid phone number format")
        
        return CustomerInfo(
            account_number=account_number,
            customer_name="Airtime Customer",
            account_status="active"
        )
    
    async def process_payment(self, payment_request):
        # Simulate airtime purchase
        return PaymentResponse(
            success=True,
            transaction_reference=payment_request.reference,
            external_reference=f"AIR_{payment_request.reference}",
            message="Airtime purchase successful"
        )
    
    async def check_transaction_status(self, reference: str):
        return {
            "status": "completed",
            "message": "Airtime purchase completed"
        }

class WaterBiller(AbstractBiller):
    """Water biller implementation for water utility companies."""
    
    async def validate_customer(self, account_number: str):
        # Basic validation for water account numbers
        if len(account_number) < 6:
            raise ValidationError("Invalid water account number")
        
        from .abstract_biller import CustomerInfo
        return CustomerInfo(
            account_number=account_number,
            customer_name="Water Customer",
            account_status="active"
        )
    
    async def process_payment(self, payment_request):
        from .abstract_biller import PaymentResponse
        return PaymentResponse(
            success=True,
            transaction_reference=payment_request.reference,
            external_reference=f"WAT_{payment_request.reference}",
            message="Water bill payment successful"
        )
    
    async def check_transaction_status(self, reference: str):
        return {
            "status": "completed",
            "message": "Water bill payment completed"
        }

class BillerProviderFactory:
    """Factory class to create appropriate biller instances based on bill type and provider."""
    
    # Mapping of bill types to their corresponding biller classes
    BILLER_CLASSES: Dict[str, Type[AbstractBiller]] = {
        "electricity": ElectricityBiller,
        "internet": InternetBiller,
        "cable_tv": InternetBiller,  # Cable TV uses same as internet
        "airtime": AirtimeBiller,
        "data": AirtimeBiller,  # Data uses same as airtime
        "water": WaterBiller
    }
    
    # Provider-specific configurations
    PROVIDER_CONFIGS = {
        # Electricity providers
        "IKEDC": {
            "bill_type": "electricity",
            "provider_code": "IKEDC",
            "name": "Ikeja Electric",
            "service_type": "prepaid"
        },
        "EKEDC": {
            "bill_type": "electricity",
            "provider_code": "EKEDC",
            "name": "Eko Electric",
            "service_type": "prepaid"
        },
        
        # Internet/Cable providers
        "DSTV": {
            "bill_type": "cable_tv",
            "provider_code": "DSTV",
            "name": "DSTV",
            "service_category": "cable_tv"
        },
        "GOTV": {
            "bill_type": "cable_tv",
            "provider_code": "GOTV",
            "name": "GOtv",
            "service_category": "cable_tv"
        },
        "SPECTRANET": {
            "bill_type": "internet",
            "provider_code": "SPECTRANET",
            "name": "Spectranet",
            "service_category": "internet"
        },
        
        # Telecom providers
        "MTN": {
            "bill_type": "airtime",
            "provider_code": "MTN",
            "name": "MTN Nigeria"
        },
        "AIRTEL": {
            "bill_type": "airtime",
            "provider_code": "AIRTEL",
            "name": "Airtel Nigeria"
        },
        "GLO": {
            "bill_type": "airtime",
            "provider_code": "GLO",
            "name": "Globacom"
        },
        "9MOBILE": {
            "bill_type": "airtime",
            "provider_code": "9MOBILE",
            "name": "9mobile"
        },
        
        # Water providers
        "LAGOS_WATER": {
            "bill_type": "water",
            "provider_code": "LAGOS_WATER",
            "name": "Lagos Water Corporation"
        }
    }
    
    @classmethod
    def create_biller(cls, biller_code: str, additional_config: Dict[str, Any] = None) -> AbstractBiller:
        """Create a biller instance based on the biller code.
        
        Args:
            biller_code: The unique code for the biller (e.g., 'IKEDC', 'DSTV')
            additional_config: Additional configuration to override defaults
            
        Returns:
            AbstractBiller: Configured biller instance
            
        Raises:
            ValidationError: If biller code is not supported
        """
        if biller_code not in cls.PROVIDER_CONFIGS:
            raise ValidationError(f"Unsupported biller: {biller_code}")
        
        # Get base configuration for the provider
        config = cls.PROVIDER_CONFIGS[biller_code].copy()
        
        # Override with additional config if provided
        if additional_config:
            config.update(additional_config)
        
        # Get the bill type to determine which biller class to use
        bill_type = config["bill_type"]
        
        if bill_type not in cls.BILLER_CLASSES:
            raise ValidationError(f"Unsupported bill type: {bill_type}")
        
        # Create and return the biller instance
        biller_class = cls.BILLER_CLASSES[bill_type]
        return biller_class(config)
    
    @classmethod
    def get_supported_billers(cls) -> Dict[str, Dict[str, Any]]:
        """Get list of all supported billers and their configurations.
        
        Returns:
            Dict containing all supported billers
        """
        return cls.PROVIDER_CONFIGS.copy()
    
    @classmethod
    def get_billers_by_type(cls, bill_type: str) -> Dict[str, Dict[str, Any]]:
        """Get all billers for a specific bill type.
        
        Args:
            bill_type: The type of bill (e.g., 'electricity', 'internet')
            
        Returns:
            Dict containing billers for the specified type
        """
        return {
            code: config for code, config in cls.PROVIDER_CONFIGS.items()
            if config["bill_type"] == bill_type
        }
    
    @classmethod
    def is_biller_supported(cls, biller_code: str) -> bool:
        """Check if a biller is supported.
        
        Args:
            biller_code: The biller code to check
            
        Returns:
            bool: True if biller is supported
        """
        return biller_code in cls.PROVIDER_CONFIGS