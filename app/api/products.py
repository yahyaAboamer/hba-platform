"""The catalogue, its rosters, and what marketing asks about each product.

W01, W02, W09, W15. Staff-side. The model's own wardrobe lives on
`/api/me/wardrobe`, because §6.1 splits on **what the session is** rather than
on what it may do.
"""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import require_permission
from app.core.money import format_egp
from app.core.permissions import Permission
from app.db import get_session
from app.models.catalogue import Product, ProductStatus, ProductVariant
from app.models.identity import UserAccount
from app.services.wardrobe import (
    feature_request_for,
    thumbnail,
    remove_feature_request,
    roster_for,
    set_feature_request,
)

router = APIRouter(prefix="/api/products")


class FeatureRequestBody(BaseModel):
    """W09's three verbs. `message` writes it, `visible` shows or hides it."""

    message: str | None = Field(default=None, max_length=2000)
    visible: bool | None = None


@router.get("")
def list_products(
    all_products: bool = False,
    scope: str | None = None,
    search: str | None = None,
    limit: int = 60,
    offset: int = 0,
    _actor: UserAccount = Depends(require_permission(Permission.AFFILIATES_VIEW)),
    db: Session = Depends(get_session),
) -> dict:
    """The catalogue.

    **Active by default; `all_products` includes draft and archived** (W01). A
    product archived in Shopify is still in somebody's wardrobe, so it is kept
    and hidden rather than dropped - the default answers *what are we selling*,
    and the switch answers *what have we ever sold*.

    Search is on the name, because W01 puts colour in the product name and
    there is no separate colour taxonomy to filter by.

    **Paged, and the page is small.** Sixty is about three scrolls on a laptop
    and it is sixty images rather than five hundred - the first version handed
    back everything up to a cap, which is fine on a shop with twelve products
    and is the reason this screen was slow on a shop with hundreds.

    `total` comes back so the interface can say *60 of 340* rather than
    implying that sixty is all there is.
    """
    from sqlalchemy import or_

    from app.models.affiliates import AccountKind, AffiliateProfile
    from app.models.promotions import FeatureRequest

    # The approved catalogue's three filters: *Active*, *All products* and
    # *Active requests* - the last being the products a feature request is
    # currently showing to models. `all_products` is kept as the older
    # spelling of the second.
    scope = scope or ("all" if all_products else "active")
    showing_requests = select(FeatureRequest.shopify_product_id).where(
        FeatureRequest.visible.is_(True)
    )

    query = select(Product)
    if scope == "active":
        query = query.where(Product.status == ProductStatus.ACTIVE)
    elif scope == "requests":
        query = query.where(Product.shopify_product_id.in_(showing_requests))
    if search and search.strip():
        needle = f"%{search.strip()}%"
        # Name **or SKU**, as the approved search says. A SKU belongs to a
        # size, so a product matches when any of its sizes does.
        query = query.where(
            or_(
                Product.title.ilike(needle),
                Product.shopify_product_id.in_(
                    select(ProductVariant.shopify_product_id).where(
                        ProductVariant.sku.ilike(needle)
                    )
                ),
            )
        )

    total = db.scalar(
        select(func.count()).select_from(query.subquery())
    ) or 0

    rows = list(
        db.scalars(
            query.order_by(Product.title)
            .offset(max(0, offset))
            .limit(min(max(1, limit), 200))
        )
    )

    sizes = {}
    if rows:
        counts = db.execute(
            select(ProductVariant.shopify_product_id, func.count())
            .where(
                ProductVariant.shopify_product_id.in_(
                    [row.shopify_product_id for row in rows]
                )
            )
            .group_by(ProductVariant.shopify_product_id)
        )
        sizes = {product_id: count for product_id, count in counts}

    # The approved catalogue is a table, and two of its columns are about the
    # models rather than the product: **how many of them have it**, and
    # **whether HBA has asked for it to be posted about**. Both are one
    # grouped query over the page's rows rather than one query per row.
    coverage: dict[str, int] = {}
    featured: dict[str, bool] = {}
    if rows:
        from app.models.promotions import FeatureRequest
        from app.services.wardrobe import coverage_for

        ids = [row.shopify_product_id for row in rows]
        coverage = coverage_for(db, ids)
        featured = {
            request.shopify_product_id: request.visible
            for request in db.scalars(
                select(FeatureRequest).where(
                    FeatureRequest.shopify_product_id.in_(ids)
                )
            )
        }

    return {
        "products": [
            {
                "shopify_product_id": row.shopify_product_id,
                "title": row.title,
                "status": row.status,
                # **The sized one**, because this is a grid of thumbnails.
                # A product photograph is commonly 2000px; sixty of those is
                # tens of megabytes to draw one page.
                "image_url": thumbnail(row.image_url),
                "sizes": sizes.get(row.shopify_product_id, 0),
                # How many models have one. Distinct models, not parcels: two
                # sent to the same person is one model covered, and counting
                # parcels would overstate reach on exactly the products HBA
                # sends most.
                "models_with_it": coverage.get(row.shopify_product_id, 0),
                # None where nothing has been asked for, which is not the same
                # as a request that exists and is currently hidden (W09).
                "featured": featured.get(row.shopify_product_id),
                # Freshness, said rather than implied. A catalogue nobody has
                # read for a fortnight looks identical to a fresh one.
                "synced_at": row.synced_at.isoformat() if row.synced_at else None,
            }
            for row in rows
        ],
        "showing": scope,
        "total": total,
        "offset": max(0, offset),
        # The counts inside the three filter labels - *Active 42* - which do
        # not move with the search, as the export's do not.
        "counts": {
            "active": db.scalar(
                select(func.count())
                .select_from(Product)
                .where(Product.status == ProductStatus.ACTIVE)
            )
            or 0,
            "all": db.scalar(select(func.count()).select_from(Product)) or 0,
            "requests": db.scalar(
                select(func.count()).select_from(showing_requests.subquery())
            )
            or 0,
        },
        # What *3 of 12 received* is out of: the models currently working
        # with HBA. A house code receives nothing and is not in it.
        "active_models": db.scalar(
            select(func.count())
            .select_from(AffiliateProfile)
            .where(AffiliateProfile.status == "active")
            .where(AffiliateProfile.account_kind != AccountKind.HOUSE)
        )
        or 0,
    }


@router.get("/{shopify_product_id}")
def product_detail(
    shopify_product_id: str,
    _actor: UserAccount = Depends(require_permission(Permission.AFFILIATES_VIEW)),
    db: Session = Depends(get_session),
) -> dict:
    """One product, its sizes, its roster and its feature request.

    The roster is W02's four groups in W02's order. It counts every model, not
    only those who received something - the question is *who could I ask*.
    """
    product = db.get(Product, shopify_product_id)
    if product is None:
        raise HTTPException(404, "No such product")

    variants = db.scalars(
        select(ProductVariant)
        .where(ProductVariant.shopify_product_id == shopify_product_id)
        .order_by(ProductVariant.position)
    )

    return {
        "shopify_product_id": product.shopify_product_id,
        "title": product.title,
        "status": product.status,
        "image_url": product.image_url,
        "synced_at": product.synced_at.isoformat() if product.synced_at else None,
        "sizes": [{"title": row.title, "sku": row.sku} for row in variants],
        "roster": roster_for(db, shopify_product_id),
        "feature_request": feature_request_for(db, shopify_product_id),
    }


@router.put("/{shopify_product_id}/feature-request")
def put_feature_request(
    shopify_product_id: str,
    body: FeatureRequestBody,
    actor: UserAccount = Depends(require_permission(Permission.AFFILIATES_MANAGE)),
    db: Session = Depends(get_session),
) -> dict:
    """Write, show or hide what marketing asks about this product.

    **Passive guidance** (W09). There is no completion to track and no target
    to move: a model reads it and decides. Hiding keeps the wording; removing
    is `DELETE`, and the two are different on purpose.
    """
    if db.get(Product, shopify_product_id) is None:
        raise HTTPException(404, "No such product")

    try:
        set_feature_request(
            db,
            shopify_product_id,
            message=body.message,
            visible=body.visible,
            actor_id=actor.id,
        )
        db.commit()
    except ValueError as exc:
        db.rollback()
        raise HTTPException(400, str(exc)) from exc

    return feature_request_for(db, shopify_product_id) or {}


@router.delete("/{shopify_product_id}/feature-request")
def delete_feature_request(
    shopify_product_id: str,
    _actor: UserAccount = Depends(require_permission(Permission.AFFILIATES_MANAGE)),
    db: Session = Depends(get_session),
) -> dict:
    """Withdraw it. W09 lists removing separately from hiding."""
    removed = remove_feature_request(db, shopify_product_id)
    db.commit()
    return {"removed": removed}


@router.get("/top-sellers/{month}")
def top_sellers(
    month: str,
    _actor: UserAccount = Depends(require_permission(Permission.AFFILIATES_VIEW)),
    db: Session = Depends(get_session),
) -> dict:
    """Which products sold through the models' codes. W11, Phase 07B.

    **Three different questions, and this answers one.** W11 separates selling
    through a code, owning something from the wardrobe, and being asked to
    feature it — *a model can sell products she never received*. This counts
    what was bought, and says nothing about who has what.

    Figures are what the customer actually paid after the model's discount.
    Summing list prices would credit the shop with money it never took.
    """
    from app.core.businesstime import parse_month
    from app.services.performance import top_products

    try:
        month = parse_month(month)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc

    found = top_products(db, month)
    return {
        "month": found["month"],
        "products": [
            {
                "shopify_product_id": row.shopify_product_id,
                "title": row.title,
                "quantity": row.quantity,
                "sales_piastres": row.sales_piastres,
                "sales": format_egp(row.sales_piastres),
            }
            for row in found["products"]
        ],
        # Given so the figures on this screen still reconcile with the sales
        # totals elsewhere, rather than quietly falling short of them.
        "no_longer_in_shopify_piastres": found["no_longer_in_shopify_piastres"],
        "no_longer_in_shopify": format_egp(found["no_longer_in_shopify_piastres"]),
        "total_piastres": found["total_piastres"],
        "total": format_egp(found["total_piastres"]),
    }
