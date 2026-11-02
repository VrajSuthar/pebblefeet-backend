import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.model.order_model import OrderStatus, PaymentMethod, PaymentStatus
from app.model.payment_model import TransactionStatus
from app.schema.common_schema import PageQuerySchema

# ------------------------------ Checkout ------------------------------


class CheckoutPreviewPayloadSchema(BaseModel):
    coupon_code: str | None = Field(default=None, max_length=50)


class PlaceOrderPayloadSchema(BaseModel):
    address_id: uuid.UUID
    payment_method: PaymentMethod = PaymentMethod.RAZORPAY
    coupon_code: str | None = Field(default=None, max_length=50)
    customer_note: str | None = Field(default=None, max_length=500)


class CheckoutLineSchema(BaseModel):
    variant_id: uuid.UUID
    product_name: str
    variant_name: str
    image_url: str | None
    quantity: int
    unit_price: Decimal
    line_total: Decimal


class CheckoutPreviewSchema(BaseModel):
    items: list[CheckoutLineSchema]
    coupon_code: str | None
    subtotal: Decimal
    discount_amount: Decimal
    shipping_fee: Decimal
    # GST already included in the prices, shown for transparency
    tax_amount: Decimal
    total_amount: Decimal
    cod_available: bool


class RazorpayPrefillSchema(BaseModel):
    name: str
    email: str
    contact: str


class RazorpayCheckoutSchema(BaseModel):
    """Everything the app passes to Razorpay Checkout (`new Razorpay(options)`)."""

    key_id: str
    razorpay_order_id: str
    amount: int  # paise
    currency: str
    order_id: uuid.UUID
    order_number: str
    name: str
    description: str
    prefill: RazorpayPrefillSchema


# ------------------------------ Orders ------------------------------


class OrderItemResponseSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    variant_id: uuid.UUID | None
    product_name: str
    variant_name: str
    sku: str
    image_url: str | None
    quantity: int
    unit_price: Decimal
    total_price: Decimal
    hsn_code: str
    gst_rate: Decimal


class OrderStatusHistorySchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    status: OrderStatus
    note: str | None
    created_at: datetime


class PaymentSummarySchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    amount: Decimal
    status: TransactionStatus
    method: str | None
    razorpay_order_id: str
    razorpay_payment_id: str | None
    failure_reason: str | None
    created_at: datetime


class OrderResponseSchema(BaseModel):
    id: uuid.UUID
    order_number: str
    status: OrderStatus
    payment_status: PaymentStatus
    payment_method: PaymentMethod
    subtotal: Decimal
    discount_amount: Decimal
    shipping_fee: Decimal
    tax_amount: Decimal
    total_amount: Decimal
    currency: str
    coupon_code: str | None
    shipping_address: dict[str, Any]
    courier_name: str | None
    tracking_number: str | None
    shipped_at: datetime | None
    delivered_at: datetime | None
    cancelled_at: datetime | None
    cancellation_reason: str | None
    customer_note: str | None
    created_at: datetime
    items: list[OrderItemResponseSchema]
    status_history: list[OrderStatusHistorySchema]
    payments: list[PaymentSummarySchema]
    # What the customer may do now; drives the buttons in the app
    can_cancel: bool
    can_return: bool
    can_pay: bool


class OrderListItemSchema(BaseModel):
    id: uuid.UUID
    order_number: str
    status: OrderStatus
    payment_status: PaymentStatus
    payment_method: PaymentMethod
    total_amount: Decimal
    item_count: int
    # First item, for the thumbnail in the order list
    preview_name: str | None
    preview_image_url: str | None
    created_at: datetime


class PlaceOrderResponseSchema(BaseModel):
    order: OrderResponseSchema
    # Present for Razorpay orders; open Checkout with it
    payment: RazorpayCheckoutSchema | None
    # Set when the order was saved but Razorpay could not be reached;
    # retry with POST /orders/{id}/pay
    payment_error: str | None = None


class OrderQuerySchema(PageQuerySchema):
    status: OrderStatus | None = None


class CancelOrderPayloadSchema(BaseModel):
    reason: str | None = Field(default=None, max_length=500)


class ReturnRequestPayloadSchema(BaseModel):
    reason: str = Field(min_length=3, max_length=500)


# ------------------------------ Payments ------------------------------


class VerifyPaymentPayloadSchema(BaseModel):
    """The three values Razorpay Checkout hands to its `handler` callback."""

    razorpay_order_id: str = Field(min_length=1, max_length=100)
    razorpay_payment_id: str = Field(min_length=1, max_length=100)
    razorpay_signature: str = Field(min_length=1, max_length=255)


# ------------------------------ Admin ------------------------------


class AdminOrderCustomerSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    first_name: str
    last_name: str
    email: str
    phone_number: str


class AdminOrderResponseSchema(OrderResponseSchema):
    customer: AdminOrderCustomerSchema


class AdminOrderListItemSchema(OrderListItemSchema):
    customer_name: str
    customer_email: str


class AdminOrderQuerySchema(PageQuerySchema):
    status: OrderStatus | None = None
    payment_status: PaymentStatus | None = None
    payment_method: PaymentMethod | None = None
    # Order number, customer email or phone
    search: str | None = Field(default=None, max_length=100)
    date_from: date | None = None
    date_to: date | None = None


class AdminOrderStatusPayloadSchema(BaseModel):
    status: OrderStatus
    note: str | None = Field(default=None, max_length=500)
    # Required when moving to "shipped" (unless already saved on the order)
    courier_name: str | None = Field(default=None, max_length=100)
    tracking_number: str | None = Field(default=None, max_length=100)


# ------------------------------ Dashboard ------------------------------


class LowStockVariantSchema(BaseModel):
    variant_id: uuid.UUID
    product_name: str
    variant_name: str
    sku: str
    stock: int


class TopProductSchema(BaseModel):
    product_name: str
    quantity_sold: int
    revenue: Decimal


class DashboardSchema(BaseModel):
    revenue_today: Decimal
    revenue_last_30_days: Decimal
    orders_today: int
    orders_last_30_days: int
    # Paid/confirmed orders waiting to be packed or shipped
    orders_to_fulfil: int
    return_requests: int
    orders_by_status: dict[OrderStatus, int]
    total_customers: int
    new_customers_last_30_days: int
    low_stock: list[LowStockVariantSchema]
    top_products_last_30_days: list[TopProductSchema]
