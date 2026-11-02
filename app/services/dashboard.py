from datetime import datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from app.model.order_model import OrderStatus
from app.repository.order import OrderRepository
from app.schema.order_schema import DashboardSchema, LowStockVariantSchema, TopProductSchema
from app.services.order import IST
from app.services.pricing import money


class DashboardService:
    def __init__(self, db: AsyncSession):
        self.repo = OrderRepository(db)

    async def summary(self) -> DashboardSchema:
        now = datetime.now(IST)
        # "Today" is the Indian calendar day, not UTC
        start_of_today = now.replace(hour=0, minute=0, second=0, microsecond=0)
        thirty_days_ago = now - timedelta(days=30)

        revenue_today, orders_today = await self.repo.revenue_and_count_since(start_of_today)
        revenue_30, orders_30 = await self.repo.revenue_and_count_since(thirty_days_ago)
        by_status = await self.repo.count_by_status()
        customers, new_customers = await self.repo.customer_counts(thirty_days_ago)

        return DashboardSchema(
            revenue_today=money(revenue_today),
            revenue_last_30_days=money(revenue_30),
            orders_today=orders_today,
            orders_last_30_days=orders_30,
            orders_to_fulfil=by_status.get(OrderStatus.CONFIRMED, 0)
            + by_status.get(OrderStatus.PROCESSING, 0),
            return_requests=by_status.get(OrderStatus.RETURN_REQUESTED, 0),
            orders_by_status={status: by_status.get(status, 0) for status in OrderStatus},
            total_customers=customers,
            new_customers_last_30_days=new_customers,
            low_stock=[
                LowStockVariantSchema(
                    variant_id=v.id,
                    product_name=v.product.name,
                    variant_name=v.name,
                    sku=v.sku,
                    stock=v.stock,
                )
                for v in await self.repo.low_stock_variants()
            ],
            top_products_last_30_days=[
                TopProductSchema(product_name=name, quantity_sold=qty, revenue=money(revenue))
                for name, qty, revenue in await self.repo.top_products_since(thirty_days_ago)
            ],
        )
