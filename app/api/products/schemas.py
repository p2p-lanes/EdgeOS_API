from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, model_validator


class ProductBase(BaseModel):
    name: str
    slug: str
    price: float
    compare_price: Optional[float] = None
    popup_city_id: int
    description: Optional[str] = None
    category: Optional[str] = None
    attendee_category: Optional[str] = None
    start_date: Optional[datetime] = None
    end_date: Optional[datetime] = None
    is_active: bool = True
    exclusive: bool = False
    insurance_percentage: Optional[float] = None
    min_price: Optional[float] = None
    max_price: Optional[float] = None

    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    model_config = ConfigDict(
        str_strip_whitespace=True,
    )

    @model_validator(mode='after')
    def validate_price_range(self) -> 'ProductBase':
        if self.min_price is not None and self.min_price <= 0:
            raise ValueError('min_price must be greater than 0')
        if self.max_price is not None and self.max_price <= 0:
            raise ValueError('max_price must be greater than 0')
        if self.min_price is not None and self.max_price is not None:
            if self.max_price < self.min_price:
                raise ValueError('max_price must be >= min_price')
        return self


class ProductCreate(ProductBase):
    name: Optional[str] = None


class ProductUpdate(ProductBase):
    pass


class Product(ProductBase):
    id: int

    model_config = ConfigDict(
        from_attributes=True,
    )


class ProductWithQuantity(Product):
    quantity: int


class ProductFilter(BaseModel):
    id: Optional[int] = None
    id_in: Optional[List[int]] = None
    is_active: Optional[bool] = None
    name: Optional[str] = None
    category: Optional[str] = None
    popup_city_id: Optional[int] = None
