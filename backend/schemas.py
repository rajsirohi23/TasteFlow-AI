from pydantic import BaseModel, ConfigDict


class MenuItemResponse(BaseModel):
    id: int
    name: str
    price: int
    category: str
    dietary_tags: list[str]
    ingredients: list[str]
    description: str
    spice_level: str
    available: bool
    image: str

    model_config = ConfigDict(from_attributes=True)