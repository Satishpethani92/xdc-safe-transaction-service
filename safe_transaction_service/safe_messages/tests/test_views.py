import json
import logging
from unittest import mock
from unittest.mock import MagicMock

from django.urls import reverse

import eth_abi
from eth_account import Account
from hexbytes import HexBytes
from rest_framework import status
from rest_framework.exceptions import ErrorDetail
from rest_framework.test import APITestCase
from safe_eth.eth.eip712 import eip712_encode
from safe_eth.safe.safe_signature import SafeSignatureEOA
from safe_eth.safe.signatures import signature_to_bytes
from safe_eth.safe.tests.safe_test_case import SafeTestCaseMixin
from safe_eth.util.util import to_0x_hex_str

from safe_transaction_service.safe_messages.models import (
    SafeMessage,
    SafeMessageConfirmation,
)
from safe_transaction_service.safe_messages.tests.factories import (
    SafeMessageConfirmationFactory,
    SafeMessageFactory,
)
from safe_transaction_service.utils.utils import datetime_to_str

from ..utils import encode_eip191_message, encode_eip712_message
from .mocks import get_eip712_payload_mock

logger = logging.getLogger(__name__)


class TestMessageViews(SafeTestCaseMixin, APITestCase):
    def test_safe_message_view(self):
        random_safe_message_hash = (
            "0x8aca9664752dbae36135fd0956c956fc4a370feeac67485b49bcd4b99608ae41"
        )
        response = self.client.get(
            reverse("v1:safe_messages:message", args=(random_safe_message_hash,))
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(
            response.json(), {"detail": "No SafeMessage matches the given query."}
        )
        safe_message = SafeMessageFactory(safe=self.deploy_test_safe().address)
        response = self.client.get(
            reverse("v1:safe_messages:message", args=(safe_message.message_hash,))
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(
            response.json(),
            {
                "created": datetime_to_str(safe_message.created),
                "modified": datetime_to_str(safe_message.modified),
                "safe": safe_message.safe,
                "messageHash": safe_message.message_hash,
                "message": safe_message.message,
                "proposedBy": safe_message.proposed_by,
                "safeAppId": safe_message.safe_app_id,
                "origin": json.dumps(safe_message.origin),
                "preparedSignature": None,
                "confirmations": [],
            },
        )

        # Add a confirmation
        safe_message_confirmation = SafeMessageConfirmationFactory(
            safe_message=safe_message
        )
        response = self.client.get(
            reverse("v1:safe_messages:message", args=(safe_message.message_hash,))
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(
            response.json(),
            {
                "created": datetime_to_str(safe_message.created),
                "modified": datetime_to_str(safe_message.modified),
                "safe": safe_message.safe,
                "messageHash": safe_message.message_hash,
                "message": safe_message.message,
                "proposedBy": safe_message.proposed_by,
                "safeAppId": safe_message.safe_app_id,
                "origin": json.dumps(safe_message.origin),
                "preparedSignature": to_0x_hex_str(safe_message_confirmation.signature),
                "confirmations": [
                    {
                        "created": datetime_to_str(safe_message_confirmation.created),
                        "modified": datetime_to_str(safe_message_confirmation.modified),
                        "owner": safe_message_confirmation.owner,
                        "signature": to_0x_hex_str(safe_message_confirmation.signature),
                        "signatureType": "EOA",
                    }
                ],
            },
        )

    def test_safe_message_not_camel_case_view(self):
        safe_message = SafeMessageFactory(safe=self.deploy_test_safe().address)
        safe_message_confirmation = SafeMessageConfirmationFactory(
            safe_message=safe_message
        )
        safe_message.message = {"test_not_camel": 2}
        safe_message.save(update_fields=["message"])

        # Response message should not be camelcased
        response = self.client.get(
            reverse("v1:safe_messages:message", args=(safe_message.message_hash,))
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(
            response.json(),
            {
                "created": datetime_to_str(safe_message.created),
                "modified": datetime_to_str(safe_message.modified),
                "safe": safe_message.safe,
                "messageHash": safe_message.message_hash,
                "message": safe_message.message,
                "proposedBy": safe_message.proposed_by,
                "safeAppId": safe_message.safe_app_id,
                "origin": json.dumps(safe_message.origin),
                "preparedSignature": to_0x_hex_str(safe_message_confirmation.signature),
                "confirmations": [
                    {
                        "created": datetime_to_str(safe_message_confirmation.created),
                        "modified": datetime_to_str(safe_message_confirmation.modified),
                        "owner": safe_message_confirmation.owner,
                        "signature": to_0x_hex_str(safe_message_confirmation.signature),
                        "signatureType": "EOA",
                    }
                ],
            },
        )

    @mock.patch(
        "safe_transaction_service.safe_messages.serializers.get_safe_owners",
    )
    def test_safe_messages_create_view(self, get_owners_mock: MagicMock):
        account = Account.create()
        safe = self.deploy_test_safe()
        safe_address = safe.address
        messages = ["Text to sign message", get_eip712_payload_mock()]
        description = "Testing EIP191 message signing"
        messages_encoded = [
            encode_eip191_message(messages[0]),
            encode_eip712_message(messages[1]),
        ]
        safe_message_hashes = [
            safe.get_message_hash(message_encoded)
            for message_encoded in messages_encoded
        ]
        signatures = [
            to_0x_hex_str(account.unsafe_sign_hash(safe_message_hash)["signature"])
            for safe_message_hash in safe_message_hashes
        ]

        sub_tests = ["create_eip191", "create_eip712"]

        for sub_test, message, safe_message_hash, signature in zip(
            sub_tests, messages, safe_message_hashes, signatures
        ):
            SafeMessage.objects.all().delete()
            get_owners_mock.return_value = []
            with self.subTest(
                sub_test,
                message=message,
                safe_message_hash=safe_message_hash,
                signature=signature,
            ):
                data = {
                    "message": message,
                    "description": description,
                    "signature": signature,
                    "safeAppId": -1,
                }
                response = self.client.post(
                    reverse("v1:safe_messages:safe-messages", args=(safe_address,)),
                    format="json",
                    data=data,
                )
                self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
                self.assertEqual(
                    response.data,
                    {
                        "safe_app_id": [
                            ErrorDetail(
                                string="Ensure this value is greater than or equal to 0.",
                                code="min_value",
                            )
                        ]
                    },
                )

                data.pop("safeAppId")
                response = self.client.post(
                    reverse("v1:safe_messages:safe-messages", args=(safe_address,)),
                    format="json",
                    data=data,
                )
                self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
                self.assertEqual(
                    response.data,
                    {
                        "non_field_errors": [
                            ErrorDetail(
                                string=f"{account.address} is not an owner of the Safe",
                                code="invalid",
                            )
                        ]
                    },
                )

                # Test not valid signature
                with mock.patch.object(
                    SafeSignatureEOA, "is_valid", return_value=False
                ):
                    response = self.client.post(
                        reverse("v1:safe_messages:safe-messages", args=(safe_address,)),
                        format="json",
                        data=data,
                    )
                    self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
                    self.assertEqual(
                        response.data,
                        {
                            "non_field_errors": [
                                ErrorDetail(
                                    string=f'Signature={data["signature"]} for owner={account.address} is not valid',
                                    code="invalid",
                                )
                            ]
                        },
                    )

                get_owners_mock.return_value = [account.address]

                with self.settings(BANNED_EOAS={account.address}):
                    response = self.client.post(
                        reverse("v1:safe_messages:safe-messages", args=(safe_address,)),
                        format="json",
                        data=data,
                    )
                    self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
                    self.assertEqual(
                        response.json(),
                        {
                            "nonFieldErrors": [
                                f"Signer={account.address} is not authorized to interact with the service"
                            ]
                        },
                    )

                response = self.client.post(
                    reverse("v1:safe_messages:safe-messages", args=(safe_address,)),
                    format="json",
                    data=data,
                )
                self.assertEqual(response.status_code, status.HTTP_201_CREATED)
                self.assertEqual(SafeMessage.objects.count(), 1)
                self.assertEqual(SafeMessageConfirmation.objects.count(), 1)

                response = self.client.post(
                    reverse("v1:safe_messages:safe-messages", args=(safe_address,)),
                    format="json",
                    data=data,
                )
                self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
                self.assertEqual(
                    response.data,
                    {
                        "non_field_errors": [
                            ErrorDetail(
                                string=f"Message with hash {to_0x_hex_str(safe_message_hash)} for safe {safe_address} "
                                f"already exists in DB",
                                code="invalid",
                            )
                        ]
                    },
                )

    def _test_safe_messages_create_using_1271_signature_view(self, safe_deployment_fn):
        account = Account.create()
        safe_owner = safe_deployment_fn(owners=[account.address])
        safe = safe_deployment_fn(owners=[safe_owner.address])

        safe_address = safe.address
        message = get_eip712_payload_mock()
        description = "Testing EIP712 message signing"
        message_encoded = b"".join(eip712_encode(message))
        safe_message_hash, safe_message_preimage = safe.get_message_hash_and_preimage(
            message_encoded
        )
        safe_owner_message_hash, _ = safe_owner.get_message_hash_and_preimage(
            safe_message_preimage
        )
        safe_owner_signature = account.unsafe_sign_hash(safe_owner_message_hash)[
            "signature"
        ]

        # Build EIP1271 signature v=0 r=safe v=dynamic_part dynamic_part=size+owner_signature
        signature_1271 = (
            signature_to_bytes(
                0, int.from_bytes(HexBytes(safe_owner.address), byteorder="big"), 65
            )
            + eth_abi.encode(["bytes"], [safe_owner_signature])[32:]
        )

        data = {
            "message": message,
            "description": description,
            "signature": to_0x_hex_str(HexBytes(signature_1271)),
        }
        response = self.client.post(
            reverse("v1:safe_messages:safe-messages", args=(safe_address,)),
            format="json",
            data=data,
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(
            SafeMessage.objects.get().message_hash, to_0x_hex_str(safe_message_hash)
        )
        self.assertEqual(
            SafeMessageConfirmation.objects.get().owner, safe_owner.address
        )

    def test_safe_messages_create_using_1271_signature_v1_3_0_view(self):
        return self._test_safe_messages_create_using_1271_signature_view(
            self.deploy_test_safe_v1_3_0
        )

    def test_safe_messages_create_using_1271_signature_v1_4_1_view(self):
        return self._test_safe_messages_create_using_1271_signature_view(
            self.deploy_test_safe_v1_4_1
        )

    @mock.patch(
        "safe_transaction_service.safe_messages.serializers.get_safe_owners",
        return_value=[],
    )
    def test_safe_message_add_signature_view(self, get_owners_mock: MagicMock):
        # Test not existing message
        safe_message_hash = (
            "0x8aca9664752dbae36135fd0956c956fc4a370feeac67485b49bcd4b99608ae41"
        )
        data = {"signature": "0x12"}
        response = self.client.post(
            reverse("v1:safe_messages:signatures", args=(safe_message_hash,)),
            format="json",
            data=data,
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

        # Test invalid signature
        safe_message = SafeMessageFactory(safe=self.deploy_test_safe().address)
        safe_message_confirmation = SafeMessageConfirmationFactory(
            safe_message=safe_message
        )
        response = self.client.post(
            reverse("v1:safe_messages:signatures", args=(safe_message.message_hash,)),
            format="json",
            data=data,
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertDictEqual(
            response.data,
            {
                "signature": [
                    ErrorDetail(
                        string="Ensure this field has at least 65 hexadecimal chars (not counting 0x).",
                        code="min_length",
                    )
                ]
            },
        )

        # Test same signature
        data["signature"] = to_0x_hex_str(safe_message_confirmation.signature)
        response = self.client.post(
            reverse("v1:safe_messages:signatures", args=(safe_message.message_hash,)),
            format="json",
            data=data,
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            response.data,
            {
                "non_field_errors": [
                    ErrorDetail(
                        string=f"Signature for owner {safe_message_confirmation.owner} already exists",
                        code="invalid",
                    )
                ]
            },
        )

        # Test not existing owner
        owner_account = Account.create()
        data["signature"] = to_0x_hex_str(
            owner_account.unsafe_sign_hash(safe_message.message_hash)["signature"]
        )
        response = self.client.post(
            reverse("v1:safe_messages:signatures", args=(safe_message.message_hash,)),
            format="json",
            data=data,
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            response.data,
            {
                "non_field_errors": [
                    ErrorDetail(
                        string=f"{owner_account.address} is not an owner of the Safe",
                        code="invalid",
                    )
                ]
            },
        )

        # Test valid owner
        get_owners_mock.return_value = [owner_account.address]
        response = self.client.post(
            reverse("v1:safe_messages:signatures", args=(safe_message.message_hash,)),
            format="json",
            data=data,
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(SafeMessage.objects.count(), 1)
        self.assertEqual(SafeMessageConfirmation.objects.count(), 2)
        safe_message_confirmation = SafeMessageConfirmation.objects.get(
            safe_message__safe=safe_message.safe, owner=owner_account.address
        )

        # Check SafeMessage modified was updated with new signature
        safe_message_modified = safe_message.modified
        safe_message.refresh_from_db()
        self.assertGreater(safe_message.modified, safe_message_modified)
        self.assertEqual(safe_message_confirmation.modified, safe_message.modified)

    def test_safe_messages_list_view(self):
        safe_address = Account.create().address
        response = self.client.get(
            reverse("v1:safe_messages:safe-messages", args=(safe_address,))
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(
            response.json(), {"count": 0, "next": None, "previous": None, "results": []}
        )

        # Create a Safe message for a random Safe, it should not appear
        safe_message = SafeMessageFactory(safe=self.deploy_test_safe().address)
        response = self.client.get(
            reverse("v1:safe_messages:safe-messages", args=(safe_address,))
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(
            response.json(), {"count": 0, "next": None, "previous": None, "results": []}
        )

        response = self.client.get(
            reverse("v1:safe_messages:safe-messages", args=(safe_message.safe,))
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(
            response.json(),
            {
                "count": 1,
                "next": None,
                "previous": None,
                "results": [
                    {
                        "created": datetime_to_str(safe_message.created),
                        "modified": datetime_to_str(safe_message.modified),
                        "safe": safe_message.safe,
                        "messageHash": safe_message.message_hash,
                        "message": safe_message.message,
                        "proposedBy": safe_message.proposed_by,
                        "safeAppId": safe_message.safe_app_id,
                        "origin": json.dumps(safe_message.origin),
                        "preparedSignature": None,
                        "confirmations": [],
                    }
                ],
            },
        )

        # Add a confirmation
        safe_message_confirmation = SafeMessageConfirmationFactory(
            safe_message=safe_message
        )
        response = self.client.get(
            reverse("v1:safe_messages:safe-messages", args=(safe_message.safe,))
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(
            response.json(),
            {
                "count": 1,
                "next": None,
                "previous": None,
                "results": [
                    {
                        "created": datetime_to_str(safe_message.created),
                        "modified": datetime_to_str(safe_message.modified),
                        "safe": safe_message.safe,
                        "messageHash": safe_message.message_hash,
                        "message": safe_message.message,
                        "proposedBy": safe_message.proposed_by,
                        "safeAppId": safe_message.safe_app_id,
                        "origin": json.dumps(safe_message.origin),
                        "preparedSignature": to_0x_hex_str(
                            safe_message_confirmation.signature
                        ),
                        "confirmations": [
                            {
                                "created": datetime_to_str(
                                    safe_message_confirmation.created
                                ),
                                "modified": datetime_to_str(
                                    safe_message_confirmation.modified
                                ),
                                "owner": safe_message_confirmation.owner,
                                "signature": to_0x_hex_str(
                                    safe_message_confirmation.signature
                                ),
                                "signatureType": "EOA",
                            }
                        ],
                    }
                ],
            },
        )

    def test_safe_messages_list_not_camel_case_view(self):
        safe_message = SafeMessageFactory(safe=self.deploy_test_safe().address)
        safe_message_confirmation = SafeMessageConfirmationFactory(
            safe_message=safe_message
        )
        safe_message.message = {"test_not_camel": 2}
        safe_message.save(update_fields=["message"])

        # Response message should not be camelcased
        response = self.client.get(
            reverse("v1:safe_messages:safe-messages", args=(safe_message.safe,))
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(
            response.json(),
            {
                "count": 1,
                "next": None,
                "previous": None,
                "results": [
                    {
                        "created": datetime_to_str(safe_message.created),
                        "modified": datetime_to_str(safe_message.modified),
                        "safe": safe_message.safe,
                        "messageHash": safe_message.message_hash,
                        "message": safe_message.message,
                        "proposedBy": safe_message.proposed_by,
                        "safeAppId": safe_message.safe_app_id,
                        "origin": json.dumps(safe_message.origin),
                        "preparedSignature": to_0x_hex_str(
                            safe_message_confirmation.signature
                        ),
                        "confirmations": [
                            {
                                "created": datetime_to_str(
                                    safe_message_confirmation.created
                                ),
                                "modified": datetime_to_str(
                                    safe_message_confirmation.modified
                                ),
                                "owner": safe_message_confirmation.owner,
                                "signature": to_0x_hex_str(
                                    safe_message_confirmation.signature
                                ),
                                "signatureType": "EOA",
                            }
                        ],
                    }
                ],
            },
        )

    def test_safe_message_view_v1_1_1(self):
        random_safe_message_hash = (
            "0x8aca9664752dbae36135fd0956c956fc4a370feeac67485b49bcd4b99608ae41"
        )
        response = self.client.get(
            reverse("v1:safe_messages:message", args=(random_safe_message_hash,))
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(
            response.json(), {"detail": "No SafeMessage matches the given query."}
        )
        safe_message = SafeMessageFactory(safe=self.deploy_test_safe_v1_1_1().address)
        response = self.client.get(
            reverse("v1:safe_messages:message", args=(safe_message.message_hash,))
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(
            response.json(),
            {
                "created": datetime_to_str(safe_message.created),
                "modified": datetime_to_str(safe_message.modified),
                "safe": safe_message.safe,
                "messageHash": safe_message.message_hash,
                "message": safe_message.message,
                "proposedBy": safe_message.proposed_by,
                "safeAppId": safe_message.safe_app_id,
                "origin": json.dumps(safe_message.origin),
                "preparedSignature": None,
                "confirmations": [],
            },
        )

        # Add a confirmation
        safe_message_confirmation = SafeMessageConfirmationFactory(
            safe_message=safe_message
        )
        response = self.client.get(
            reverse("v1:safe_messages:message", args=(safe_message.message_hash,))
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(
            response.json(),
            {
                "created": datetime_to_str(safe_message.created),
                "modified": datetime_to_str(safe_message.modified),
                "safe": safe_message.safe,
                "messageHash": safe_message.message_hash,
                "message": safe_message.message,
                "proposedBy": safe_message.proposed_by,
                "safeAppId": safe_message.safe_app_id,
                "origin": json.dumps(safe_message.origin),
                "preparedSignature": to_0x_hex_str(safe_message_confirmation.signature),
                "confirmations": [
                    {
                        "created": datetime_to_str(safe_message_confirmation.created),
                        "modified": datetime_to_str(safe_message_confirmation.modified),
                        "owner": safe_message_confirmation.owner,
                        "signature": to_0x_hex_str(safe_message_confirmation.signature),
                        "signatureType": "EOA",
                    }
                ],
            },
        )
