"""Indian states / union territories and an approximate PIN code -> state lookup.

PIN prefixes follow India Post's postal circles. Circles don't match state borders exactly,
so this is a best-effort default; field extraction can override it from the tender text.
"""

STATES = [
    "Andaman and Nicobar Islands",
    "Andhra Pradesh",
    "Arunachal Pradesh",
    "Assam",
    "Bihar",
    "Chandigarh",
    "Chhattisgarh",
    "Dadra and Nagar Haveli and Daman and Diu",
    "Delhi",
    "Goa",
    "Gujarat",
    "Haryana",
    "Himachal Pradesh",
    "Jammu and Kashmir",
    "Jharkhand",
    "Karnataka",
    "Kerala",
    "Ladakh",
    "Lakshadweep",
    "Madhya Pradesh",
    "Maharashtra",
    "Manipur",
    "Meghalaya",
    "Mizoram",
    "Nagaland",
    "Odisha",
    "Puducherry",
    "Punjab",
    "Rajasthan",
    "Sikkim",
    "Tamil Nadu",
    "Telangana",
    "Tripura",
    "Uttar Pradesh",
    "Uttarakhand",
    "West Bengal",
]

# (first 3 digits low, high, state). Checked in order; exceptions come first.
_PIN3_RANGES: list[tuple[int, int, str]] = [
    (110, 110, "Delhi"),
    (160, 160, "Chandigarh"),
    (121, 136, "Haryana"),
    (140, 159, "Punjab"),
    (171, 177, "Himachal Pradesh"),
    (194, 194, "Ladakh"),
    (180, 193, "Jammu and Kashmir"),
    (246, 249, "Uttarakhand"),
    (262, 263, "Uttarakhand"),
    (201, 285, "Uttar Pradesh"),
    (301, 345, "Rajasthan"),
    (396, 396, "Dadra and Nagar Haveli and Daman and Diu"),
    (360, 395, "Gujarat"),
    (403, 403, "Goa"),
    (400, 445, "Maharashtra"),
    (490, 497, "Chhattisgarh"),
    (450, 488, "Madhya Pradesh"),
    (500, 509, "Telangana"),
    (533, 533, "Puducherry"),  # Yanam
    (515, 535, "Andhra Pradesh"),
    (560, 591, "Karnataka"),
    (605, 605, "Puducherry"),
    (609, 609, "Puducherry"),  # Karaikal
    (600, 643, "Tamil Nadu"),
    (682, 682, "Kerala"),  # 682 is shared with Lakshadweep (6825xx); Kerala is far more common
    (673, 673, "Kerala"),
    (670, 695, "Kerala"),
    (737, 737, "Sikkim"),
    (744, 744, "Andaman and Nicobar Islands"),
    (700, 743, "West Bengal"),
    (751, 770, "Odisha"),
    (781, 788, "Assam"),
    (790, 792, "Arunachal Pradesh"),
    (793, 794, "Meghalaya"),
    (795, 795, "Manipur"),
    (796, 796, "Mizoram"),
    (797, 798, "Nagaland"),
    (799, 799, "Tripura"),
    (814, 816, "Jharkhand"),
    (822, 822, "Jharkhand"),
    (825, 835, "Jharkhand"),
    (800, 855, "Bihar"),
]


def state_from_pincode(pincode: str | None) -> str | None:
    if not pincode:
        return None
    digits = pincode.strip()
    if len(digits) != 6 or not digits.isdigit():
        return None
    prefix = int(digits[:3])
    for low, high, state in _PIN3_RANGES:
        if low <= prefix <= high:
            return state
    return None
