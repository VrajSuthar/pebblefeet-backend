from decimal import Decimal

from app.model.coupon_model import Coupon, DiscountType
from app.services.pricing import Line, coupon_discount, price_order, shipping_for, to_paise

D = Decimal


def coupon(kind: DiscountType, value: str, cap: str | None = None) -> Coupon:
    return Coupon(
        discount_type=kind,
        discount_value=D(value),
        max_discount_amount=D(cap) if cap else None,
    )


def test_shipping_free_from_threshold():
    assert shipping_for(D("498.99")) == D("50.00")
    assert shipping_for(D("499")) == D("0.00")
    assert shipping_for(D("0")) == D("0.00")


def test_gst_is_extracted_not_added():
    # ₹118 at 18% GST contains exactly ₹18 of tax; customer pays 118 + shipping
    breakdown = price_order([Line(D("118"), 1, D("18"))])
    assert breakdown.tax_amount == D("18.00")
    assert breakdown.total_amount == D("168.00")  # 118 + 50 shipping


def test_percentage_coupon_is_capped():
    assert coupon_discount(coupon(DiscountType.PERCENTAGE, "20", cap="100"), D("1000")) == D("100.00")
    assert coupon_discount(coupon(DiscountType.PERCENTAGE, "20"), D("1000")) == D("200.00")


def test_flat_coupon_never_goes_below_zero():
    assert coupon_discount(coupon(DiscountType.FLAT, "500"), D("300")) == D("300.00")


def test_discount_split_across_lines_adds_up():
    lines = [Line(D("120"), 3, D("18")), Line(D("330"), 1, D("5")), Line(D("99.99"), 1, D("12"))]
    breakdown = price_order(lines, coupon(DiscountType.PERCENTAGE, "15"))

    assert breakdown.subtotal == D("789.99")
    assert breakdown.discount_amount == D("118.50")
    assert sum(line.discount for line in breakdown.lines) == breakdown.discount_amount
    assert breakdown.shipping_fee == D("0.00")
    assert breakdown.total_amount == D("671.49")
    # GST per line is on what was paid for that line after its discount share
    first = breakdown.lines[0]
    assert first.tax == ((first.total - first.discount) * 18 / 118).quantize(D("0.01"))


def test_to_paise():
    assert to_paise(D("671.49")) == 67149
    assert to_paise(D("0.1")) == 10
