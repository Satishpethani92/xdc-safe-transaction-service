from typing import Any, Optional, Union
from urllib.parse import urlparse

from django import forms
from django.core import exceptions
from django.core.exceptions import ValidationError
from django.utils.translation import gettext as _

from hexbytes import HexBytes
from safe_eth.util.util import to_0x_hex_str
from web3.types import LogReceipt


class HexField(forms.CharField):
    # TODO Move this to safe-eth-py
    default_error_messages = {
        "invalid": _("Enter a valid hexadecimal."),
    }

    def to_python(self, value: Union[str, bytes, memoryview]) -> HexBytes:
        if isinstance(value, bytes):
            return value
        if isinstance(value, memoryview):
            return HexBytes(bytes(value))
        if value in self.empty_values:
            return None

        value = str(value)
        if self.strip:
            try:
                value = HexBytes(value.strip())
            except (TypeError, ValueError) as exc:
                raise exceptions.ValidationError(
                    self.error_messages["invalid"],
                    code="invalid",
                ) from exc
        return value

    def prepare_value(self, value: memoryview) -> str:
        return to_0x_hex_str(bytes(value)) if value else ""


def clean_receipt_log(receipt_log: LogReceipt) -> Optional[dict[str, Any]]:
    """
    Clean receipt log and make them JSON compliant

    :param receipt_log:
    :return:
    """

    parsed_log = {
        "address": receipt_log["address"],
        "data": to_0x_hex_str(receipt_log["data"]),
        "topics": [to_0x_hex_str(topic) for topic in receipt_log["topics"]],
    }
    return parsed_log


def validate_url(url: str) -> None:
    result = urlparse(url)
    if not all(
        (
            result.scheme
            in (
                "http",
                "https",
            ),
            result.netloc,
        )
    ):
        raise ValidationError(f"{url} is not a valid url")
