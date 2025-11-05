"""
Simple Twilio client for sending SMS messages.

Uses only basic HTTP requests to interact with the Twilio API.
"""

import base64
from typing import Dict

import requests
from logger import log


class TwilioClient:
    """Simple client for Twilio SMS operations."""

    def __init__(self, account_sid: str, auth_token: str):
        """
        Initialize Twilio client.

        Args:
            account_sid: Twilio Account SID
            auth_token: Twilio Auth Token
        """
        self.account_sid = account_sid
        self.auth_token = auth_token
        self.base_url = f"https://api.twilio.com/2010-04-01/Accounts/{account_sid}"

    def _get_auth_header(self) -> str:
        """
        Generate HTTP Basic Auth header for Twilio API.

        Returns:
            Base64-encoded authentication string
        """
        credentials = f"{self.account_sid}:{self.auth_token}"
        encoded = base64.b64encode(credentials.encode()).decode()
        return f"Basic {encoded}"

    def send_sms(self, to: str, from_: str, body: str) -> Dict:
        """
        Send an SMS message via Twilio.

        Args:
            to: Recipient phone number in E.164 format (e.g., +1234567890)
            from_: Twilio phone number in E.164 format (e.g., +1234567890)
            body: Message text (up to 1600 characters)

        Returns:
            Dictionary with:
                - success: bool
                - message_sid: str (if successful)
                - error: str (if failed)

        Example:
            >>> client = TwilioClient(account_sid="AC123...", auth_token="abc123...")
            >>> result = client.send_sms(
            ...     to="+15551234567",
            ...     from_="+15559876543",
            ...     body="Hello from Canvas!"
            ... )
            >>> if result["success"]:
            ...     print(f"Message sent: {result['message_sid']}")
        """
        url = f"{self.base_url}/Messages.json"

        headers = {
            "Authorization": self._get_auth_header(),
            "Content-Type": "application/x-www-form-urlencoded",
        }

        data = {
            "To": to,
            "From": from_,
            "Body": body,
        }

        try:
            log.info(f"Sending SMS to {to} from {from_}")
            response = requests.post(url, headers=headers, data=data, timeout=10)

            if response.status_code in (200, 201):
                response_data = response.json()
                message_sid = response_data.get("sid")
                log.info(f"SMS sent successfully: {message_sid}")
                return {
                    "success": True,
                    "message_sid": message_sid,
                    "error": None,
                }
            else:
                error_msg = f"Twilio API error: {response.status_code} - {response.text}"
                log.error(error_msg)
                return {
                    "success": False,
                    "message_sid": None,
                    "error": error_msg,
                }

        except requests.exceptions.Timeout:
            error_msg = "Twilio API request timed out"
            log.error(error_msg)
            return {
                "success": False,
                "message_sid": None,
                "error": error_msg,
            }

        except requests.exceptions.RequestException as e:
            error_msg = f"Twilio API request failed: {str(e)}"
            log.error(error_msg)
            return {
                "success": False,
                "message_sid": None,
                "error": error_msg,
            }

        except Exception as e:
            error_msg = f"Unexpected error sending SMS: {str(e)}"
            log.error(error_msg)
            return {
                "success": False,
                "message_sid": None,
                "error": error_msg,
            }
