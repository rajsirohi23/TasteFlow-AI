
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.orm import Session

from order_schemas import OrderCreate
from agent_schemas import MenuRecommendationRequest
from agents.order_agent import prepare_order_preview
from agents.supervisor_agent import (
    route_customer_request_with_ai,
    extract_menu_preferences,
    get_ai_menu_tool_request,
    get_ai_analytics_tool_request,
)

from database import get_db
from agents.menu_agent import (
    get_dish_popularity,
    get_recommendation_reasons,
    recommend_menu_items,
)

from services.time_utils import local_today
from fastapi import Header
from auth import verify_token

from routers.owner import (
    get_owner_summary,
    get_popular_dishes,
    get_low_demand_dishes,
    get_daily_sales,
    get_top_revenue_dishes,
)


router = APIRouter(
    prefix="/api/agents",
    tags=["AI Agents"],
)


class RecommendedMenuItem(BaseModel):
    id: int
    name: str
    price: int
    category: str
    dietary_tags: list[str]
    description: str
    spice_level: str
    image: str
    reasons: list[str]


class MenuRecommendationResponse(BaseModel):
    count: int
    recommendations: list[RecommendedMenuItem]


class SupervisorRequest(BaseModel):
    message: str = Field(min_length=1, max_length=1000)

    @field_validator("message")
    @classmethod
    def validate_message(cls, value: str) -> str:
        value = value.strip()

        if not value:
            raise ValueError("Message cannot be empty or contain only spaces.")

        return value



@router.post(
    "/menu/recommend",
    response_model=MenuRecommendationResponse,
)
def get_menu_recommendations(
    request: MenuRecommendationRequest,
    db: Session = Depends(get_db),
):
    try:
        items = recommend_menu_items(
            db=db,
            budget=request.budget,
            diet=request.diet,
            category=request.category,
            spice_level=request.spice_level,
            max_spice_level=request.max_spice_level,
            exclude_ingredients=request.exclude_ingredients or None,
            protein_focus=request.protein_focus,
            limit=request.limit,
        )
        popularity = get_dish_popularity(db)

        return {
            "count": len(items),
            "recommendations": [
                {
                    "id": item.id,
                    "name": item.name,
                    "price": item.price,
                    "category": item.category,
                    "dietary_tags": item.dietary_tags or [],
                    "description": item.description,
                    "spice_level": item.spice_level,
                    "image": item.image,
                    "reasons": get_recommendation_reasons(
                        item=item,
                        budget=request.budget,
                        diet=request.diet,
                        category=request.category,
                        spice_level=request.spice_level,
                        popularity=popularity,
                        max_spice_level=request.max_spice_level,
                        protein_focus=request.protein_focus,
                    ),
                }
                for item in items
            ],
        }

    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail="Unable to generate menu recommendations.",
        ) from exc




@router.post("/orders/preview")
def preview_order(
    order_data: OrderCreate,
    db: Session = Depends(get_db),
):
    try:
        return prepare_order_preview(db, order_data)

    except ValueError as exc:
        message = str(exc)

        if "not found" in message.lower():
            raise HTTPException(
                status_code=404,
                detail=message,
            ) from exc

        raise HTTPException(
            status_code=409,
            detail=message,
        ) from exc



@router.post("/supervisor/route")
def supervise_customer_request(request: SupervisorRequest):
    result = route_customer_request_with_ai(request.message)

    return {
        "success": True,
        "selected_agent": result["agent"],
        "intent": result["intent"],
        "message": result["message"],
    }



@router.post("/supervisor/execute")
def execute_supervisor_request(
    request: SupervisorRequest,
    db: Session = Depends(get_db),
    authorization: str | None = Header(default=None),
):
    """Legacy single-shot endpoint, kept for compatibility. New UI uses POST /api/chat."""
    route = route_customer_request_with_ai(request.message)

    response = {
        "success": True,
        "selected_agent": route["agent"],
        "intent": route["intent"],
        "message": route["message"],
    }

    # MENU AGENT
    if route["agent"] == "menu":
        preferences = get_ai_menu_tool_request(request.message)

        if preferences is None:
            preferences = extract_menu_preferences(request.message)

        recommendation_request = MenuRecommendationRequest(
            **preferences
        )

        recommendations = get_menu_recommendations(
            recommendation_request,
            db,
        )

        response["result"] = recommendations
        return response

    # ORDER AGENT
    if route["agent"] == "order":
        response["result"] = {
            "message": (
                "I can help you review an order. "
                "Please select dishes using the menu and cart, "
                "then review your order before confirming checkout."
            ),
            "requires_confirmation": True,
            "preview_endpoint": "/api/agents/orders/preview",
        }
        return response

    # ANALYTICS AGENT
    if route["agent"] == "analytics":
        payload = verify_token(authorization[7:].strip()) if authorization and authorization.lower().startswith("bearer ") else None
        if not payload or payload["role"] != "owner":
            response["result"] = {"message": "Business analytics is available to restaurant staff only."}
            return response
        message = request.message.lower()

        report_type = get_ai_analytics_tool_request(
            request.message
        )

        # Rule-based fallback if AI tool selection is unavailable.
        if report_type is None:
            if "low demand" in message or "low-demand" in message:
                report_type = "low_demand_dishes"
            elif (
                "popular" in message
                or "not popular" in message
                or "best selling" in message
                or "best-selling" in message
                or "selling the best" in message
            ):
                report_type = "popular_dishes"
            elif (
                "top revenue" in message
                or "highest revenue" in message
            ):
                report_type = "top_revenue_dishes"
            elif (
                "daily sales" in message
                or "today" in message
            ):
                report_type = "daily_sales"
            else:
                report_type = "sales_summary"

        if report_type == "low_demand_dishes":
            result = get_low_demand_dishes(
                threshold=2,
                start_date=None,
                end_date=None,
                db=db,
            )

        elif report_type == "popular_dishes":
            result = get_popular_dishes(
                limit=5,
                start_date=None,
                end_date=None,
                db=db,
            )

        elif report_type == "top_revenue_dishes":
            result = get_top_revenue_dishes(
                start_date=None,
                end_date=None,
                limit=5,
                db=db,
            )

        elif report_type == "daily_sales":
            today = local_today()
            result = get_daily_sales(
                start_date=today,
                end_date=today,
                db=db,
            )

        else:
            report_type = "sales_summary"
            result = get_owner_summary(
                start_date=None,
                end_date=None,
                db=db,
            )

        response["result"] = {
            "report_type": report_type,
            "data": result,
        }
        return response

    # GENERAL AGENT
    response["result"] = {
        "message": (
            "I'm your TasteFlow assistant. I can recommend dishes, "
            "help with ordering, or answer restaurant analytics questions."
        )
    }
    return response
