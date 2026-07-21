"""Customer service — RBAC + computed loan summary."""

import re
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from src.constants.enums import LoanStatus, UserRole
from src.core.exceptions.base import ConflictError, ForbiddenError, NotFoundError
from src.data.models.postgres.customer import Customer
from src.data.models.postgres.loan import Loan
from src.data.repositories.customer_repository import CustomerRepository
from src.schemas.common import PaginatedResponse
from src.schemas.customer import CustomerCreate, CustomerResponse, CustomerUpdate

_NON_DIGIT = re.compile(r"\D+")


def _normalize_phone(raw: str) -> str:
    """Strip every non-digit so '+91 9876-543-210' → '919876543210'.

    Keeps the unique constraint meaningful by preventing whitespace / dash
    formatting variants from creating duplicate rows.
    """
    return _NON_DIGIT.sub("", raw or "")


class CustomerService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.customers = CustomerRepository(session)

    async def list(
        self,
        current_user: dict,
        status_filter: str | None,
        search: str | None,
        page: int,
        page_size: int,
    ) -> PaginatedResponse[CustomerResponse]:
        offset = (page - 1) * page_size

        # Collectors only see customers they have active loans with
        collector_id = (
            current_user["sub"] if current_user.get("role") == UserRole.COLLECTOR.value else None
        )

        rows, total = await self.customers.list_with_summary(
            collector_id=collector_id,
            status_filter=status_filter,
            search=search,
            offset=offset,
            limit=page_size,
        )

        items = [
            CustomerResponse(
                id=c.id,
                name=c.name,
                phone=c.phone,
                location=c.location,
                risk_level=c.risk_level,
                is_blacklisted=c.is_blacklisted,
                blacklist_reason=c.blacklist_reason,
                active_loan_count=active_count,
                total_outstanding=max(0, outstanding),
            )
            for c, active_count, outstanding in rows
        ]

        return PaginatedResponse[CustomerResponse](
            items=items,
            total=total,
            page=page,
            page_size=page_size,
            has_next=offset + page_size < total,
        )

    async def get(self, current_user: dict, customer_id: str) -> CustomerResponse:
        customer = await self.customers.get_by_id(customer_id)
        if customer is None:
            raise NotFoundError("customer", customer_id)
        await self._check_can_view(current_user, customer)
        summary = await self._loan_summary_for(customer.id)
        return CustomerResponse(
            id=customer.id,
            name=customer.name,
            phone=customer.phone,
            location=customer.location,
            risk_level=customer.risk_level,
            is_blacklisted=customer.is_blacklisted,
            blacklist_reason=customer.blacklist_reason,
            active_loan_count=summary[0],
            total_outstanding=summary[1],
        )

    async def _loan_summary_for(self, customer_id: str) -> tuple[int, int]:
        """Return (active_loan_count, total_outstanding) for one customer."""
        from sqlalchemy import func, select  # local — keep service imports tight

        from src.data.models.postgres.installment import Installment
        from src.data.models.postgres.loan import Loan

        active = await self.session.execute(
            select(func.count(Loan.id)).where(
                Loan.customer_id == customer_id, Loan.status == LoanStatus.ACTIVE.value
            )
        )
        active_count = int(active.scalar_one() or 0)

        outstanding_q = await self.session.execute(
            select(
                func.coalesce(func.sum(Loan.repayable), 0).label("repayable_total"),
                func.coalesce(
                    select(func.sum(Installment.paid_amount))
                    .select_from(Installment)
                    .join(Loan, Loan.id == Installment.loan_id)
                    .where(
                        Loan.customer_id == customer_id,
                        Loan.status == LoanStatus.ACTIVE.value,
                    )
                    .scalar_subquery(),
                    0,
                ).label("paid_total"),
            ).where(Loan.customer_id == customer_id, Loan.status == LoanStatus.ACTIVE.value)
        )
        row = outstanding_q.one()
        outstanding = max(0, int(row.repayable_total) - int(row.paid_total))
        return active_count, outstanding

    async def create(self, current_user: dict, body: CustomerCreate) -> CustomerResponse:
        self._require_investor(current_user)
        phone = _normalize_phone(body.phone)
        if not phone:
            raise ConflictError("phone is required")

        existing = await self.customers.get_by_phone(phone)
        if existing is not None:
            raise ConflictError(f"customer with phone {phone} already exists")

        customer = Customer(
            name=body.name.strip(),
            phone=phone,
            location=body.location.strip() if body.location else None,
            risk_level=body.risk_level.value,
            is_blacklisted=False,
        )
        try:
            await self.customers.create(customer)
        except IntegrityError as exc:
            # Race with concurrent create — the unique index catches it
            await self.session.rollback()
            raise ConflictError(f"customer with phone {phone} already exists") from exc
        return CustomerResponse.model_validate(customer)

    async def update(
        self, current_user: dict, customer_id: str, body: CustomerUpdate
    ) -> CustomerResponse:
        self._require_investor(current_user)
        customer = await self.customers.get_by_id(customer_id)
        if customer is None:
            raise NotFoundError("customer", customer_id)

        if body.name is not None:
            customer.name = body.name.strip()
        if body.phone is not None:
            new_phone = _normalize_phone(body.phone)
            if new_phone != customer.phone:
                clash = await self.customers.get_by_phone(new_phone)
                if clash is not None and clash.id != customer.id:
                    raise ConflictError(
                        f"customer with phone {new_phone} already exists"
                    )
                customer.phone = new_phone
        if body.location is not None:
            customer.location = body.location.strip()
        if body.risk_level is not None:
            customer.risk_level = body.risk_level.value
        try:
            await self.session.flush()
        except IntegrityError as exc:
            await self.session.rollback()
            raise ConflictError("phone update collided with another customer") from exc
        return CustomerResponse.model_validate(customer)

    async def delete(self, current_user: dict, customer_id: str) -> None:
        self._require_investor(current_user)
        customer = await self.customers.get_by_id(customer_id)
        if customer is None:
            raise NotFoundError("customer", customer_id)
        from sqlalchemy import func
        active_count = (await self.session.execute(
            select(func.count(Loan.id)).where(
                Loan.customer_id == customer_id,
                Loan.status == LoanStatus.ACTIVE.value,
            )
        )).scalar_one()
        if int(active_count) > 0:
            raise ConflictError("close or reassign active loans before deleting this customer")
        customer.is_deleted = True
        customer.deleted_at = datetime.now(timezone.utc)
        await self.session.flush()

    async def blacklist(
        self, current_user: dict, customer_id: str, reason: str
    ) -> CustomerResponse:
        self._require_investor(current_user)
        customer = await self.customers.get_by_id(customer_id)
        if customer is None:
            raise NotFoundError("customer", customer_id)
        customer.is_blacklisted = True
        customer.blacklist_reason = reason.strip()
        await self.session.flush()
        return CustomerResponse.model_validate(customer)

    async def unblacklist(
        self, current_user: dict, customer_id: str
    ) -> CustomerResponse:
        self._require_investor(current_user)
        customer = await self.customers.get_by_id(customer_id)
        if customer is None:
            raise NotFoundError("customer", customer_id)
        customer.is_blacklisted = False
        customer.blacklist_reason = None
        await self.session.flush()
        return CustomerResponse.model_validate(customer)

    # ----- RBAC helpers -----

    @staticmethod
    def _require_investor(current_user: dict) -> None:
        if current_user.get("role") != UserRole.INVESTOR.value:
            raise ForbiddenError("only investor can perform this action")

    async def _check_can_view(self, current_user: dict, customer: Customer) -> None:
        # Investor: anyone. Collector: only customers they have active loans with.
        if current_user.get("role") == UserRole.INVESTOR.value:
            return
        result = await self.session.execute(
            select(Loan.id)
            .where(
                Loan.customer_id == customer.id,
                Loan.collector_id == current_user["sub"],
                Loan.status == LoanStatus.ACTIVE.value,
            )
            .limit(1)
        )
        if result.scalar_one_or_none() is None:
            raise ForbiddenError("customer not assigned to you")
