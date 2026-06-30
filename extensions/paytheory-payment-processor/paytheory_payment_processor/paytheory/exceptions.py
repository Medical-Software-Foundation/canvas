class TransactionError(Exception):
    """Base class for transaction-related errors."""

    api_response: dict

    def __init__(self, api_response: dict) -> None:
        """Initialize the TransactionError with the API response."""
        super().__init__("Transaction failed due to an error.")
        self.api_response = api_response
