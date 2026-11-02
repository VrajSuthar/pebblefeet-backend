"""Money maths for the cart and checkout. Pure functions, no database.

Prices are GST-inclusive (Indian MRP rule: the printed price includes all
taxes), so GST is *extracted* from what the customer pays, never added on top:

    total = subtotal - discount + shipping
    tax   = GST contained in (each line - its share of the discount)
"""

from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal

from app.core.settings import settings
from app.model.coupon_model import Coupon, DiscountType

ZERO = Decimal("0.00")
HUNDRED = Decimal("100")


def money(value: Decimal | int) -> Decimal:
    return Decimal(value).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def to_paise(amount: Decimal) -> int:
    """Razorpay takes amounts in the smallest currency unit."""
    return int(money(amount) * 100)


@dataclass
class Line:
    unit_price: Decimal
    quantity: int
    gst_rate: Decimal
    # Filled in by price_order
    discount: Decimal = ZERO
    tax: Decimal = ZERO

    @property
    def total(self) -> Decimal:
        return money(self.unit_price * self.quantity)


@dataclass
class PriceBreakdown:
    subtotal: Decimal
    discount_amount: Decimal
    shipping_fee: Decimal
    tax_amount: Decimal
    total_amount: Decimal
    lines: list[Line] = field(default_factory=list)


def coupon_discount(coupon: Coupon, subtotal: Decimal) -> Decimal:
    if coupon.discount_type == DiscountType.PERCENTAGE:
        discount = money(subtotal * coupon.discount_value / HUNDRED)
        if coupon.max_discount_amount is not None:
            discount = min(discount, coupon.max_discount_amount)
    else:
        discount = coupon.discount_value
    # A flat coupon bigger than the cart makes it free, never negative
    return money(min(discount, subtotal))


def shipping_for(goods_amount: Decimal) -> Decimal:
    if goods_amount <= 0 or goods_amount >= settings.free_shipping_threshold:
        return ZERO
    return money(settings.shipping_fee)


def _gst_included(amount: Decimal, rate: Decimal) -> Decimal:
    return money(amount * rate / (HUNDRED + rate))


def price_order(lines: list[Line], coupon: Coupon | None = None) -> PriceBreakdown:
    subtotal = money(sum((line.total for line in lines), ZERO))
    discount = coupon_discount(coupon, subtotal) if coupon and subtotal > 0 else ZERO

    # Spread the discount over lines by value so each line's GST is computed
    # on what was really paid for it. The last line takes the rounding remainder.
    remaining = discount
    for index, line in enumerate(lines):
        if index == len(lines) - 1:
            line.discount = remaining
        else:
            line.discount = money(discount * line.total / subtotal) if subtotal else ZERO
            remaining -= line.discount
        line.tax = _gst_included(line.total - line.discount, line.gst_rate)

    goods = subtotal - discount
    shipping = shipping_for(goods)
    return PriceBreakdown(
        subtotal=subtotal,
        discount_amount=discount,
        shipping_fee=shipping,
        tax_amount=money(sum((line.tax for line in lines), ZERO)),
        total_amount=money(goods + shipping),
        lines=lines,
    )
