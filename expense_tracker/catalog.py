"""Categories, subcategories, payment methods and income sources, each with an icon.

The defaults below are used until you customise them (Settings → Categories & icons in the
window); after that, your own lists are saved in the data file.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field

DEFAULT_ICON = "🏷"
DEFAULT_COLOR = "#8d99ae"
PALETTE = [
    "#f4a261", "#43aa8b", "#2a9d8f", "#8d6cab", "#e9c46a", "#e76f51",
    "#577590", "#f28482", "#4d908e", "#cdb4db", "#277da1", "#90be6d",
]


@dataclass
class Item:
    """A named thing with an icon: a subcategory, payment method or income source."""

    name: str
    icon: str = DEFAULT_ICON

    def to_dict(self) -> dict:
        return {"name": self.name, "icon": self.icon}

    @classmethod
    def from_dict(cls, d: dict) -> Item:
        return cls(name=d["name"], icon=d.get("icon") or DEFAULT_ICON)


@dataclass
class Category:
    name: str
    icon: str = DEFAULT_ICON
    color: str = DEFAULT_COLOR
    subcategories: list[Item] = field(default_factory=list)

    def subcategory(self, name: str) -> Item | None:
        return next((s for s in self.subcategories if s.name.lower() == name.lower()), None)

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "icon": self.icon,
            "color": self.color,
            "subcategories": [s.to_dict() for s in self.subcategories],
        }

    @classmethod
    def from_dict(cls, d: dict) -> Category:
        return cls(
            name=d["name"],
            icon=d.get("icon") or DEFAULT_ICON,
            color=d.get("color") or DEFAULT_COLOR,
            subcategories=[Item.from_dict(s) for s in d.get("subcategories", [])],
        )


def _cat(name: str, icon: str, color: str, subs: list[tuple[str, str]]) -> Category:
    return Category(name, icon, color, [Item(n, i) for n, i in subs])


def default_categories() -> list[Category]:
    return [
        _cat("Food", "🍽", "#f4a261", [
            ("Restaurant", "🍽"), ("Delivery", "🛵"), ("Coffee", "☕"), ("Snacks", "🍿"),
        ]),
        _cat("Groceries", "🛒", "#43aa8b", [
            ("Supermarket", "🛒"), ("Market", "🥬"), ("Bakery", "🥖"),
        ]),
        _cat("Transport", "🚕", "#2a9d8f", [
            ("Taxi", "🚕"), ("Bus / Metro", "🚌"), ("Gasoline", "⛽"),
            ("Parking", "🅿"), ("Car maintenance", "🔧"),
        ]),
        _cat("Housing", "🏠", "#8d6cab", [
            ("Rent", "🏠"), ("Repairs", "🛠"), ("Furniture", "🛋"),
        ]),
        _cat("Utilities", "💡", "#e9c46a", [
            ("Electricity", "💡"), ("Water", "🚿"), ("Gas", "🔥"), ("Internet", "🌐"), ("Phone", "📱"),
        ]),
        _cat("Health", "💊", "#e76f51", [
            ("Pharmacy", "💊"), ("Doctor", "🩺"), ("Dentist", "🦷"), ("Insurance", "🛡"), ("Gym", "🏋"),
        ]),
        _cat("Entertainment", "🎬", "#577590", [
            ("Movies", "🎬"), ("Streaming", "📺"), ("Games", "🎮"), ("Events", "🎟"), ("Going out", "🍻"),
        ]),
        _cat("Shopping", "🛍", "#f28482", [
            ("Clothes", "👕"), ("Electronics", "💻"), ("Home", "🏡"), ("Gifts", "🎁"),
        ]),
        _cat("Education", "📚", "#4d908e", [
            ("Courses", "🎓"), ("Books", "📚"), ("Supplies", "✏"),
        ]),
        _cat("Personal care", "💇", "#cdb4db", [
            ("Haircut", "💇"), ("Cosmetics", "🧴"),
        ]),
        _cat("Travel", "✈", "#277da1", [
            ("Flights", "✈"), ("Lodging", "🏨"), ("Tours", "🗺"),
        ]),
        _cat("Other", "📦", "#adb5bd", []),
    ]


def default_payment_methods() -> list[Item]:
    return [
        Item("Cash", "💵"), Item("Debit card", "💳"), Item("Credit card", "💳"),
        Item("Yape", "📱"), Item("Plin", "📲"), Item("Bank transfer", "🏦"),
    ]


def default_income_sources() -> list[Item]:
    return [
        Item("Salary", "💼"), Item("Freelance", "💻"), Item("Gift", "🎁"),
        Item("Investments", "📈"), Item("Refund", "↩"), Item("Other", "💰"),
    ]


# Emoji offered in the icon picker.
ICON_CHOICES = [
    "🍽", "🍔", "🍕", "🍜", "🍣", "🍱", "🥗", "☕", "🍿", "🍻", "🍷", "🛵",
    "🛒", "🥬", "🥖", "🍎", "🥩", "🧀", "🚕", "🚌", "🚇", "🚗", "⛽", "🅿",
    "🔧", "🚲", "✈", "🚆", "🏠", "🛠", "🛋", "🧹", "💡", "🚿", "🔥", "🌐",
    "📱", "📲", "💊", "🩺", "🦷", "🛡", "🏋", "🧘", "🎬", "📺", "🎮", "🎟",
    "🎵", "📖", "🛍", "👕", "👟", "💻", "🏡", "🎁", "📚", "🎓", "✏", "💇",
    "🧴", "💅", "🏨", "🗺", "🏖", "🐶", "🐱", "👶", "🧸", "💼", "📈", "💰",
    "💵", "💳", "🏦", "↩", "🧾", "📦", "🏷", "⭐", "❤", "🌱", "⚽", "🎨",
]


def color_for(name: str) -> str:
    """Stable fallback color for a category that isn't in the catalog."""
    digest = hashlib.md5(name.lower().encode("utf-8")).digest()
    return PALETTE[digest[0] % len(PALETTE)]


def find_category(categories: list[Category], name: str) -> Category | None:
    return next((c for c in categories if c.name.lower() == name.lower()), None)


def find_item(items: list[Item], name: str) -> Item | None:
    return next((i for i in items if i.name.lower() == name.lower()), None)


def category_look(categories: list[Category], category: str, subcategory: str = "") -> tuple[str, str]:
    """(icon, color) to show for a category/subcategory, with sensible fallbacks."""
    cat = find_category(categories, category)
    if cat is None:
        return DEFAULT_ICON, color_for(category)
    if subcategory:
        sub = cat.subcategory(subcategory)
        if sub is not None:
            return sub.icon, cat.color
    return cat.icon, cat.color
