from django.shortcuts import get_object_or_404

import django_filters
from djangorestframework_camel_case.parser import CamelCaseJSONParser
from djangorestframework_camel_case.render import CamelCaseJSONRenderer
from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import status
from rest_framework.filters import OrderingFilter
from rest_framework.generics import CreateAPIView, ListCreateAPIView, RetrieveAPIView
from rest_framework.response import Response
from safe_eth.eth.utils import fast_is_checksum_address

from . import pagination, serializers
from .models import SafeMessage


class DisableCamelCaseForMessageParser(CamelCaseJSONParser):
    json_underscoreize = {"ignore_fields": ("message",)}


class DisableCamelCaseForMessageRenderer(CamelCaseJSONRenderer):
    json_underscoreize = {"ignore_fields": ("message",)}


class SafeMessageView(RetrieveAPIView):
    """
    Returns detailed information on a message associated with a given message hash
    """

    lookup_url_kwarg = "message_hash"
    queryset = SafeMessage.objects.prefetch_related("confirmations")
    serializer_class = serializers.SafeMessageResponseSerializer
    renderer_classes = (DisableCamelCaseForMessageRenderer,)


class SafeMessageSignatureView(CreateAPIView):
    serializer_class = serializers.SafeMessageSignatureSerializer

    def get_serializer_context(self):
        context = super().get_serializer_context()
        if getattr(self, "swagger_fake_view", False):
            return context

        context["safe_message"] = get_object_or_404(
            SafeMessage, pk=self.kwargs["message_hash"]
        )
        return context

    @extend_schema(
        tags=["messages"],
        responses={201: OpenApiResponse(description="Created")},
    )
    def post(self, request, *args, **kwargs):
        """
        Adds the signature of a message given its message hash

        Note: Safe must be v1.4.1 for EIP-1271 signatures to work.
        """
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        self.perform_create(serializer)
        return Response(status=status.HTTP_201_CREATED)


class SafeMessagesView(ListCreateAPIView):
    filter_backends = [
        django_filters.rest_framework.DjangoFilterBackend,
        OrderingFilter,
    ]
    ordering = ["-created"]
    ordering_fields = ["created", "modified"]
    pagination_class = pagination.DefaultPagination
    parser_classes = (DisableCamelCaseForMessageParser,)
    renderer_classes = (DisableCamelCaseForMessageRenderer,)

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return SafeMessage.objects.none()

        safe = self.kwargs["address"]
        return SafeMessage.objects.filter(safe=safe).prefetch_related("confirmations")

    def get_serializer_context(self):
        context = super().get_serializer_context()
        context["safe_address"] = self.kwargs["address"]
        return context

    def get_serializer_class(self):
        if self.request.method == "GET":
            return serializers.SafeMessageResponseSerializer
        elif self.request.method == "POST":
            return serializers.SafeMessageSerializer

    @extend_schema(
        tags=["messages"],
        responses={200: serializers.SafeMessageResponseSerializer},
    )
    def get(self, request, address, *args, **kwargs):
        """
        Returns the list of messages for a given Safe account
        """
        if not fast_is_checksum_address(address):
            return Response(
                status=status.HTTP_422_UNPROCESSABLE_ENTITY,
                data={
                    "code": 1,
                    "message": "Checksum address validation failed",
                    "arguments": [address],
                },
            )
        return super().get(request, address, *args, **kwargs)

    @extend_schema(
        tags=["messages"],
        request=serializers.SafeMessageSerializer,
        responses={201: OpenApiResponse(description="Created")},
    )
    def post(self, request, address, *args, **kwargs):
        """
        Adds a new message for a given Safe account.
        Message can be:
        - A ``string``, so ``EIP191`` will be used to get the hash.
        - An ``EIP712`` ``object``.

        Hash will be calculated from the provided ``message``. Sending a raw ``hash`` will not be accepted,
        service needs to derive it itself.

        Note: Safe must be v1.4.1 for EIP-1271 signatures to work.
        """
        if not fast_is_checksum_address(address):
            return Response(
                status=status.HTTP_422_UNPROCESSABLE_ENTITY,
                data={
                    "code": 1,
                    "message": "Checksum address validation failed",
                    "arguments": [address],
                },
            )
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        self.perform_create(serializer)
        return Response(status=status.HTTP_201_CREATED)
