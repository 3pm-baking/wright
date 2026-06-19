# Beyond Food — Using wright for Any Domain

`wright` is built on domain-agnostic primitives: `Material`, `Component`,
`ProductionItem`, and `PurchasedItem`.  This guide shows how to use them
for construction, brewing, event planning, and manufacturing.

## Construction

Build a deck BOM, scale it, and calculate material costs:

```python
from decimal import Decimal
from wright import Material, Component, ProductionItem, ProductionRun
from wright import generate_shopping_list, calculate_item_costs

# Define a deck as a set of components
framing = Component(
    name="Deck Framing",
    materials=[
        Material(
            name="2x6 Pressure-Treated",
            quantity=48,
            unit="ft",
            require_tags=["#2", "ground-contact"],
        ),
        Material(name="2x4 Joist Hangers", quantity=12, unit="each"),
        Material(name='3" Deck Screws', quantity=400, unit="each"),
    ],
)
footings = Component(
    name="Concrete Footings",
    materials=[
        Material(
            name="Concrete Mix",
            quantity=8,
            unit="bag",
            equivalent_quantity=60,
            equivalent_unit="lb",
        ),
        Material(name="Post Anchor", quantity=6, unit="each"),
    ],
)

# Purchase price data (any PurchasedItem protocol works)
hardware_prices = [
    Purchase(
        name="2x6 Pressure-Treated",
        quantity=8,
        unit="ft",
        price=Decimal("12.97"),
        store="Home Depot",
        tags="ground-contact,#2",
    ),
    Purchase(
        name='3" Deck Screws',
        quantity=100,
        unit="each",
        price=Decimal("5.97"),
        store="Home Depot",
    ),
    Purchase(
        name="Concrete Mix",
        quantity=1,
        unit="bag",
        price=Decimal("4.98"),
        store="Lowe's",
    ),
]

# Cost individual materials
materials_costed = calculate_item_costs(framing.materials, hardware_prices)
for mc in materials_costed:
    print(f"  {mc.item.name}: ${mc.total_cost} ({mc.store})")

# Use construction-specific categorization
from wright import CategoryRule, categorize_item

lumberyard_rules = [
    CategoryRule(
        category="Lumber",
        priority=0,
        keywords=["lumber", "plywood", "2x", "stud", "beam"],
    ),
    CategoryRule(
        category="Hardware",
        priority=1,
        keywords=["screw", "nail", "bolt", "anchor", "hanger"],
    ),
    CategoryRule(
        category="Concrete",
        priority=2,
        keywords=["concrete", "cement", "mortar", "post"],
    ),
]
```

### Subclass for construction metadata

```python
from wright import Material


class Lumber(Material):
    grade: str | None = None
    waste_factor: float = 0.10
    species: str | None = None


stud = Lumber(
    name="2x4 Stud",
    quantity=24,
    unit="ft",
    grade="#2",
    species="Douglas Fir",
    waste_factor=0.05,
)
```

## Brewing

A beer recipe as a grain bill with hops and yeast:

```python
from wright import Material, Component

grain_bill = Component(
    name="Mash",
    materials=[
        Material(name="Pilsner Malt", quantity=12, unit="lb"),
        Material(name="Munich Malt", quantity=2, unit="lb"),
        Material(name="Carapils", quantity=1, unit="lb"),
    ],
)
hop_schedule = Component(
    name="Boil Hops",
    materials=[
        Material(name="Hallertau", quantity=2, unit="oz", require_tags=["4.5% AA"]),
        Material(name="Saaz", quantity=1, unit="oz", require_tags=["3.2% AA"]),
    ],
)

# Scale to a 5-gallon batch
five_gallon_grain = grain_bill * 1.0  # 1x = ~15 lb grain bill

# Determine cost per batch
batch_cost = calculate_item_costs(
    grain_bill.materials + hop_schedule.materials,
    supplier_prices,
)
```

## Event planning

Aggregate supplies for a 50-person event:

```python
seating = Component(
    name="Seating",
    materials=[
        Material(name="Folding Chairs", quantity=50, unit="each"),
        Material(
            name="Round Tables", quantity=5, unit="each", require_tags=["60-inch"]
        ),
    ],
)
decor = Component(
    name="Decor",
    materials=[
        Material(name="Table Linens", quantity=5, unit="each", require_tags=["white"]),
        Material(name="Centerpieces", quantity=5, unit="each"),
    ],
)

# Shopping list aggregation works the same way
all_supplies = seating.materials + decor.materials
```

## Manufacturing

An assembly line bill of materials:

```python
chassis = Component(
    name="Chassis Assembly",
    materials=[
        Material(name="Steel Frame", quantity=1, unit="each"),
        Material(name="M8 Bolts", quantity=16, unit="each", require_tags=["stainless"]),
        Material(name="Rubber Feet", quantity=4, unit="each"),
    ],
)
electronics = Component(
    name="Control Board",
    materials=[
        Material(name="PCB v3", quantity=1, unit="each", product_ref="pcb-subassembly"),
        Material(name="Wiring Harness", quantity=1, unit="each"),
    ],
)

# product_ref handles recursive sub-assembly expansion
```

## Supply tracking across domains

Inventory management works the same regardless of domain:

```python
from wright import Stock, SupplyItem

# Track lumber inventory
stock = Stock([
    SupplyItem(name="2x6 Pressure-Treated", quantity=200, unit="ft"),
    SupplyItem(name='3" Deck Screws', quantity=1000, unit="each"),
])

# Deduct what a deck project consumes
stock, remaining = stock.use(framing.materials)
# remaining → list[SupplyItem] with deficit (empty if stock covers it)
```

## See also

- [Examples](examples.md) — copy-paste patterns for every workflow
- [Customization guide](customization.md) — inject custom matchers, pickers, and callbacks
- [API Reference](../api.md) — full function and model documentation
