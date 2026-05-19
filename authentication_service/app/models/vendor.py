from sqlalchemy import Column, Integer, String, Enum

from authentication_service.app.core.db import Base


class Vendor(Base):
    __tablename__ = "vendors"
    __table_args__ = {"extend_existing": True}

    VendorID = Column(Integer, primary_key=True, autoincrement=True)
    SupplierNumber = Column(String(100), nullable=False)
    Name1 = Column(String(200), nullable=False)
    Name2 = Column(String(200), nullable=False)
    overall_status = Column(
        Enum("PENDING", "IN_PROGRESS", "APPROVED", "REJECTED", name="vendor_status_enum"),
        nullable=False,
    )
    sap_order_number = Column(String(20), nullable=True)

    CompanyCode = Column(String(50), nullable=True)
    GSTNumber = Column(String(50), nullable=False)
    PaymentTerm = Column(String(100), nullable=True)

    BankName1 = Column(String(200), nullable=True)
    BankName2 = Column(String(200), nullable=True)
    BankName3 = Column(String(200), nullable=True)

    IFSCCode = Column(String(100), nullable=True)
    SwiftCode = Column(String(100), nullable=True)
    AccountNumber = Column(String(100), nullable=True)

    user_id = Column(Integer, nullable=True)
