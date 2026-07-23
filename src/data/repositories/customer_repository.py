"""Customer repository — list with filters, search, computed loan summary."""

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.constants.enums import LoanStatus
from src.data.models.postgres.customer import Customer
from src.data.models.postgres.installment import Installment
from src.data.models.postgres.loan import Loan


class CustomerRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_id(self, customer_id: str) -> Customer | None:
        result = await self.session.execute(
            select(Customer).where(Customer.id == customer_id, Customer.is_deleted.is_(False))
        )
        return result.scalar_one_or_none()

    async def get_by_phone(self, phone: str) -> Customer | None:
        result = await self.session.execute(select(Customer).where(Customer.phone == phone))
        return result.scalar_one_or_none()

    async def create(self, customer: Customer) -> Customer:
        self.session.add(customer)
        await self.session.flush()
        await self.session.refresh(customer)
        return customer

    async def list_with_summary(
        self,
        *,
        collector_id: str | None = None,
        status_filter: str | None = None,
        search: str | None = None,
        offset: int = 0,
        limit: int = 20,
    ) -> tuple[list[tuple[Customer, int, int]], int]:
        """List customers + computed (active_loan_count, total_outstanding).

        outstanding = SUM(repayable - paid_on_installments) across active loans.
        """
        # Subquery: count of active loans per customer
        active_count_sq = (
            select(func.count(Loan.id))
            .where(Loan.customer_id == Customer.id, Loan.status == LoanStatus.ACTIVE.value)
            .correlate(Customer)
            .scalar_subquery()
        )

        # Subquery: sum of repayable across active loans
        repayable_sq = (
            select(func.coalesce(func.sum(Loan.repayable), 0))
            .where(Loan.customer_id == Customer.id, Loan.status == LoanStatus.ACTIVE.value)
            .correlate(Customer)
            .scalar_subquery()
        )

        # Subquery: sum of paid across installments of active loans for this customer
        paid_sq = (
            select(func.coalesce(func.sum(Installment.paid_amount), 0))
            .select_from(Installment)
            .join(Loan, Loan.id == Installment.loan_id)
            .where(Loan.customer_id == Customer.id, Loan.status == LoanStatus.ACTIVE.value)
            .correlate(Customer)
            .scalar_subquery()
        )
        outstanding_expr = (repayable_sq - paid_sq).label("total_outstanding")

        base = select(
            Customer,
            active_count_sq.label("active_loan_count"),
            outstanding_expr,
        )

        conds = [Customer.is_deleted.is_(False)]
        if collector_id is not None:
            assigned_sq = (
                select(Loan.customer_id)
                .where(
                    Loan.collector_id == collector_id,
                    Loan.status == LoanStatus.ACTIVE.value,
                )
                .scalar_subquery()
            )
            conds.append(Customer.id.in_(assigned_sq))

        if status_filter == "blacklisted":
            conds.append(Customer.is_blacklisted.is_(True))
        elif status_filter == "active":
            conds.append(Customer.is_blacklisted.is_(False))
            conds.append(active_count_sq > 0)
        elif status_filter == "overdue":
            overdue_sq = (
                select(Loan.customer_id)
                .where(Loan.status == LoanStatus.OVERDUE.value)
                .scalar_subquery()
            )
            conds.append(Customer.id.in_(overdue_sq))

        if search:
            like = f"%{search.strip().lower()}%"
            conds.append(
                or_(
                    func.lower(Customer.name).like(like),
                    func.lower(Customer.phone).like(like),
                )
            )

        if conds:
            base = base.where(and_(*conds))

        count_q = select(func.count()).select_from(base.subquery())
        total = (await self.session.execute(count_q)).scalar_one()

        paged = base.order_by(Customer.created_at.desc()).offset(offset).limit(limit)
        result = await self.session.execute(paged)
        rows = [(row[0], int(row[1] or 0), int(row[2] or 0)) for row in result.all()]
        return rows, int(total)
