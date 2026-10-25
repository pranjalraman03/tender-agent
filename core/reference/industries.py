"""Reference data: the fixed industry list and the NIC code -> industry map (first draft;
review before relying on it). Field extraction may only use these slugs."""

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

# (slug, name). Kept small and fixed; field extraction may only use these slugs.
INDUSTRIES = [
    ("civil_construction", "Civil construction & infrastructure works"),
    ("electrical_works", "Electrical works & installations"),
    ("it_services", "IT services, software & hardware"),
    ("facility_management", "Facility management, housekeeping & manpower"),
    ("security_services", "Security services"),
    ("medical_supplies", "Medical equipment & supplies"),
    ("furniture", "Furniture & fixtures"),
    ("vehicles_transport", "Vehicle hire & transport"),
    ("printing_stationery", "Printing & stationery"),
    ("water_sanitation", "Water supply, sanitation & plumbing"),
    ("consulting", "Consulting & professional services"),
    ("machinery_equipment", "Machinery & industrial equipment"),
    ("catering", "Catering & food supply"),
    ("solar_energy", "Solar & renewable energy"),
]

# NIC 2008 code prefix -> industry slug. Longest matching prefix wins at lookup time.
NIC_MAP = [
    ("41", "civil_construction"),
    ("42", "civil_construction"),
    ("4321", "electrical_works"),
    ("4322", "water_sanitation"),
    ("27", "electrical_works"),
    ("62", "it_services"),
    ("63", "it_services"),
    ("2620", "it_services"),
    ("8121", "facility_management"),
    ("8129", "facility_management"),
    ("7810", "facility_management"),
    ("801", "security_services"),
    ("3250", "medical_supplies"),
    ("4772", "medical_supplies"),
    ("310", "furniture"),
    ("4923", "vehicles_transport"),
    ("7710", "vehicles_transport"),
    ("181", "printing_stationery"),
    ("1709", "printing_stationery"),
    ("36", "water_sanitation"),
    ("37", "water_sanitation"),
    ("702", "consulting"),
    ("711", "consulting"),
    ("28", "machinery_equipment"),
    ("562", "catering"),
    ("3510", "solar_energy"),
]


async def seed_reference_data(session: AsyncSession) -> None:
    """Upsert industries and the NIC map. Safe to re-run."""
    for slug, name in INDUSTRIES:
        await session.execute(
            text(
                "INSERT INTO industries (slug, name) VALUES (:slug, :name) "
                "ON CONFLICT (slug) DO UPDATE SET name = EXCLUDED.name"
            ),
            {"slug": slug, "name": name},
        )
    for prefix, slug in NIC_MAP:
        await session.execute(
            text(
                "INSERT INTO nic_industry_map (nic_prefix, industry_slug) "
                "VALUES (:p, :s) ON CONFLICT DO NOTHING"
            ),
            {"p": prefix, "s": slug},
        )
