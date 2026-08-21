"""Configuration: device constant, company taxonomy, environment presets, city/state maps."""

# ---------------------------------------------------------------------------
# Device constant — EgoCapture-1
# ---------------------------------------------------------------------------
DEVICE_CONSTANT = {
    "camera_type": "Egocentric",
    "device_type": "egocapture_headset",
    "device_generation": "EgoCapture-1",
    "device_kit_id": "egocapture_1_kit",
    "device_id_prefix": "egocapture1_",
    "firmware_version": "UNKNOWN - REQUIRED",
    "image_sensor": "SmartSens SC3336P + 185deg fisheye",
    "imu_sensor": "Bosch BMI270 (6-axis)",
}

# ---------------------------------------------------------------------------
# Static per-video blocks (coordinate system, cameras, sensors)
# Populated per-video from these presets; IMU sampling_rate_hz is measured
# from the actual .txt file when available.
# ---------------------------------------------------------------------------
COORDINATE_SYSTEM = {
    "x": "right",
    "y": "down",
    "z": "forward from camera plane",
    "handedness": "right",
}

CAMERA_CONFIGURATION = [
    {
        "camera_name": "ego_camera",
        "sensor_type": "rgb",
        "mounting_location": "head",
        "stream_file": "video.mp4",
        "resolution": {"width": 1920, "height": 1080},
        "frame_rate": 30,
    },
]

SENSORS_TEMPLATE = {
    "imu": {
        "sampling_rate_hz": 200,
        "reference_frame": "ego_head",
        "raw_gyro_accel": True,
    },
}

# ---------------------------------------------------------------------------
# Industry taxonomy
#   Keys used at the CLI prompt are lowercase and stable.
#   For every vertical:
#     operator_job, task_id, task_description, skill_group, dataset_category,
#     action_candidates, object_candidates, subtask_candidates,
#     default_difficulty, indoor_outdoor, additional_tags.
# ---------------------------------------------------------------------------
TAXONOMY = {
    # 1) Diamond ------------------------------------------------------------
    "diamond": {
        "operator_job": "Diamond Craftsman",
        "task_id": "diamond_processing_v1",
        "task_description": "Diamond processing tasks including cleaving, bruting, cutting, polishing, and grading.",
        "skill_group": "Gem & Jewelry",
        "dataset_category": "Industrial - Diamond Processing",
        "action_candidates": [
            "cleaving", "bruting", "cutting", "polishing", "grading",
            "inspecting", "mounting", "cleaning",
        ],
        "object_candidates": [
            "rough_diamond", "polished_diamond", "loupe", "tang", "scaif",
            "polishing_wheel", "tweezers", "microscope", "grading_tray",
        ],
        "subtask_candidates": [
            "facet_polishing", "diamond_grading", "stone_mounting",
            "quality_inspection", "rough_cleaving",
        ],
        "default_difficulty": "hard",
        "indoor_outdoor": "Indoor",
        "additional_tags": ["diamond", "gem", "precision", "manufacturing"],
    },

    # 2) Semiconductor ------------------------------------------------------
    "semiconductor": {
        "operator_job": "Semiconductor Fab Technician",
        "task_id": "semiconductor_fab_v1",
        "task_description": "Semiconductor fab tasks including wafer handling, photolithography prep, etching, wire-bonding, and electrical testing.",
        "skill_group": "Semiconductor Fabrication",
        "dataset_category": "Industrial - Semiconductor",
        "action_candidates": [
            "wafer_handling", "loading_cassette", "aligning", "inspecting",
            "wire_bonding", "probing", "testing", "cleaning",
        ],
        "object_candidates": [
            "wafer", "cassette", "tweezers", "probe_card", "microscope",
            "wire_bonder", "chuck", "cleanroom_gloves", "die",
        ],
        "subtask_candidates": [
            "wafer_load", "die_inspection", "wire_bond_pass",
            "electrical_probe", "cassette_transfer",
        ],
        "default_difficulty": "hard",
        "indoor_outdoor": "Indoor",
        "additional_tags": ["semiconductor", "cleanroom", "fab", "manufacturing"],
    },

    # 3) Electronics --------------------------------------------------------
    "electronics": {
        "operator_job": "Electronics Assembler",
        "task_id": "electronics_assembly_v1",
        "task_description": "Electronics assembly including soldering, component placement, inspection, and wiring.",
        "skill_group": "Electronics Assembly",
        "dataset_category": "Industrial - Electronics",
        "action_candidates": [
            "soldering", "placing", "inspecting", "wiring", "testing",
            "crimping", "screwing", "connector_mating",
        ],
        "object_candidates": [
            "pcb", "solder_iron", "resistor", "capacitor", "ic_chip",
            "wire", "multimeter", "flux", "connector", "screwdriver",
        ],
        "subtask_candidates": [
            "component_placement", "solder_joint", "wire_routing",
            "board_inspection", "connector_assembly",
        ],
        "default_difficulty": "hard",
        "indoor_outdoor": "Indoor",
        "additional_tags": ["electronics", "assembly", "manufacturing"],
    },

    # 4) Furniture ----------------------------------------------------------
    "furniture": {
        "operator_job": "Furniture Maker",
        "task_id": "furniture_manufacturing_v1",
        "task_description": "Furniture manufacturing tasks including sawing, sanding, drilling, assembling, and finishing.",
        "skill_group": "Woodworking & Furniture",
        "dataset_category": "Industrial - Furniture",
        "action_candidates": [
            "sawing", "sanding", "drilling", "assembling", "gluing",
            "clamping", "finishing", "polishing", "screwing",
        ],
        "object_candidates": [
            "wood_plank", "saw", "sander", "drill", "clamp", "glue_bottle",
            "screw", "screwdriver", "brush", "varnish_can",
        ],
        "subtask_candidates": [
            "wood_cutting", "surface_sanding", "joint_assembly",
            "finish_application", "hardware_install",
        ],
        "default_difficulty": "medium",
        "indoor_outdoor": "Indoor",
        "additional_tags": ["furniture", "woodworking", "manufacturing"],
    },

    # 5) Paper --------------------------------------------------------------
    "paper": {
        "operator_job": "Paper Mill Worker",
        "task_id": "paper_processing_v1",
        "task_description": "Paper processing tasks including pulping, sheet forming, roll handling, cutting, and packing.",
        "skill_group": "Pulp & Paper",
        "dataset_category": "Industrial - Paper",
        "action_candidates": [
            "loading", "cutting", "stacking", "inspecting", "roll_handling",
            "trimming", "packing", "labeling",
        ],
        "object_candidates": [
            "paper_roll", "paper_sheet", "cutter", "stacker", "pallet",
            "forklift_horn", "tape_dispenser", "label", "pallet_wrap",
        ],
        "subtask_candidates": [
            "sheet_cutting", "roll_transfer", "stack_alignment",
            "quality_check", "bundle_packing",
        ],
        "default_difficulty": "medium",
        "indoor_outdoor": "Indoor",
        "additional_tags": ["paper", "pulp", "manufacturing"],
    },

    # 6) Household ----------------------------------------------------------
    "household": {
        "operator_job": "Household Worker",
        "task_id": "household_v1",
        "task_description": "Household chores including cooking, cleaning, laundry, and organizing.",
        "skill_group": "Domestic Skills",
        "dataset_category": "Consumer - Household",
        "action_candidates": [
            "cooking", "cleaning", "organizing", "washing", "wiping",
            "arranging", "folding", "sweeping",
        ],
        "object_candidates": [
            "utensil", "pan", "broom", "cloth", "container",
            "sponge", "detergent", "bucket", "mop",
        ],
        "subtask_candidates": [
            "meal_prep", "surface_cleaning", "item_organizing",
            "dishwashing", "laundry_folding",
        ],
        "default_difficulty": "easy",
        "indoor_outdoor": "Indoor",
        "additional_tags": ["household", "domestic"],
    },

    # 7) Looms --------------------------------------------------------------
    "looms": {
        "operator_job": "Loom Operator",
        "task_id": "loom_weaving_v1",
        "task_description": "Loom and weaving tasks including warping, threading, weaving, defect fixing, and beam handling.",
        "skill_group": "Textile Weaving",
        "dataset_category": "Industrial - Looms & Weaving",
        "action_candidates": [
            "warping", "threading", "weaving", "shuttling", "beam_loading",
            "knot_tying", "defect_fixing", "inspecting",
        ],
        "object_candidates": [
            "loom", "warp_yarn", "weft_yarn", "shuttle", "reed",
            "heddle", "beam", "bobbin", "scissors",
        ],
        "subtask_candidates": [
            "warp_threading", "weft_insertion", "defect_repair",
            "beam_change", "fabric_inspection",
        ],
        "default_difficulty": "medium",
        "indoor_outdoor": "Indoor",
        "additional_tags": ["looms", "weaving", "textile", "manufacturing"],
    },

    # 8) Granite & Stone ----------------------------------------------------
    "granite_stone": {
        "operator_job": "Stone Craftsman",
        "task_id": "granite_stone_v1",
        "task_description": "Granite and stone processing including cutting, chiseling, edge shaping, polishing, and slab handling.",
        "skill_group": "Stone & Masonry",
        "dataset_category": "Industrial - Granite & Stone",
        "action_candidates": [
            "cutting", "chiseling", "grinding", "polishing", "edge_shaping",
            "slab_handling", "drilling", "measuring",
        ],
        "object_candidates": [
            "granite_slab", "stone_block", "angle_grinder", "chisel",
            "hammer", "polisher_disc", "water_hose", "measuring_tape", "clamp",
        ],
        "subtask_candidates": [
            "slab_cutting", "edge_polishing", "surface_grinding",
            "chisel_shaping", "slab_transfer",
        ],
        "default_difficulty": "hard",
        "indoor_outdoor": "Indoor",
        "additional_tags": ["granite", "stone", "masonry", "manufacturing"],
    },

    # 9) Cooking ------------------------------------------------------------
    "cooking": {
        "operator_job": "Cook",
        "task_id": "cooking_v1",
        "task_description": "Cooking tasks including chopping, mixing, sauteing, boiling, plating, and cleaning up.",
        "skill_group": "Culinary",
        "dataset_category": "Consumer - Cooking",
        "action_candidates": [
            "chopping", "mixing", "sauteing", "boiling", "frying",
            "stirring", "plating", "seasoning", "washing",
        ],
        "object_candidates": [
            "knife", "cutting_board", "pan", "pot", "spatula",
            "ladle", "bowl", "plate", "stove", "vegetable",
        ],
        "subtask_candidates": [
            "ingredient_prep", "cooking_execution", "plating",
            "kitchen_cleanup", "seasoning_adjustment",
        ],
        "default_difficulty": "medium",
        "indoor_outdoor": "Indoor",
        "additional_tags": ["cooking", "culinary", "home"],
    },

    # 10) Garments ----------------------------------------------------------
    "garments": {
        "operator_job": "Garment Worker",
        "task_id": "garment_manufacturing_v1",
        "task_description": "Garment manufacturing tasks including sewing, stitching, cutting, ironing, and folding.",
        "skill_group": "Textile & Apparel",
        "dataset_category": "Industrial - Garment Manufacturing",
        "action_candidates": [
            "sewing", "stitching", "cutting", "ironing", "folding",
            "measuring", "pinning", "trimming",
        ],
        "object_candidates": [
            "fabric", "needle", "sewing_machine", "thread", "scissors",
            "iron", "measuring_tape", "pins", "chalk_marker",
        ],
        "subtask_candidates": [
            "seam_stitching", "hemming", "pattern_cutting",
            "garment_folding", "pressing",
        ],
        "default_difficulty": "medium",
        "indoor_outdoor": "Indoor",
        "additional_tags": ["garments", "textile", "apparel", "manufacturing"],
    },

    # 11) Mahadev data ------------------------------------------------------
    #     Custom collection under the "Mahadev" project — treated as a generic
    #     assembly / bench-work vertical. Adjust freely as the project firms up.
    "mahadev": {
        "operator_job": "Mahadev Project Operator",
        "task_id": "mahadev_project_v1",
        "task_description": "Mahadev project egocentric captures covering assembly, sorting, packing, and inspection tasks.",
        "skill_group": "General Manual Work",
        "dataset_category": "Project - Mahadev",
        "action_candidates": [
            "assembling", "sorting", "packing", "inspecting", "labeling",
            "moving_item", "measuring", "handling",
        ],
        "object_candidates": [
            "component", "container", "tray", "label", "tool",
            "carton", "packing_tape", "workbench",
        ],
        "subtask_candidates": [
            "item_assembly", "item_sorting", "package_prep",
            "visual_inspection", "workstation_setup",
        ],
        "default_difficulty": "medium",
        "indoor_outdoor": "Indoor",
        "additional_tags": ["mahadev", "project", "manual_work"],
    },

    # 12) Toy Factory Drive data --------------------------------------------
    "toy_factory": {
        "operator_job": "Toy Factory Worker",
        "task_id": "toy_manufacturing_v1",
        "task_description": "Toy manufacturing tasks including molding, part fitting, painting, assembly, quality check, and packing.",
        "skill_group": "Toy Manufacturing",
        "dataset_category": "Industrial - Toys",
        "action_candidates": [
            "molding", "assembling", "painting", "fitting", "gluing",
            "packing", "inspecting", "labeling", "sorting",
        ],
        "object_candidates": [
            "plastic_part", "toy_body", "paint_brush", "glue_gun",
            "mold", "sticker", "carton", "toy_accessory", "screwdriver",
        ],
        "subtask_candidates": [
            "part_molding", "toy_assembly", "paint_application",
            "quality_check", "gift_packing",
        ],
        "default_difficulty": "medium",
        "indoor_outdoor": "Indoor",
        "additional_tags": ["toy", "toys", "assembly", "manufacturing"],
    },
}

# ---------------------------------------------------------------------------
# Environment presets (l1 / l2 / l3)
# ---------------------------------------------------------------------------
ENVIRONMENTS = {
    "diamond_workshop":   {"l1": "Industrial",  "l2": "Manufacturing", "l3": "Diamond Workshop"},
    "semiconductor_fab":  {"l1": "Industrial",  "l2": "Manufacturing", "l3": "Semiconductor Cleanroom"},
    "electronics_lab":    {"l1": "Industrial",  "l2": "Manufacturing", "l3": "Electronics Assembly Line"},
    "furniture_workshop": {"l1": "Industrial",  "l2": "Manufacturing", "l3": "Furniture Workshop"},
    "paper_mill":         {"l1": "Industrial",  "l2": "Manufacturing", "l3": "Paper Mill Floor"},
    "home_general":       {"l1": "Residential", "l2": "Home",          "l3": "Living Area"},
    "home_kitchen":       {"l1": "Residential", "l2": "Home",          "l3": "Kitchen"},
    "loom_floor":         {"l1": "Industrial",  "l2": "Manufacturing", "l3": "Loom / Weaving Floor"},
    "stone_yard":         {"l1": "Industrial",  "l2": "Manufacturing", "l3": "Granite & Stone Yard"},
    "commercial_kitchen": {"l1": "Commercial",  "l2": "Food Service",  "l3": "Commercial Kitchen"},
    "garment_factory":    {"l1": "Industrial",  "l2": "Manufacturing", "l3": "Garment Factory Floor"},
    "mahadev_site":       {"l1": "Industrial",  "l2": "Project Site",  "l3": "Mahadev Workstation"},
    "toy_factory":        {"l1": "Industrial",  "l2": "Manufacturing", "l3": "Toy Factory Floor"},
    # legacy / other
    "auto_plant":         {"l1": "Industrial",  "l2": "Manufacturing", "l3": "Automotive Assembly Line"},
    "food_plant":         {"l1": "Industrial",  "l2": "Manufacturing", "l3": "Food Processing Line"},
}

# ---------------------------------------------------------------------------
# India city → coordinates (for geohash derivation)
# ---------------------------------------------------------------------------
CITY_COORDS = {
    "bengaluru": (12.9716, 77.5946), "bangalore": (12.9716, 77.5946),
    "mumbai": (19.0760, 72.8777),
    "pune": (18.5204, 73.8567),
    "delhi": (28.7041, 77.1025), "new delhi": (28.6139, 77.2090),
    "chennai": (13.0827, 80.2707),
    "coimbatore": (11.0168, 76.9558),
    "hyderabad": (17.3850, 78.4867),
    "kolkata": (22.5726, 88.3639),
    "ahmedabad": (23.0225, 72.5714),
    "surat": (21.1702, 72.8311),
    "jaipur": (26.9124, 75.7873),
    "lucknow": (26.8467, 80.9462),
    "noida": (28.5355, 77.3910),
    "gurgaon": (28.4595, 77.0266), "gurugram": (28.4595, 77.0266),
    "tiruppur": (11.1085, 77.3411),
    "ludhiana": (30.9010, 75.8573),
    "rajkot": (22.3039, 70.8022),
    "bhavnagar": (21.7645, 72.1519),
    "vadodara": (22.3072, 73.1812),
    "indore": (22.7196, 75.8577),
    "nagpur": (21.1458, 79.0882),
    "visakhapatnam": (17.6868, 83.2185),
    "kochi": (9.9312, 76.2673),
    "trivandrum": (8.5241, 76.9366),
}

# ---------------------------------------------------------------------------
# India city → state map
# ---------------------------------------------------------------------------
STATE_MAP = {
    "bengaluru": "Karnataka", "bangalore": "Karnataka",
    "mumbai": "Maharashtra", "pune": "Maharashtra", "nagpur": "Maharashtra",
    "delhi": "Delhi", "new delhi": "Delhi",
    "chennai": "Tamil Nadu", "coimbatore": "Tamil Nadu", "tiruppur": "Tamil Nadu",
    "hyderabad": "Telangana",
    "kolkata": "West Bengal",
    "ahmedabad": "Gujarat", "surat": "Gujarat", "rajkot": "Gujarat",
    "bhavnagar": "Gujarat", "vadodara": "Gujarat",
    "jaipur": "Rajasthan",
    "lucknow": "Uttar Pradesh", "noida": "Uttar Pradesh",
    "gurgaon": "Haryana", "gurugram": "Haryana",
    "ludhiana": "Punjab",
    "indore": "Madhya Pradesh",
    "visakhapatnam": "Andhra Pradesh",
    "kochi": "Kerala", "trivandrum": "Kerala",
}

# ---------------------------------------------------------------------------
# Optional demographic priors per vertical
# (only used when --assume-demographics flag is set; never applied silently)
# ---------------------------------------------------------------------------
DEMOGRAPHIC_PRIORS = {
    "diamond":        {"age_range": "30-34", "gender": "Male",   "handedness": "Right-handed"},
    "semiconductor":  {"age_range": "25-29", "gender": "Female", "handedness": "Right-handed"},
    "electronics":    {"age_range": "25-29", "gender": "Female", "handedness": "Right-handed"},
    "furniture":      {"age_range": "30-34", "gender": "Male",   "handedness": "Right-handed"},
    "paper":          {"age_range": "30-34", "gender": "Male",   "handedness": "Right-handed"},
    "household":      {"age_range": "35-39", "gender": "Female", "handedness": "Right-handed"},
    "looms":          {"age_range": "35-39", "gender": "Female", "handedness": "Right-handed"},
    "granite_stone":  {"age_range": "30-34", "gender": "Male",   "handedness": "Right-handed"},
    "cooking":        {"age_range": "30-34", "gender": "Female", "handedness": "Right-handed"},
    "garments":       {"age_range": "25-29", "gender": "Female", "handedness": "Right-handed"},
    "mahadev":        {"age_range": "25-29", "gender": "Male",   "handedness": "Right-handed"},
    "toy_factory":    {"age_range": "25-29", "gender": "Female", "handedness": "Right-handed"},
}
